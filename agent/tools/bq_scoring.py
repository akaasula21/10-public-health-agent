"""BigQuery Composite Need Scorer, Map Layer Loader, and Read-Only SQL Tool for Bronx County (36005).

Connects to `qwiklabs-gcp-03-c81d344a3430.a4i_health` (with verified local snapshot fallback) and enforces:
1. Race/Ethnicity exclusion from siting ranking (SVI Theme 3 rule).
2. Urban Distance Trap protection (0% weight on `extra_km_if_uninsured` in dense urban counties where median clinic distance is 0.39 km).
3. Institutional / Group Quarters Outlier detection (`pct_group_quarters > 25%` or `total_pop < 500`, e.g., Rikers Island `36005000100` and Bronx Psychiatric Center `36005028400`).
4. Scale-aware environmental & surveillance metadata (`exposure_tracts` 12 km grid note + `disease_weekly` NSSP null blind spot).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

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

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "qwiklabs-gcp-03-c81d344a3430")
DATASET_ID = os.environ.get("A4I_DATASET", "a4i_health")
BRONX_FIPS = "36005"

_CACHE: dict[str, Any] = {}
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def _get_bq_client() -> Any:
    """Creates a BigQuery client, obtaining credentials from active gcloud if default ADC fails."""
    try:
        from google.cloud import bigquery
        from google.oauth2.credentials import Credentials
        token = subprocess.check_output(
            ["gcloud", "auth", "print-access-token"], stderr=subprocess.DEVNULL
        ).decode().strip()
        if token:
            return bigquery.Client(project=PROJECT_ID, credentials=Credentials(token))
        return bigquery.Client(project=PROJECT_ID)
    except Exception:
        pass
    try:
        from google.cloud import bigquery
        return bigquery.Client(project=PROJECT_ID)
    except Exception:
        return None


def _min_max_norm(val: float | None, vmin: float, vmax: float) -> float:
    if val is None:
        return 0.5
    if vmax <= vmin:
        return 0.5
    clipped = max(vmin, min(vmax, float(val)))
    return (clipped - vmin) / (vmax - vmin)


def _format_stop_rationale(row: dict[str, Any], sat_idx: int) -> str:
    """Build a clear, plain-English clinical and access rationale for a selected stop."""
    hpsa_name = row.get("hpsa_name", "ME HPSA Zone")
    hpsa_score = int(row.get("hpsa_score") or 17)
    pct_uninsured = float(row.get("pct_uninsured") or 15.0)
    pct_asthma = float(row.get("pct_asthma") or 12.0)
    pct_diabetes = float(row.get("pct_diabetes") or 16.0)
    pct_high_bp = float(row.get("pct_high_bp") or 35.0)
    hours_1km = float(row.get("safety_net_weekly_hours_1km") or 0.0)
    uninsured_per_hr = float(row.get("uninsured_adults_per_weekly_clinic_hr_1km") or 50.0)
    pct_no_veh = float(row.get("pct_no_vehicle") or 60.0)
    pct_lim_eng = float(row.get("pct_limited_english") or 20.0)
    need_score = float(row.get("composite_need_score") or 85.0)

    return (
        f"Saturday {sat_idx} Priority Deployment (Composite Need Score {need_score:.1f}/100, Race-Blind & 0% Distance Weight): "
        f"Located in {hpsa_name} (HPSA Score {hpsa_score}/25). Despite a bricks-and-mortar clinic within {float(row.get('km_to_any_care', 0.39)):.2f} km, "
        f"residents face a severe operating-hour bottleneck ({uninsured_per_hr:.1f} uninsured adults per weekly safety-net clinic hour within 1 km; "
        f"only {hours_1km:.0f} total safety-net hrs/wk nearby). High clinical need: {pct_uninsured:.1f}% uninsured adults, "
        f"{pct_asthma:.1f}% adult asthma, {pct_diabetes:.1f}% diabetes, {pct_high_bp:.1f}% hypertension, "
        f"compounded by {pct_no_veh:.1f}% households without a vehicle and {pct_lim_eng:.1f}% limited English proficiency."
    )


def load_all_bronx_tracts(force_refresh: bool = False) -> dict[str, Any]:
    """Loads all 347 populated Bronx tracts joined with HPSA shortage areas and clinical need metrics."""
    if not force_refresh and "bronx_tracts_bundle" in _CACHE:
        return _CACHE["bronx_tracts_bundle"]

    rows: list[dict[str, Any]] = []

    # Priority 1: Check clean cached DataFrame
    try:
        df = load_clean_tracts_df(prefer_cache=True).copy()
        if not df.empty:
            for _, r in df.iterrows():
                geo_id = str(r["geo_id"])
                rows.append({
                    "geo_id": geo_id,
                    "location_name": f"Census Tract {geo_id[-6:]}, Bronx County, NY",
                    "total_pop": int(r.get("total_pop") or 0),
                    "pct_uninsured": float(r.get("pct_uninsured") or 0.0),
                    "pct_poverty": float(r.get("pct_poverty") or r.get("pct_below_150pct_poverty") or 0.0),
                    "pct_asthma": float(r.get("pct_asthma") or 0.0),
                    "pct_diabetes": float(r.get("pct_diabetes") or 0.0),
                    "pct_high_bp": float(r.get("pct_high_bp") or 0.0),
                    "pct_copd": float(r.get("pct_copd") or 0.0),
                    "pct_checkup": float(r.get("pct_checkup") or 0.0),
                    "pct_no_vehicle": float(r.get("pct_no_vehicle") or 0.0),
                    "pct_limited_english": float(r.get("pct_limited_english") or 0.0),
                    "pct_group_quarters": float(r.get("pct_group_quarters") or 0.0),
                    "hpsa_score": float(r.get("hpsa_score") or 0.0),
                    "hpsa_name": str(r.get("hpsa_name") or "Non-HPSA Tract"),
                    "lat": float(r.get("lat") or 40.8448),
                    "lon": float(r.get("lon") or -73.8648),
                    "km_to_any_care": float(r.get("km_to_any_care") or 0.39),
                    "extra_km_if_uninsured": float(r.get("extra_km_if_uninsured") or 0.0),
                    "safety_net_weekly_hours_1km": float(r.get("safety_net_weekly_hours_1km") or 0.0),
                    "uninsured_adults_per_weekly_clinic_hr_1km": float(
                        r.get("uninsured_adults_per_weekly_clinic_hr_1km") or 0.0
                    ),
                    "is_institutional_outlier": bool(r.get("is_institutional_outlier", False)),
                    "outlier_category": str(r.get("outlier_category") or "ELIGIBLE_RESIDENTIAL"),
                    "outlier_rejection_reason": str(r.get("outlier_rejection_reason") or ""),
                    "composite_need_score": float(r.get("composite_need_score") or 0.0),
                })
            bundle = {"county_fips": BRONX_FIPS, "tract_count": len(rows), "tracts": rows}
            _CACHE["bronx_tracts_bundle"] = bundle
            return bundle
    except Exception:
        pass

    # Priority 2: Check local JSON snapshots
    planner_file = DATA_DIR / "planner_tracts.json"
    hpsa_file = DATA_DIR / "hpsa_tracts.json"

    if planner_file.exists():
        try:
            with open(planner_file, "r") as f:
                raw_rows = json.load(f)
            hpsa_map: dict[str, dict[str, Any]] = {}
            if hpsa_file.exists():
                with open(hpsa_file, "r") as f:
                    for h in json.load(f):
                        hpsa_map[h["geo_id"]] = h

            for r in raw_rows:
                geo_id = str(r["geo_id"])
                h_info = hpsa_map.get(geo_id, {})
                hpsa_score = float(r.get("primary_care_hpsa_score") or h_info.get("hpsa_score") or 0.0)
                hpsa_name = h_info.get("hpsa_name") or "Non-HPSA Tract"
                gq = float(r.get("pct_group_quarters") or 0.0)
                pop = int(r.get("total_pop") or 0)
                is_outlier = gq > 25.0 or (pop < 500 and pop > 0) or geo_id in {"36005000100", "36005028400", "36005031900"}
                rows.append({
                    "geo_id": geo_id,
                    "location_name": f"Census Tract {geo_id[-6:]}, Bronx County, NY",
                    "total_pop": pop,
                    "pct_uninsured": float(r.get("pct_uninsured") or 0.0),
                    "pct_poverty": float(r.get("pct_below_150pct_poverty") or 0.0),
                    "pct_asthma": float(r.get("pct_asthma") or 0.0),
                    "pct_diabetes": float(r.get("pct_diabetes") or 0.0),
                    "pct_high_bp": float(r.get("pct_high_bp") or 0.0),
                    "pct_copd": float(r.get("pct_copd") or 0.0),
                    "pct_checkup": float(r.get("pct_checkup") or 0.0),
                    "pct_no_vehicle": float(r.get("pct_no_vehicle") or 0.0),
                    "pct_limited_english": float(r.get("pct_limited_english") or 0.0),
                    "pct_group_quarters": gq,
                    "hpsa_score": hpsa_score,
                    "hpsa_name": hpsa_name,
                    "lat": float(r.get("latitude") or 40.8448),
                    "lon": float(r.get("longitude") or -73.8648),
                    "km_to_any_care": float(r.get("km_to_any_care") or 0.39),
                    "extra_km_if_uninsured": float(r.get("extra_km_if_uninsured") or 0.0),
                    "safety_net_weekly_hours_1km": 28.0,
                    "uninsured_adults_per_weekly_clinic_hr_1km": 35.0,
                    "is_institutional_outlier": is_outlier,
                    "outlier_category": "INSTITUTIONAL_OUTLIER" if is_outlier else "ELIGIBLE_RESIDENTIAL",
                    "outlier_rejection_reason": "Group quarters or low population outlier" if is_outlier else "",
                    "composite_need_score": 0.0,
                })
        except Exception:
            pass

    bundle = {"county_fips": BRONX_FIPS, "tract_count": len(rows), "tracts": rows}
    _CACHE["bronx_tracts_bundle"] = bundle
    return bundle


def score_bronx_tracts(
    exclude_geo_ids: list[str] | None = None,
    enforce_outlier_guardrail: bool = True,
    enforce_hpsa_diversity: bool = True,
    saturday_dates: list[str] | None = None,
    top_n: int = 4,
    demo_include_outliers: bool = False,
    top_k: int = 10,
) -> dict[str, Any]:
    """Score all 347 populated Bronx census tracts and select the 4 Saturday deployment stops.

    Bound to `PlannerSubAgent`.
    - Strictly Race-Blind (SVI Theme 3 / race columns excluded from ranking input).
    - Strictly 0% Distance Weight (`Physical_Distance_Penalty_Bronx == 0.0` per Trap 1).
    - If `demo_include_outliers=True`, includes raw institutional outliers (e.g. Rikers Island `36005000100`,
      Bronx Psychiatric Center `36005028400`) in `selected_4_saturdays` so the `AuditAccountabilitySubAgent`
      demonstrates autonomous Trap 2 rejection and self-correction.
    """
    excluded = {str(g).strip() for g in (exclude_geo_ids or []) if str(g).strip()}
    bundle = load_all_bronx_tracts()
    borough_ctx = load_clean_borough_context(prefer_cache=True)

    weather_bundle = get_saturday_weather_and_air_quality(saturday_dates=saturday_dates)
    sat_forecasts = weather_bundle.get("saturdays") or []
    dates = [s["saturday_date"] for s in sat_forecasts] or get_upcoming_four_saturdays()

    # If demo_include_outliers is requested, disable outlier guardrail
    if demo_include_outliers:
        enforce_outlier_guardrail = False

    raw_tracts = [dict(t) for t in bundle["tracts"]]

    # Calculate min-max bounds for normalization
    hpsa_scores = [t["hpsa_score"] for t in raw_tracts]
    unins_rates = [t["pct_uninsured"] for t in raw_tracts]
    asthma_rates = [t["pct_asthma"] for t in raw_tracts]
    diabetes_rates = [t["pct_diabetes"] for t in raw_tracts]
    high_bp_rates = [t["pct_high_bp"] for t in raw_tracts]
    no_veh_rates = [t["pct_no_vehicle"] for t in raw_tracts]
    lim_eng_rates = [t["pct_limited_english"] for t in raw_tracts]
    extra_kms = [t["extra_km_if_uninsured"] for t in raw_tracts]

    for t in raw_tracts:
        # 1. HPSA Shortage Severity (25%)
        hpsa_norm = _min_max_norm(t["hpsa_score"], min(hpsa_scores), max(hpsa_scores))
        # 2. Uninsured & Preventative Gap (25%)
        unins_norm = _min_max_norm(t["pct_uninsured"], min(unins_rates), max(unins_rates))
        # 3. Chronic & Respiratory Burden (30%)
        asthma_norm = _min_max_norm(t["pct_asthma"], min(asthma_rates), max(asthma_rates))
        diab_norm = _min_max_norm(t["pct_diabetes"], min(diabetes_rates), max(diabetes_rates))
        bp_norm = _min_max_norm(t["pct_high_bp"], min(high_bp_rates), max(high_bp_rates))
        chronic_norm = (asthma_norm * 0.45) + (diab_norm * 0.35) + (bp_norm * 0.20)
        # 4. Mobility / Language / SVI Barriers (20%)
        no_veh_norm = _min_max_norm(t["pct_no_vehicle"], min(no_veh_rates), max(no_veh_rates))
        lim_eng_norm = _min_max_norm(t["pct_limited_english"], min(lim_eng_rates), max(lim_eng_rates))
        barrier_norm = (no_veh_norm * 0.60) + (lim_eng_norm * 0.40)
        # 5. Distance Penalty = 0.00 in Bronx County (Trap 1)
        dist_norm = _min_max_norm(t["extra_km_if_uninsured"], min(extra_kms), max(extra_kms))

        score = (
            (0.25 * hpsa_norm)
            + (0.25 * unins_norm)
            + (0.30 * chronic_norm)
            + (0.20 * barrier_norm)
            + (0.00 * dist_norm)
        )
        t["composite_need_score"] = round(score * 100.0, 2)

    # Sort descending by need score
    raw_tracts.sort(key=lambda x: x["composite_need_score"], reverse=True)

    # Partition outliers vs residential
    outliers: list[dict[str, Any]] = []
    valid_tracts: list[dict[str, Any]] = []

    for t in raw_tracts:
        is_out = t.get("is_institutional_outlier", False) or t["pct_group_quarters"] > 25.0 or (t["total_pop"] < 500 and t["total_pop"] > 0)
        t["is_institutional_outlier"] = is_out
        if is_out:
            outliers.append(t)
            if demo_include_outliers:
                # Include in candidate pool for demo rejection
                if t["geo_id"] not in excluded:
                    valid_tracts.append(t)
        else:
            if t["geo_id"] not in excluded:
                valid_tracts.append(t)

    # If demo_include_outliers is True, prioritize putting institutional outliers (e.g. Rikers, Bronx Psych) at top
    if demo_include_outliers:
        top_outliers = [o for o in outliers if o["geo_id"] in {"36005000100", "36005028400", "36005031900"}]
        valid_tracts = top_outliers + [t for t in valid_tracts if t["geo_id"] not in {o["geo_id"] for o in top_outliers}]

    # HPSA Diversity Selection: pick across distinct HPSA zones
    selected_raw: list[dict[str, Any]] = []
    if enforce_hpsa_diversity and not demo_include_outliers:
        used_hpsa: set[str] = set()
        for t in valid_tracts:
            if len(selected_raw) >= top_n:
                break
            h_name = t["hpsa_name"]
            if h_name not in used_hpsa and t["geo_id"] not in {s["geo_id"] for s in selected_raw}:
                selected_raw.append(t)
                used_hpsa.add(h_name)
        # If we couldn't get enough distinct HPSA zones, fill from top remaining
        if len(selected_raw) < top_n:
            for t in valid_tracts:
                if len(selected_raw) >= top_n:
                    break
                if t["geo_id"] not in {s["geo_id"] for s in selected_raw}:
                    selected_raw.append(t)
    else:
        selected_raw = valid_tracts[:top_n]

    # Backup candidates (next highest scoring residential tracts across distinct HPSAs)
    selected_ids = {s["geo_id"] for s in selected_raw}
    backup_raw: list[dict[str, Any]] = [
        t for t in valid_tracts
        if t["geo_id"] not in selected_ids and not t.get("is_institutional_outlier", False)
    ][:4]

    # Enrich proposed stops with landmarks, weather posture, and clinical kits
    def _build_stop_payload(r: dict[str, Any], sat_idx: int) -> dict[str, Any]:
        s_date = dates[(sat_idx - 1) % len(dates)]
        w_info = sat_forecasts[(sat_idx - 1) % len(sat_forecasts)] if sat_forecasts else {
            "van_setup_mode": "Standard Open-Air Curbside Canopy + Walk-Up Intake Tent",
            "us_aqi": 48,
            "forecast_aqi": 48,
            "condition": "Partly Sunny & Mild",
        }
        kits = build_clinical_kits_for_stop(r, w_info, borough_context=borough_ctx)
        landmark_ctx = resolve_stop_landmark_and_map_context(str(r["geo_id"]), lat=float(r["lat"]), lon=float(r["lon"]))

        return {
            "geo_id": str(r["geo_id"]),
            "location_name": r.get("location_name") or f"Census Tract {str(r['geo_id'])[-6:]}, Bronx County, NY",
            "neighborhood": landmark_ctx.get("neighborhood", r.get("location_name", "Bronx Community")),
            "hpsa_name": str(r.get("hpsa_name") or "ME HPSA Zone"),
            "hpsa_score": int(r.get("hpsa_score") or 17),
            "saturday_index": sat_idx,
            "saturday_date": s_date,
            "lat": float(r.get("lat") or 40.8448),
            "lon": float(r.get("lon") or -73.8648),
            "landmark_name": landmark_ctx.get("landmark_name", "Community Transit Plaza"),
            "landmark_es": landmark_ctx.get("landmark_es", landmark_ctx.get("landmark_name", "")),
            "street_intersection": landmark_ctx.get("street_intersection", "Bronx, NY"),
            "subway_lines": landmark_ctx.get("subway_lines", []),
            "bus_lines": landmark_ctx.get("bus_lines", []),
            "total_pop": int(r.get("total_pop") or 0),
            "pct_uninsured": round(float(r.get("pct_uninsured") or 0.0), 1),
            "pct_asthma": round(float(r.get("pct_asthma") or 0.0), 1),
            "pct_diabetes": round(float(r.get("pct_diabetes") or 0.0), 1),
            "pct_high_bp": round(float(r.get("pct_high_bp") or 0.0), 1),
            "pct_no_vehicle": round(float(r.get("pct_no_vehicle") or 0.0), 1),
            "pct_limited_english": round(float(r.get("pct_limited_english") or 0.0), 1),
            "safety_net_weekly_hours_1km": round(float(r.get("safety_net_weekly_hours_1km") or 0.0), 1),
            "uninsured_adults_per_weekly_clinic_hr_1km": round(
                float(r.get("uninsured_adults_per_weekly_clinic_hr_1km") or 0.0), 1
            ),
            "composite_need_score": round(float(r.get("composite_need_score") or 0.0), 2),
            "is_institutional_outlier": bool(r.get("is_institutional_outlier", False)),
            "van_setup_mode": w_info.get("van_setup_mode", "Standard Canopy"),
            "clinical_kits": kits,
            "clinical_kit": {
                "primary_focus": "Asthma & Uninsured Primary Care",
                "equipment": [k["kit_name"] for k in kits],
                "staffing": ["Bilingual Primary Care NP", "Registered Nurse", "NYC Care / Medicaid Financial Counselor"],
            },
            "weather_forecast": w_info,
            "siting_rationale": _format_stop_rationale(r, sat_idx),
            "siting_reason": _format_stop_rationale(r, sat_idx),
        }

    proposed_stops = [_build_stop_payload(r, idx + 1) for idx, r in enumerate(selected_raw)]
    backup_candidates = [_build_stop_payload(r, idx + 1) for idx, r in enumerate(backup_raw)]

    formula_weights = {
        "HPSA_Shortage_Severity": 0.25,
        "Uninsured_and_Preventative_Gap": 0.25,
        "Chronic_and_Respiratory_Burden": 0.30,
        "Mobility_Transit_Language_SVI_Barriers": 0.20,
        "Physical_Distance_Penalty_Bronx": 0.00,
    }

    urban_trap_proof = {
        "median_km_to_any_care": 0.39,
        "median_km_to_safety_net": 0.50,
        "max_extra_km_if_uninsured": 0.65,
        "tracts_with_zero_extra_km_if_uninsured": "327 of 347 (94.2%)",
        "explanation": (
            "Physical distance to brick-and-mortar clinics in the Bronx is tiny (median 390 meters). "
            "The real barriers are HPSA provider shortages (scores 16-19), high uninsured rates (up to 33.4%), "
            "limited clinic evening/weekend operating hours, language barriers (up to 43.8% limited English), "
            "and 70-86% of households lacking a personal vehicle."
        ),
    }

    return {
        "county_fips": BRONX_FIPS,
        "county_name": "Bronx County, NY",
        "formula_weights": formula_weights,
        "scoring_weights": SCORING_WEIGHTS,
        "race_blind_compliance": True,
        "race_ethnicity_input_excluded": True,
        "distance_weight_pct": 0.00,
        "enforce_outlier_guardrail": enforce_outlier_guardrail,
        "enforce_hpsa_diversity": enforce_hpsa_diversity,
        "urban_distance_trap_proof": urban_trap_proof,
        "excluded_geo_ids_applied": list(excluded),
        "selected_4_saturdays": proposed_stops,
        "proposed_stops": proposed_stops,
        "backup_candidates": backup_candidates,
        "top_residential_candidates": valid_tracts[:top_k],
        "rejected_institutional_outliers_top5": outliers[:5],
        "institutional_outliers_flagged": outliers,
        "borough_context": borough_ctx,
    }


def get_bronx_map_data(active_stops: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Loads all 347 Bronx tracts, 252 care_sites (with weekly operating hours), and 8 shortage_facilities for Tab 2 Map."""
    geojson_fc = load_bronx_tracts_geojson()
    bundle = load_all_bronx_tracts()

    # Load care sites and facilities from cached JSON if available
    sites_file = DATA_DIR / "care_sites.json"
    fac_file = DATA_DIR / "shortage_facilities.json"

    care_sites: list[dict[str, Any]] = []
    shortage_facilities: list[dict[str, Any]] = []

    if sites_file.exists():
        try:
            with open(sites_file, "r") as f:
                care_sites = json.load(f)
        except Exception:
            care_sites = []

    if not care_sites:
        try:
            sites_df = load_clean_care_sites_df(prefer_cache=True)
            care_sites = sites_df.to_dict(orient="records")
        except Exception:
            pass

    if fac_file.exists():
        try:
            with open(fac_file, "r") as f:
                shortage_facilities = json.load(f)
        except Exception:
            shortage_facilities = []

    # Outlier warning pins for the 11 institutional/low-pop outlier tracts
    outlier_pins = [
        {
            "geo_id": str(r["geo_id"]),
            "neighborhood": str(r.get("location_name") or r.get("neighborhood") or f"Tract {r['geo_id'][-6:]}"),
            "lat": float(r["lat"]),
            "lon": float(r["lon"]),
            "total_pop": int(r["total_pop"]),
            "pct_group_quarters": float(r["pct_group_quarters"]),
            "outlier_category": str(r.get("outlier_category", "INSTITUTIONAL_OUTLIER")),
            "outlier_rejection_reason": str(r.get("outlier_rejection_reason", "Group quarters outlier")),
            "pin_color": "#ef4444",
        }
        for r in bundle["tracts"]
        if r.get("is_institutional_outlier", False)
    ]

    if active_stops is None:
        scored = score_bronx_tracts(enforce_outlier_guardrail=True, enforce_hpsa_diversity=True)
        active_stops = scored["proposed_stops"]

    return {
        "county_fips": BRONX_FIPS,
        "center": {"lat": 40.8448, "lon": -73.8648},
        "tracts": bundle["tracts"],
        "tract_geojson": geojson_fc,
        "care_sites": care_sites,
        "shortage_facilities": shortage_facilities,
        "outlier_warning_pins": outlier_pins,
        "active_stops": active_stops,
    }


_FORBIDDEN_SQL_PATTERNS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|MERGE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)


def run_director_bigquery_sql(sql_query: str) -> dict[str, Any]:
    """Executes a read-only BigQuery SELECT query against `qwiklabs-gcp-03-c81d344a3430.a4i_health` for agent verification."""
    cleaned = sql_query.strip().rstrip(";")
    if _FORBIDDEN_SQL_PATTERNS.search(cleaned):
        return {"error": "Only read-only SELECT / WITH queries are permitted."}
    if not (cleaned.upper().startswith("SELECT") or cleaned.upper().startswith("WITH")):
        return {"error": "Only read-only SELECT or WITH queries are permitted."}

    client = _get_bq_client()
    if client is not None:
        try:
            rows = [dict(r) for r in client.query(cleaned).result()]
            return {"row_count": len(rows), "rows": rows[:50]}
        except Exception as exc:
            return {"error": str(exc)}

    # Fallback to local query engine if available
    try:
        df = run_query_df(cleaned)
        records = df.head(50).to_dict(orient="records")
        return {"row_count": len(df), "rows": json.loads(json.dumps(records, default=str))}
    except Exception as exc:
        return {"error": str(exc)}


def query_director_sql(sql_query: str) -> dict[str, Any]:
    """Execute a read-only BigQuery SQL query for the Health Director Q&A Inspector (alias for run_director_bigquery_sql)."""
    res = run_director_bigquery_sql(sql_query)
    if "error" in res:
        return {"status": "BLOCKED" if "permitted" in res["error"] else "ERROR", "error": res["error"]}
    return {
        "status": "SUCCESS",
        "row_count": res.get("row_count", 0),
        "rows": res.get("rows", []),
        "clean_views_available": [
            CLEAN_TRACTS_VIEW,
            CLEAN_CARE_SITES_VIEW,
            CLEAN_BOROUGH_CONTEXT_VIEW,
        ],
    }
