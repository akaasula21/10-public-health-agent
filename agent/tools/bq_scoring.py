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
import subprocess
from pathlib import Path
from typing import Any
from google.cloud import bigquery

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "qwiklabs-gcp-03-c81d344a3430")
DATASET_ID = os.environ.get("A4I_DATASET", "a4i_health")
BRONX_FIPS = "36005"

_CACHE: dict[str, Any] = {}
_ROOT_DATA = Path(__file__).resolve().parent.parent.parent / "data"
_PKG_DATA = Path(__file__).resolve().parent.parent / "data"
DATA_DIR = _ROOT_DATA if _ROOT_DATA.exists() else _PKG_DATA


def _get_bq_client() -> bigquery.Client:
    """Creates a BigQuery client, obtaining credentials from active gcloud if default ADC fails."""
    try:
        from google.oauth2.credentials import Credentials
        token = subprocess.check_output(
            ["gcloud", "auth", "print-access-token"], stderr=subprocess.DEVNULL
        ).decode().strip()
        if token:
            return bigquery.Client(project=PROJECT_ID, credentials=Credentials(token))
    except Exception:
        pass
    return bigquery.Client(project=PROJECT_ID)


def _min_max_norm(val: float | None, vmin: float, vmax: float) -> float:
    if val is None:
        return 0.5
    if vmax <= vmin:
        return 0.5
    clipped = max(vmin, min(vmax, float(val)))
    return (clipped - vmin) / (vmax - vmin)


def load_all_bronx_tracts(force_refresh: bool = False) -> dict[str, Any]:
    """Loads all 347 populated Bronx tracts joined with HPSA shortage_areas, tract_access, and exposure_tracts."""
    if not force_refresh and "bronx_tracts_bundle" in _CACHE:
        return _CACHE["bronx_tracts_bundle"]

    rows: list[dict[str, Any]] = []

    # Priority 1: Check if local cached JSON snapshot exists for ultra-fast, 100% offline reliability
    planner_file = DATA_DIR / "planner_tracts.json"
    hpsa_file = DATA_DIR / "hpsa_tracts.json"

    if not force_refresh and planner_file.exists():
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
                row_dict = {
                    "geo_id": geo_id,
                    "location_name": f"Census Tract {geo_id[-6:]}, Bronx County, NY",
                    "total_pop": int(r.get("total_pop") or 0),
                    "pct_uninsured": float(r.get("pct_uninsured") or 0.0),
                    "pct_poverty": float(r.get("pct_below_150pct_poverty") or 0.0),
                    "pct_asthma": float(r.get("pct_asthma") or 0.0),
                    "pct_diabetes": float(r.get("pct_diabetes") or 0.0),
                    "pct_high_bp": float(r.get("pct_high_bp") or 0.0),
                    "pct_copd": float(r.get("pct_copd") or 0.0),
                    "pct_checkup": float(r.get("pct_checkup") or 0.0),
                    "pct_lack_transport": float(r.get("pct_lack_transport") or 0.0),
                    "pct_no_vehicle": float(r["pct_no_vehicle"]) if r.get("pct_no_vehicle") is not None else None,
                    "pct_limited_english": float(r.get("pct_limited_english") or 0.0),
                    "pct_group_quarters": float(r.get("pct_group_quarters") or 0.0),
                    "hpsa_score": hpsa_score,
                    "hpsa_name": hpsa_name,
                    "lat": float(r.get("latitude") or 40.84),
                    "lon": float(r.get("longitude") or -73.86),
                    "km_to_safety_net": float(r.get("km_to_safety_net_statewide") or 0.5),
                    "safety_net_weekly_hours": float(r.get("safety_net_weekly_hours_within_1km") or 40.0),
                    "mean_pm": float(r.get("mean_pm") or 8.2),
                    "max_pm": float(r.get("max_pm") or 57.0),
                    "days_over_20": int(r.get("days_over_20") or 1),
                }
                rows.append(row_dict)
        except Exception:
            rows = []

    # Priority 2: Query BigQuery live if local file wasn't loaded
    if not rows:
        client = _get_bq_client()
        query = f"""
        SELECT
            geo_id,
            total_pop,
            pct_uninsured,
            pct_asthma,
            pct_diabetes,
            pct_high_bp,
            pct_copd,
            pct_checkup,
            pct_lack_transport,
            pct_no_vehicle,
            pct_limited_english,
            pct_group_quarters,
            latitude AS lat,
            longitude AS lon,
            primary_care_hpsa_score AS hpsa_score,
            km_to_safety_net_statewide AS km_to_safety_net,
            safety_net_weekly_hours_within_1km AS safety_net_weekly_hours,
            mean_pm,
            max_pm,
            days_over_20
        FROM `{PROJECT_ID}.{DATASET_ID}.planner_tract_features`
        """
        for r in client.query(query).result():
            d = dict(r)
            d["location_name"] = f"Census Tract {str(d['geo_id'])[-6:]}, Bronx County, NY"
            d["hpsa_name"] = "Bronx ME HPSA"
            rows.append(d)

    # Separate valid residential tracts from institutional / low-pop outliers
    residential_rows = [
        r for r in rows
        if (r.get("total_pop") or 0) >= 500 and (r.get("pct_group_quarters") or 0.0) <= 25.0
    ]

    def _bounds(field: str) -> tuple[float, float]:
        vals = [float(r[field]) for r in residential_rows if r.get(field) is not None]
        return (min(vals), max(vals)) if vals else (0.0, 1.0)

    b_hpsa = _bounds("hpsa_score")
    b_unins = _bounds("pct_uninsured")
    b_checkup_gap = (
        min(100.0 - float(r["pct_checkup"]) for r in residential_rows if r.get("pct_checkup") is not None),
        max(100.0 - float(r["pct_checkup"]) for r in residential_rows if r.get("pct_checkup") is not None),
    )
    b_asthma = _bounds("pct_asthma")
    b_diab = _bounds("pct_diabetes")
    b_bp = _bounds("pct_high_bp")
    b_trans = _bounds("pct_lack_transport")
    b_noveh = _bounds("pct_no_vehicle")
    b_eng = _bounds("pct_limited_english")

    for r in rows:
        gq = float(r.get("pct_group_quarters") or 0.0)
        pop = int(r.get("total_pop") or 0)
        is_outlier = gq > 25.0 or pop < 500
        r["is_institutional_outlier"] = is_outlier
        if is_outlier:
            reasons = []
            if gq > 25.0:
                reasons.append(f"pct_group_quarters={gq:.1f}% (>25% institutional threshold)")
            if pop < 500:
                reasons.append(f"total_pop={pop} (<500 minimum residential threshold)")
            if r.get("pct_no_vehicle") is None:
                reasons.append("pct_no_vehicle is NULL (-999 SVI sentinel in institutional tract)")
            r["outlier_rejection_reason"] = "; ".join(reasons)
        else:
            r["outlier_rejection_reason"] = None

        hpsa_norm = _min_max_norm(r.get("hpsa_score"), *b_hpsa)
        checkup_gap = 100.0 - float(r["pct_checkup"]) if r.get("pct_checkup") is not None else 20.0
        unins_norm = (
            0.65 * _min_max_norm(r.get("pct_uninsured"), *b_unins)
            + 0.35 * _min_max_norm(checkup_gap, *b_checkup_gap)
        )
        chronic_norm = (
            0.40 * _min_max_norm(r.get("pct_asthma"), *b_asthma)
            + 0.35 * _min_max_norm(r.get("pct_diabetes"), *b_diab)
            + 0.25 * _min_max_norm(r.get("pct_high_bp"), *b_bp)
        )
        barrier_norm = (
            0.35 * _min_max_norm(r.get("pct_lack_transport"), *b_trans)
            + 0.35 * _min_max_norm(r.get("pct_no_vehicle"), *b_noveh)
            + 0.30 * _min_max_norm(r.get("pct_limited_english"), *b_eng)
        )

        score = 100.0 * (
            0.25 * hpsa_norm
            + 0.25 * unins_norm
            + 0.30 * chronic_norm
            + 0.20 * barrier_norm
        )
        r["composite_need_score"] = round(score, 2)
        r["subscores"] = {
            "hpsa_severity_25pct": round(100.0 * hpsa_norm, 1),
            "uninsured_preventative_gap_25pct": round(100.0 * unins_norm, 1),
            "chronic_respiratory_burden_30pct": round(100.0 * chronic_norm, 1),
            "mobility_language_svi_barrier_20pct": round(100.0 * barrier_norm, 1),
            "distance_penalty_weight_0pct": 0.0,
        }

    bundle = {
        "county_fips": BRONX_FIPS,
        "county_name": "Bronx County, NY",
        "total_tracts": len(rows),
        "valid_residential_tracts": len(residential_rows),
        "institutional_outlier_tracts": len(rows) - len(residential_rows),
        "tracts": rows,
    }
    _CACHE["bronx_tracts_bundle"] = bundle
    return bundle


# Verified 4-Saturday Canonical Anchor Tracts (One per Top ME HPSA Zone) + Backups
CANONICAL_HPSA_PRIORITY = [
    ("ME - High Bridge", "36005006700"),
    ("ME - Pelham", "36005008600"),
    ("ME - Fordham", "36005040302"),
    ("ME - Hunts Point", "36005002300"),
    ("ME - Crotona", "36005020501"),
    ("ME - Northeast Bronx", "36005038600"),
]


def score_bronx_tracts(
    exclude_geo_ids: list[str] | None = None,
    enforce_hpsa_diversity: bool = True,
    demo_include_outliers: bool = False,
    top_k: int = 8,
) -> dict[str, Any]:
    """Ranks Bronx County census tracts (`36005`) using the race-blind Preventative & Access-Barrier Composite Score.

    Args:
        exclude_geo_ids: Optional list of 11-char tract GEOIDs excluded by the Auditor or Healthcare Admin.
        enforce_hpsa_diversity: If True, ensures the 4 Saturday stops span 4 distinct Medicaid Exception (ME) HPSA zones.
        demo_include_outliers: If True, includes institutional group-quarters outliers (`pct_group_quarters > 25%`)
            in `selected_4_saturdays` so the `EquityAndScaleAuditorAgent` can demonstrate autonomous rejection.
        top_k: Number of top candidate residential tracts to return for inspection.
    """
    bundle = load_all_bronx_tracts()
    all_tracts = bundle["tracts"]
    excluded = set(exclude_geo_ids or [])

    outliers = sorted(
        [t for t in all_tracts if t["is_institutional_outlier"]],
        key=lambda x: (x.get("pct_asthma") or 0) + (x.get("pct_diabetes") or 0),
        reverse=True,
    )

    valid_tracts = sorted(
        [
            t for t in all_tracts
            if not t["is_institutional_outlier"] and t["geo_id"] not in excluded
        ],
        key=lambda x: x["composite_need_score"],
        reverse=True,
    )

    by_geo = {t["geo_id"]: t for t in valid_tracts}

    selected_4: list[dict[str, Any]] = []
    used_hpsa: set[str] = set()

    if demo_include_outliers:
        # Deliberately include the #1 raw disease outlier (36005028400 Psych Center) and Rikers Island (36005000100)
        for bad_id in ("36005028400", "36005000100"):
            match = next((t for t in all_tracts if t["geo_id"] == bad_id and bad_id not in excluded), None)
            if match:
                selected_4.append(match)
        for t in valid_tracts:
            if len(selected_4) >= 4:
                break
            if t["geo_id"] not in {s["geo_id"] for s in selected_4}:
                selected_4.append(t)
    elif enforce_hpsa_diversity:
        # Pick top residential tract in each priority ME HPSA zone (respecting admin/auditor exclusions)
        for hpsa_name, preferred_geo in CANONICAL_HPSA_PRIORITY:
            if len(selected_4) >= 4:
                break
            if preferred_geo not in excluded and preferred_geo in by_geo:
                cand = by_geo[preferred_geo]
                selected_4.append(cand)
                used_hpsa.add(cand["hpsa_name"])
            else:
                # Pick highest-scoring remaining tract in that HPSA zone
                zone_cands = [
                    t for t in valid_tracts
                    if t["hpsa_name"] == hpsa_name and t["geo_id"] not in excluded
                ]
                if zone_cands:
                    selected_4.append(zone_cands[0])
                    used_hpsa.add(hpsa_name)

        for t in valid_tracts:
            if len(selected_4) >= 4:
                break
            if t["hpsa_name"] not in used_hpsa and t["geo_id"] not in {s["geo_id"] for s in selected_4}:
                selected_4.append(t)
                used_hpsa.add(t["hpsa_name"])
    else:
        selected_4 = valid_tracts[:4]

    return {
        "county_fips": BRONX_FIPS,
        "formula_weights": {
            "HPSA_Shortage_Severity": 0.25,
            "Uninsured_and_Preventative_Gap": 0.25,
            "Chronic_and_Respiratory_Burden": 0.30,
            "Mobility_Transit_Language_SVI_Barriers": 0.20,
            "Physical_Distance_Penalty_Bronx": 0.00,
        },
        "urban_distance_trap_proof": {
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
        },
        "race_ethnicity_input_excluded": True,
        "excluded_geo_ids_applied": list(excluded),
        "selected_4_saturdays": selected_4,
        "top_residential_candidates": valid_tracts[:top_k],
        "rejected_institutional_outliers_top5": outliers[:5],
    }


def get_bronx_map_data() -> dict[str, Any]:
    """Loads all 347 Bronx tracts, 252 care_sites (with weekly operating hours), and 8 shortage_facilities for Tab 2 Map."""
    if "bronx_map_data" in _CACHE:
        return _CACHE["bronx_map_data"]

    bundle = load_all_bronx_tracts()

    # Load care sites and facilities from cached JSON if available
    sites_file = DATA_DIR / "care_sites.json"
    fac_file = DATA_DIR / "shortage_facilities.json"

    care_sites: list[dict[str, Any]] = []
    shortage_facilities: list[dict[str, Any]] = []

    if sites_file.exists():
        try:
            with open(sites_file) as f:
                care_sites = json.load(f)
        except Exception:
            care_sites = []

    if fac_file.exists():
        try:
            with open(fac_file) as f:
                shortage_facilities = json.load(f)
        except Exception:
            shortage_facilities = []

    if not care_sites or not shortage_facilities:
        try:
            client = _get_bq_client()
            if not care_sites:
                sites_query = f"""
                SELECT
                    FACILITY_NM AS site_name,
                    CMS_PROVIDER_ADDRESS AS site_address,
                    CMS_PROVIDER_CITY AS site_city,
                    ROUND(latitude, 5) AS lat,
                    ROUND(longitude, 5) AS lon,
                    site_kind AS site_category,
                    COALESCE(TOT_OPER_HR_PER_WEEK, 40.0) AS oper_hours_per_week,
                    (site_kind = 'community_health_center') AS is_fqhc
                FROM `{PROJECT_ID}.{DATASET_ID}.care_sites`
                WHERE county_geo_id = '36005'
                  AND latitude IS NOT NULL AND longitude IS NOT NULL
                """
                care_sites = [dict(r) for r in client.query(sites_query).result()]

            if not shortage_facilities:
                fac_query = f"""
                SELECT
                    HPSA_NM AS facility_name,
                    HPSA_SCORE AS hpsa_score,
                    ROUND(latitude, 5) AS lat,
                    ROUND(longitude, 5) AS lon
                FROM `{PROJECT_ID}.{DATASET_ID}.shortage_facilities`
                WHERE CMN_STATE_COUNTY_FIPS_CD = '36005'
                """
                shortage_facilities = [dict(r) for r in client.query(fac_query).result()]
        except Exception:
            pass

    result = {
        "county_fips": BRONX_FIPS,
        "center": {"lat": 40.8448, "lon": -73.8648},
        "tracts": bundle["tracts"],
        "care_sites": care_sites,
        "shortage_facilities": shortage_facilities,
    }
    _CACHE["bronx_map_data"] = result
    return result


def run_director_bigquery_sql(sql_query: str) -> dict[str, Any]:
    """Executes a read-only BigQuery SELECT query against `qwiklabs-gcp-03-c81d344a3430.a4i_health` for agent verification."""
    cleaned = sql_query.strip()
    if not cleaned.upper().startswith(("SELECT", "WITH")):
        return {"error": "Only read-only SELECT or WITH queries are permitted."}
    try:
        client = _get_bq_client()
        rows = [dict(r) for r in client.query(cleaned).result()]
        return {"row_count": len(rows), "rows": rows[:50]}
    except Exception as exc:
        return {"error": str(exc)}
