"""Isolated Post-Hoc Demographic Equity & Multi-Scale Guardrail Auditor Tool.

IMPORTANT ETHICAL & ARCHITECTURAL SEPARATION:
- Race and ethnicity (`pct_hispanic`, `pct_black`, `pct_asian`, `pct_white`) are strictly excluded
  from `score_bronx_tracts` (SVI Theme 3 exclusion).
- Only this isolated auditor tool queries `pct_race_*` columns AFTER candidate tracts have been proposed,
  verifying that the race-blind composite score produces an equitable outcome for underserved Bronx communities
  and catches institutional group-quarters outliers (`pct_group_quarters > 25%` or `total_pop < 500`).
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
AUDIT_DATASET_ID = os.environ.get("A4I_AUDIT_DATASET", "a4i_health_audit")
_ROOT_DATA = Path(__file__).resolve().parent.parent.parent / "data"
_PKG_DATA = Path(__file__).resolve().parent.parent / "data"
DATA_DIR = _ROOT_DATA if _ROOT_DATA.exists() else _PKG_DATA

_DEMO_CACHE: dict[str, dict[str, Any]] | None = None


def _get_bq_client() -> bigquery.Client:
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


def _load_bronx_demographics() -> dict[str, dict[str, Any]]:
    global _DEMO_CACHE
    if _DEMO_CACHE is not None:
        return _DEMO_CACHE

    demo_map: dict[str, dict[str, Any]] = {}

    # Priority 1: Load from local snapshots if available
    audit_file = DATA_DIR / "equity_audit.json"
    planner_file = DATA_DIR / "planner_tracts.json"
    hpsa_file = DATA_DIR / "hpsa_tracts.json"

    if audit_file.exists() and planner_file.exists():
        try:
            with open(audit_file) as f:
                audit_list = json.load(f)
            with open(planner_file) as f:
                planner_list = json.load(f)
            hpsa_list = []
            if hpsa_file.exists():
                with open(hpsa_file) as f:
                    hpsa_list = json.load(f)

            pt_map = {str(r["geo_id"]): r for r in planner_list}
            h_map = {str(r["geo_id"]): r for r in hpsa_list}

            for a in audit_list:
                gid = str(a["geo_id"])
                p = pt_map.get(gid, {})
                h = h_map.get(gid, {})

                demo_map[gid] = {
                    "geo_id": gid,
                    "location_name": f"Census Tract {gid[-6:]}, Bronx County, NY",
                    "total_pop": int(p.get("total_pop") or a.get("audit_total_pop") or 0),
                    "pct_hispanic": float(a.get("pct_hispanic") or 0.0),
                    "pct_black": float(a.get("pct_black_nonhisp") or 0.0),
                    "pct_asian": float(a.get("pct_asian_nonhisp") or 0.0),
                    "pct_white": float(a.get("pct_white_nonhisp_est") or 0.0),
                    "pct_poverty": float(a.get("pct_below_150pct_poverty") or 0.0),
                    "pct_uninsured": float(p.get("pct_uninsured") or 0.0),
                    "pct_group_quarters": float(p.get("pct_group_quarters") or 0.0),
                    "pct_no_vehicle": float(p["pct_no_vehicle"]) if p.get("pct_no_vehicle") is not None else None,
                    "hpsa_name": h.get("hpsa_name") or "Non-HPSA Tract",
                    "hpsa_score": float(h.get("hpsa_score") or p.get("primary_care_hpsa_score") or 0.0),
                }
            _DEMO_CACHE = demo_map
            return _DEMO_CACHE
        except Exception:
            demo_map = {}

    # Priority 2: Query BigQuery live
    client = _get_bq_client()
    query = f"""
    SELECT
        b.geo_id,
        b.pct_hispanic,
        b.pct_black_nonhisp AS pct_black,
        b.pct_asian_nonhisp AS pct_asian,
        b.pct_white_nonhisp_est AS pct_white,
        b.pct_below_150pct_poverty AS pct_poverty,
        p.total_pop,
        p.pct_uninsured,
        p.pct_group_quarters,
        p.pct_no_vehicle,
        p.primary_care_hpsa_score AS hpsa_score
    FROM `{PROJECT_ID}.{AUDIT_DATASET_ID}.v_bronx_equity_baseline` b
    LEFT JOIN `{PROJECT_ID}.{DATASET_ID}.planner_tract_features` p ON b.geo_id = p.geo_id
    """
    for row in client.query(query).result():
        d = dict(row)
        gid = str(d["geo_id"])
        demo_map[gid] = {
            "geo_id": gid,
            "location_name": f"Census Tract {gid[-6:]}, Bronx County, NY",
            "total_pop": int(d.get("total_pop") or 0),
            "pct_hispanic": float(d.get("pct_hispanic") or 0.0),
            "pct_black": float(d.get("pct_black") or 0.0),
            "pct_asian": float(d.get("pct_asian") or 0.0),
            "pct_white": float(d.get("pct_white") or 0.0),
            "pct_poverty": float(d.get("pct_poverty") or 0.0),
            "pct_uninsured": float(d.get("pct_uninsured") or 0.0),
            "pct_group_quarters": float(d.get("pct_group_quarters") or 0.0),
            "pct_no_vehicle": float(d["pct_no_vehicle"]) if d.get("pct_no_vehicle") is not None else None,
            "hpsa_name": "Bronx ME HPSA",
            "hpsa_score": float(d.get("hpsa_score") or 0.0),
        }

    _DEMO_CACHE = demo_map
    return _DEMO_CACHE


def run_posthoc_equity_audit(selected_geo_ids: list[str]) -> dict[str, Any]:
    """Audits a proposed 4-Saturday Bronx tract list for institutional outliers, HPSA diversity, and demographic equity.

    Args:
        selected_geo_ids: List of 4 proposed 11-character census tract GEOIDs (e.g. ['36005006700', ...]).
    """
    demo_map = _load_bronx_demographics()
    all_rows = list(demo_map.values())

    # Compute population-weighted Bronx County baseline across all residential tracts
    residential_baseline_rows = [r for r in all_rows if int(r.get("total_pop") or 0) >= 500]
    county_pop = sum(int(r.get("total_pop") or 0) for r in residential_baseline_rows) or 1

    def _weighted_avg(rows: list[dict[str, Any]], field: str) -> float:
        total_w = sum(int(r.get("total_pop") or 0) for r in rows if r.get(field) is not None)
        if total_w <= 0:
            return 0.0
        num = sum(float(r[field]) * int(r.get("total_pop") or 0) for r in rows if r.get(field) is not None)
        return round(num / total_w, 1)

    baseline = {
        "county_total_pop": county_pop,
        "pct_hispanic": _weighted_avg(residential_baseline_rows, "pct_hispanic"),
        "pct_black": _weighted_avg(residential_baseline_rows, "pct_black"),
        "pct_black_or_hispanic_combined": round(
            _weighted_avg(residential_baseline_rows, "pct_hispanic") + _weighted_avg(residential_baseline_rows, "pct_black"), 1
        ),
        "pct_asian": _weighted_avg(residential_baseline_rows, "pct_asian"),
        "pct_white": _weighted_avg(residential_baseline_rows, "pct_white"),
        "pct_poverty": _weighted_avg(residential_baseline_rows, "pct_poverty"),
        "pct_uninsured": _weighted_avg(residential_baseline_rows, "pct_uninsured"),
    }

    selected_rows = [demo_map[g] for g in selected_geo_ids if g in demo_map]
    violations: list[dict[str, Any]] = []

    # Check 1: Institutional / Group-Quarters Outlier Check (Trap 2)
    for r in selected_rows:
        gq = float(r.get("pct_group_quarters") or 0.0)
        pop = int(r.get("total_pop") or 0)
        if gq > 25.0 or pop < 500:
            facility_hint = (
                "Rikers Island Correctional Complex"
                if r["geo_id"] == "36005000100"
                else "Bronx Psychiatric Center / Institutional Facility"
                if r["geo_id"] == "36005028400"
                else "Institutional Group Quarters Tract"
            )
            violations.append({
                "rule": "INSTITUTIONAL_GROUP_QUARTERS_OUTLIER",
                "geo_id": r["geo_id"],
                "severity": "CRITICAL_REJECT",
                "reason": (
                    f"Tract {r['geo_id']} ({facility_hint}) has pct_group_quarters={gq:.1f}% "
                    f"and total_pop={pop} (pct_no_vehicle={r.get('pct_no_vehicle')}). "
                    "A community mobile van cannot serve locked correctional or inpatient psychiatric facilities. "
                    "Must re-plan onto a residential tract (pct_group_quarters <= 25%, total_pop >= 500)."
                ),
            })

    # Check 2: HPSA Geographic Diversity Check
    hpsa_zones = [r.get("hpsa_name", "Unknown") for r in selected_rows]
    distinct_zones = set(hpsa_zones)
    if len(selected_rows) >= 4 and len(distinct_zones) < 3:
        violations.append({
            "rule": "HPSA_GEOGRAPHIC_CLUSTERING",
            "geo_id": ",".join(selected_geo_ids),
            "severity": "CRITICAL_REJECT",
            "reason": (
                f"Proposed schedule clusters 4 Saturdays into only {len(distinct_zones)} HPSA zone(s): "
                f"{sorted(distinct_zones)}. Must span at least 3-4 distinct Bronx ME HPSA zones."
            ),
        })

    # Check 3: Post-Hoc Racial/Ethnic & Poverty Distributional Equity Check (Trap 5)
    selected_pop = sum(int(r.get("total_pop") or 0) for r in selected_rows)
    selected_metrics = {
        "selected_total_pop": selected_pop,
        "pct_hispanic": _weighted_avg(selected_rows, "pct_hispanic"),
        "pct_black": _weighted_avg(selected_rows, "pct_black"),
        "pct_black_or_hispanic_combined": round(
            _weighted_avg(selected_rows, "pct_hispanic") + _weighted_avg(selected_rows, "pct_black"), 1
        ),
        "pct_asian": _weighted_avg(selected_rows, "pct_asian"),
        "pct_white": _weighted_avg(selected_rows, "pct_white"),
        "pct_poverty": _weighted_avg(selected_rows, "pct_poverty"),
        "pct_uninsured": _weighted_avg(selected_rows, "pct_uninsured"),
    }

    if selected_rows and selected_metrics["pct_black_or_hispanic_combined"] < 0.85 * baseline["pct_black_or_hispanic_combined"]:
        violations.append({
            "rule": "POSTHOC_DEMOGRAPHIC_EQUITY_UNDERSERVED",
            "geo_id": ",".join(selected_geo_ids),
            "severity": "CRITICAL_REJECT",
            "reason": (
                f"Selected tracts under-serve historically underserved Black/Hispanic residents "
                f"({selected_metrics['pct_black_or_hispanic_combined']}% vs {baseline['pct_black_or_hispanic_combined']}% county baseline)."
            ),
        })

    status = "REJECTED" if violations else "APPROVED"
    return {
        "audit_status": status,
        "race_used_in_ranking_input": False,
        "race_verified_in_posthoc_audit": True,
        "selected_geo_ids": selected_geo_ids,
        "distinct_hpsa_zones": sorted(distinct_zones),
        "violations": violations,
        "bronx_county_baseline": baseline,
        "selected_tracts_weighted_profile": selected_metrics,
        "coverage_ratios_vs_county_baseline": {
            "hispanic_ratio": round(selected_metrics["pct_hispanic"] / max(baseline["pct_hispanic"], 1.0), 2),
            "black_or_hispanic_combined_ratio": round(
                selected_metrics["pct_black_or_hispanic_combined"] / max(baseline["pct_black_or_hispanic_combined"], 1.0), 2
            ),
            "poverty_concentration_ratio": round(selected_metrics["pct_poverty"] / max(baseline["pct_poverty"], 1.0), 2),
            "uninsured_concentration_ratio": round(selected_metrics["pct_uninsured"] / max(baseline["pct_uninsured"], 1.0), 2),
        },
        "tract_by_tract_demographics": selected_rows,
    }


def approve_and_exit_audit_loop(tool_context: Any, summary: str = "Schedule meets all equity, diversity, and outlier criteria.") -> dict[str, Any]:
    """Approves the schedule and breaks out of the Planner-Auditor self-correction loop in Google ADK.

    Args:
        tool_context: The ADK ToolContext injected by the runner.
        summary: Clear justification explaining why the schedule is approved.
    """
    if hasattr(tool_context, "state") and tool_context.state is not None:
        try:
            tool_context.state["audit_verdict"] = summary
        except Exception:
            pass
    if hasattr(tool_context, "actions") and tool_context.actions is not None:
        tool_context.actions.escalate = True
    return {
        "status": "APPROVED",
        "loop_escalated": True,
        "message": summary,
    }
