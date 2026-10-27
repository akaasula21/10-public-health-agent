"""Race-blind, 0%-distance tract scoring, map data loader, and guardrailed Director SQL tool."""

from __future__ import annotations

import json
import re
from typing import Any

import pandas as pd

from agent.config import (
    CLEAN_BOROUGH_CONTEXT_VIEW,
    CLEAN_CARE_SITES_VIEW,
    CLEAN_TRACTS_VIEW,
    SCORING_WEIGHTS,
)
from agent.data.bq_client import (
    load_bronx_tracts_geojson,
    load_clean_borough_context,
    load_clean_care_sites_df,
    load_clean_tracts_df,
    run_query_df,
)
from agent.tools.maps_landmarks import resolve_stop_landmark_and_map_context
from agent.tools.weather_aq import (
    build_clinical_kits_for_stop,
    get_saturday_weather_and_air_quality,
    get_upcoming_four_saturdays,
)


def _format_stop_rationale(row: dict[str, Any], sat_idx: int) -> str:
    """Build a clear, plain-English clinical and access rationale for a selected stop."""
    hpsa_name = row.get("hpsa_name", "ME HPSA Zone")
    hpsa_score = int(row.get("hpsa_score", 17))
    pct_uninsured = float(row.get("pct_uninsured", 15.0))
    pct_asthma = float(row.get("pct_asthma", 12.0))
    pct_diabetes = float(row.get("pct_diabetes", 16.0))
    pct_high_bp = float(row.get("pct_high_bp", 35.0))
    hours_1km = float(row.get("safety_net_weekly_hours_1km", 0.0))
    uninsured_per_hr = float(row.get("uninsured_adults_per_weekly_clinic_hr_1km", 50.0))
    pct_no_veh = float(row.get("pct_no_vehicle", 60.0))
    pct_lim_eng = float(row.get("pct_limited_english", 20.0))
    need_score = float(row.get("composite_need_score", 85.0))

    return (
        f"Saturday {sat_idx} Priority Deployment (Composite Need Score {need_score:.1f}/100, Race-Blind & 0% Distance Weight): "
        f"Located in {hpsa_name} (HPSA Score {hpsa_score}/25). Despite a bricks-and-mortar clinic within {float(row.get('km_to_any_care', 0.39)):.2f} km, "
        f"residents face a severe operating-hour bottleneck ({uninsured_per_hr:.1f} uninsured adults per weekly safety-net clinic hour within 1 km; "
        f"only {hours_1km:.0f} total safety-net hrs/wk nearby). High clinical need: {pct_uninsured:.1f}% uninsured adults, "
        f"{pct_asthma:.1f}% adult asthma, {pct_diabetes:.1f}% diabetes, {pct_high_bp:.1f}% hypertension, "
        f"compounded by {pct_no_veh:.1f}% households without a vehicle and {pct_lim_eng:.1f}% limited English proficiency."
    )


def score_bronx_tracts(
    exclude_geo_ids: list[str] | None = None,
    enforce_outlier_guardrail: bool = True,
    enforce_hpsa_diversity: bool = True,
    saturday_dates: list[str] | None = None,
    top_n: int = 4,
) -> dict[str, Any]:
    """Score all 347 populated Bronx census tracts and select the 4 Saturday deployment stops.

    Bound to `PlannerSubAgent`.
    - Strictly Race-Blind (SVI Theme 3 / race columns are not present in `v_clean_bronx_tracts`).
    - Strictly 0% Distance Weight (`SCORING_WEIGHTS['physical_distance_km'] == 0.0` per Trap 1).
    - If `enforce_outlier_guardrail=False` (used in Iteration 1 self-correction demo), includes raw top-scoring
      institutional outliers (e.g., Bronx Psychiatric Center `36005028400`, Rikers Island `36005000100`) so the
      `AuditAccountabilitySubAgent` can demonstrate autonomous Trap 2 rejection and self-correction.
    """
    excluded = {str(g).strip() for g in (exclude_geo_ids or []) if g}
    df = load_clean_tracts_df(prefer_cache=True).copy()
    borough_ctx = load_clean_borough_context(prefer_cache=True)
    weather_bundle = get_saturday_weather_and_air_quality(saturday_dates=saturday_dates)
    sat_forecasts = weather_bundle["saturdays"]
    dates = [s["saturday_date"] for s in sat_forecasts]

    # Separate institutional outliers for transparency & Tab 2 Red Warning Pins
    outliers_df = df[df["is_institutional_outlier"]].sort_values("composite_need_score", ascending=False)
    outliers_list = [
        {
            "geo_id": str(r["geo_id"]),
            "neighborhood": str(r.get("neighborhood", "")),
            "total_pop": int(r["total_pop"]),
            "pct_group_quarters": float(r["pct_group_quarters"]),
            "hpsa_name": str(r["hpsa_name"]),
            "hpsa_score": int(r["hpsa_score"]),
            "composite_need_score": float(r["composite_need_score"]),
            "outlier_category": str(r["outlier_category"]),
            "outlier_rejection_reason": str(r["outlier_rejection_reason"]),
            "lat": float(r["lat"]),
            "lon": float(r["lon"]),
        }
        for _, r in outliers_df.iterrows()
    ]

    # Filter excluded geo_ids
    pool_df = df[~df["geo_id"].astype(str).isin(excluded)].copy()
    if enforce_outlier_guardrail:
        pool_df = pool_df[~pool_df["is_institutional_outlier"]].copy()

    pool_df = pool_df.sort_values("composite_need_score", ascending=False)

    selected_rows: list[dict[str, Any]] = []
    used_hpsa_zones: set[str] = set()
    used_geo_ids: set[str] = set()

    if not enforce_outlier_guardrail:
        # Naive Iteration 1 mode: inject top institutional outlier (Bronx Psychiatric Center 36005028400 or Rikers 36005000100)
        # alongside top raw tracts so AuditAccountabilitySubAgent catches Trap 2 & HPSA clustering
        top_outlier = outliers_df[outliers_df["geo_id"].isin(["36005028400", "36005000100"])].head(1)
        if not top_outlier.empty:
            rdict = top_outlier.iloc[0].to_dict()
            selected_rows.append(rdict)
            used_geo_ids.add(str(rdict["geo_id"]))

    # Select top stops with HPSA diversity across the 7 Bronx ME HPSA zones when enabled
    for _, row in pool_df.iterrows():
        if len(selected_rows) >= top_n:
            break
        gid = str(row["geo_id"])
        if gid in used_geo_ids:
            continue
        hpsa_nm = str(row["hpsa_name"])
        if enforce_hpsa_diversity and hpsa_nm in used_hpsa_zones and len(used_hpsa_zones) < 4:
            continue
        selected_rows.append(row.to_dict())
        used_geo_ids.add(gid)
        used_hpsa_zones.add(hpsa_nm)

    # Backfill if needed
    if len(selected_rows) < top_n:
        for _, row in pool_df.iterrows():
            if len(selected_rows) >= top_n:
                break
            gid = str(row["geo_id"])
            if gid not in used_geo_ids:
                selected_rows.append(row.to_dict())
                used_geo_ids.add(gid)

    # Select next 6 clean residential backup stops for HITL re-planning
    backup_rows: list[dict[str, Any]] = []
    clean_remaining = df[(~df["is_institutional_outlier"]) & (~df["geo_id"].astype(str).isin(used_geo_ids | excluded))].sort_values(
        "composite_need_score", ascending=False
    )
    for _, row in clean_remaining.head(6).iterrows():
        backup_rows.append(row.to_dict())

    def _build_stop_payload(r: dict[str, Any], sat_idx: int) -> dict[str, Any]:
        gid = str(r["geo_id"])
        lat, lon = float(r["lat"]), float(r["lon"])
        lm = resolve_stop_landmark_and_map_context(gid, lat, lon)
        w_info = sat_forecasts[(sat_idx - 1) % len(sat_forecasts)]
        kits = build_clinical_kits_for_stop(r, w_info, borough_ctx)
        return {
            "saturday_index": sat_idx,
            "saturday_date": dates[(sat_idx - 1) % len(dates)],
            "geo_id": gid,
            "neighborhood": lm["neighborhood"],
            "sub_corridor": lm.get("sub_corridor", ""),
            "hpsa_name": str(r["hpsa_name"]),
            "hpsa_score": int(r["hpsa_score"]),
            "landmark_name": lm["landmark_name"],
            "street_intersection": lm["street_intersection"],
            "subway_lines": lm["subway_lines"],
            "bus_lines": lm["bus_lines"],
            "google_maps_url": lm["google_maps_url"],
            "street_view_url": lm["street_view_url"],
            "earth_3d_url": lm["earth_3d_url"],
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "total_pop": int(r["total_pop"]),
            "pct_group_quarters": round(float(r.get("pct_group_quarters", 0.0)), 2),
            "is_institutional_outlier": bool(r.get("is_institutional_outlier", False)),
            "outlier_category": str(r.get("outlier_category", "RESIDENTIAL_ELIGIBLE")),
            "pct_uninsured": round(float(r["pct_uninsured"]), 2),
            "pct_asthma": round(float(r["pct_asthma"]), 2),
            "pct_diabetes": round(float(r["pct_diabetes"]), 2),
            "pct_high_bp": round(float(r["pct_high_bp"]), 2),
            "pct_no_vehicle": round(float(r["pct_no_vehicle"]), 2),
            "pct_limited_english": round(float(r["pct_limited_english"]), 2),
            "safety_net_weekly_hours_1km": round(float(r.get("safety_net_weekly_hours_1km", 0.0)), 1),
            "uninsured_adults_per_weekly_clinic_hr_1km": round(
                float(r.get("uninsured_adults_per_weekly_clinic_hr_1km", 0.0)), 1
            ),
            "composite_need_score": round(float(r["composite_need_score"]), 2),
            "van_setup_mode": w_info["van_setup_mode"],
            "clinical_kits": kits,
            "weather_forecast": w_info,
            "siting_rationale": _format_stop_rationale(r, sat_idx),
        }

    proposed_stops = [_build_stop_payload(r, idx + 1) for idx, r in enumerate(selected_rows)]
    backup_candidates = [_build_stop_payload(r, idx + 1) for idx, r in enumerate(backup_rows)]

    return {
        "county_fips": "36005",
        "county_name": "Bronx County, NY",
        "scoring_weights": SCORING_WEIGHTS,
        "race_blind_compliance": True,
        "distance_weight_pct": 0.0,
        "enforce_outlier_guardrail": enforce_outlier_guardrail,
        "enforce_hpsa_diversity": enforce_hpsa_diversity,
        "proposed_stops": proposed_stops,
        "backup_candidates": backup_candidates,
        "institutional_outliers_flagged": outliers_list,
        "borough_context": borough_ctx,
    }


def get_bronx_map_data(active_stops: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return the 4-layer spatial dataset for Tab 2 (Interactive Bronx Map & Earth View).

    Layers:
    1. `tract_geojson`: 347 populated Bronx 2020 census tract polygons with need scores & metrics.
    2. `care_sites`: 252 Bronx clinics color-coded by operating hours (`TOT_OPER_HR_PER_WEEK`).
    3. `outlier_warning_pins`: Red Warning Pins for the 11 institutional/low-pop outlier tracts rejected by Trap 2.
    4. `active_stops`: The 4 active Saturday deployment stops with Street View & 3D Earth View URLs.
    """
    geojson_fc = load_bronx_tracts_geojson()
    sites_df = load_clean_care_sites_df(prefer_cache=True)
    tracts_df = load_clean_tracts_df(prefer_cache=True)

    outliers_df = tracts_df[tracts_df["is_institutional_outlier"]].sort_values("pct_group_quarters", ascending=False)
    outlier_pins = [
        {
            "geo_id": str(r["geo_id"]),
            "neighborhood": str(r.get("neighborhood", "")),
            "landmark_name": str(r.get("landmark_name", "")),
            "lat": float(r["lat"]),
            "lon": float(r["lon"]),
            "total_pop": int(r["total_pop"]),
            "pct_group_quarters": float(r["pct_group_quarters"]),
            "outlier_category": str(r["outlier_category"]),
            "outlier_rejection_reason": str(r["outlier_rejection_reason"]),
            "pin_color": "#ef4444",  # Red Warning Pin
        }
        for _, r in outliers_df.iterrows()
    ]

    care_sites_list = sites_df.to_dict(orient="records")
    if active_stops is None:
        scored = score_bronx_tracts(enforce_outlier_guardrail=True, enforce_hpsa_diversity=True)
        active_stops = scored["proposed_stops"]

    return {
        "tract_geojson": geojson_fc,
        "care_sites": care_sites_list,
        "outlier_warning_pins": outlier_pins,
        "active_stops": active_stops,
    }


_FORBIDDEN_SQL_PATTERNS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|MERGE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)


def query_director_sql(sql_query: str) -> dict[str, Any]:
    """Execute a read-only BigQuery SQL query for the Tab 4 Health Director Q&A Inspector.

    Enforces SELECT/WITH-only read guardrails and limits output to 100 rows.
    """
    cleaned_sql = sql_query.strip().rstrip(";")
    if _FORBIDDEN_SQL_PATTERNS.search(cleaned_sql):
        return {
            "status": "BLOCKED",
            "error": "Only read-only SELECT / WITH queries are permitted by the Director SQL tool.",
        }
    if not (cleaned_sql.upper().startswith("SELECT") or cleaned_sql.upper().startswith("WITH")):
        return {
            "status": "BLOCKED",
            "error": "Query must begin with SELECT or WITH.",
        }

    try:
        df = run_query_df(cleaned_sql)
        records = df.head(100).to_dict(orient="records")
        return {
            "status": "SUCCESS",
            "row_count": len(df),
            "rows": json.loads(json.dumps(records, default=str)),
            "clean_views_available": [
                CLEAN_TRACTS_VIEW,
                CLEAN_CARE_SITES_VIEW,
                CLEAN_BOROUGH_CONTEXT_VIEW,
            ],
        }
    except Exception as exc:
        return {
            "status": "ERROR",
            "error": str(exc),
        }
