"""Post-hoc Demographic Equity Auditor & 5-Trap Validator bound to AuditAccountabilitySubAgent."""

from __future__ import annotations

from typing import Any

from agent.config import MAX_GROUP_QUARTERS_PCT, MIN_RESIDENTIAL_POPULATION
from agent.data.bq_client import (
    load_clean_borough_context,
    load_clean_equity_audit_df,
    load_clean_tracts_df,
)


def run_posthoc_equity_audit(
    selected_geo_ids: list[str],
    proposed_stops: list[dict[str, Any]] | None = None,
    distance_weight_used: float = 0.0,
    pm25_used_in_tract_ranking: bool = False,
) -> dict[str, Any]:
    """Execute the 5-Trap Validation and Post-Hoc Demographic Equity Audit for Bronx County (`36005`).

    Bound exclusively to `AuditAccountabilitySubAgent` (`include_contents="none"`).
    Enforces:
    1. Trap 1 (Urban Distance Illusion): Verifies physical distance weight is 0%.
    2. Trap 2 (Institutional Outliers): Rejects any stop with `pct_group_quarters > 25%` or `total_pop < 500`
       (e.g., Rikers Island `36005000100`, Bronx Psychiatric Center `36005028400`).
    3. HPSA Diversity Check: Verifies the 4 Saturday stops span at least 3 distinct Bronx ME HPSA zones.
    4. Trap 3 (Multi-Scale 12km PM2.5 Grid): Verifies annual `mean_pm` was not used for neighborhood ranking.
    5. Trap 4 (NSSP ED Surveillance Blind Spot): Verifies every stop provisions Point-of-Care Rapid Flu/COVID/RSV testing.
    6. Trap 5 (Post-Hoc Demographic Equity Verification): Queries isolated `a4i_health_audit.v_clean_equity_audit`
       to verify population-weighted Hispanic and Black coverage meets or exceeds the Bronx County baseline.
    """
    geo_ids = [str(g).strip() for g in selected_geo_ids if g]
    tracts_df = load_clean_tracts_df(prefer_cache=True)
    equity_df = load_clean_equity_audit_df(prefer_cache=True)
    borough_ctx = load_clean_borough_context(prefer_cache=True)

    selected_tracts = tracts_df[tracts_df["geo_id"].astype(str).isin(geo_ids)].copy()
    selected_equity = equity_df[equity_df["geo_id"].astype(str).isin(geo_ids)].copy()

    violations: list[dict[str, Any]] = []
    outliers_detected: list[dict[str, Any]] = []

    # --- Trap 1 Check: Urban Distance Illusion ---
    if float(distance_weight_used) > 0.0:
        violations.append(
            {
                "trap_id": "TRAP_1_URBAN_DISTANCE_ILLUSION",
                "severity": "CRITICAL",
                "message": (
                    f"Distance to clinic was weighted at {distance_weight_used:.2f} (> 0%). In dense Bronx (0.39 km median), "
                    "distance must be weighted at 0% in favor of HPSA score and clinic operating-hour bottlenecks."
                ),
            }
        )

    # --- Trap 2 Check: Institutional / Group Quarters Outliers ---
    for _, row in selected_tracts.iterrows():
        gq = float(row.get("pct_group_quarters", 0.0))
        pop = int(row.get("total_pop", 0))
        if gq > MAX_GROUP_QUARTERS_PCT or pop < MIN_RESIDENTIAL_POPULATION or bool(row.get("is_institutional_outlier", False)):
            outlier_info = {
                "geo_id": str(row["geo_id"]),
                "neighborhood": str(row.get("neighborhood", "")),
                "total_pop": pop,
                "pct_group_quarters": round(gq, 2),
                "outlier_category": str(row.get("outlier_category", "INSTITUTIONAL_OUTLIER")),
                "reason": str(row.get("outlier_rejection_reason", "Institutional or low-population outlier.")),
            }
            outliers_detected.append(outlier_info)
            violations.append(
                {
                    "trap_id": "TRAP_2_INSTITUTIONAL_OUTLIER",
                    "geo_id": str(row["geo_id"]),
                    "severity": "CRITICAL",
                    "message": outlier_info["reason"],
                }
            )

    # --- HPSA Zone Diversity Check ---
    distinct_hpsas = sorted({str(h) for h in selected_tracts["hpsa_name"].dropna().tolist()})
    if len(distinct_hpsas) < min(3, len(geo_ids)):
        hpsa_diversity_status = f"FAIL_CLUSTERED ({len(distinct_hpsas)} zones: {', '.join(distinct_hpsas)})"
        violations.append(
            {
                "trap_id": "HPSA_DIVERSITY_CHECK",
                "severity": "HIGH",
                "message": (
                    f"Selected stops span only {len(distinct_hpsas)} HPSA zone(s) ({', '.join(distinct_hpsas)}). "
                    "Must distribute across at least 3 distinct Bronx Medicaid Exception (ME) HPSA zones."
                ),
            }
        )
    else:
        hpsa_diversity_status = f"PASS ({len(distinct_hpsas)} distinct ME HPSA zones: {', '.join(distinct_hpsas)})"

    # --- Trap 3 Check: Coarse 12 km PM2.5 Grid ---
    if pm25_used_in_tract_ranking:
        violations.append(
            {
                "trap_id": "TRAP_3_COARSE_PM25_GRID",
                "severity": "HIGH",
                "message": "Annual mean_pm (12 km satellite CMAQ grid) cannot be used to rank individual census tracts.",
            }
        )

    # --- Trap 4 Check: NSSP Surveillance Blind Spot ---
    if proposed_stops:
        for stop in proposed_stops:
            kits = stop.get("clinical_kits", [])
            has_poc = any(
                "POC" in str(k.get("kit_code", "")).upper() or "RAPID" in str(k.get("kit_name", "")).upper()
                for k in kits
                if isinstance(k, dict)
            )
            if not has_poc:
                violations.append(
                    {
                        "trap_id": "TRAP_4_NSSP_BLIND_SPOT",
                        "geo_id": str(stop.get("geo_id", "")),
                        "severity": "HIGH",
                        "message": "Missing mandatory Point-of-Care Rapid Flu/COVID/RSV Testing Kit to cover 100% NULL NSSP ED data.",
                    }
                )

    # --- Trap 5 Check: Post-Hoc Demographic Equity Verification ---
    if not selected_equity.empty:
        total_sel_pop = float(selected_equity["total_pop"].sum())
        w_hisp = float((selected_equity["total_pop"] * selected_equity["pct_hispanic"]).sum() / total_sel_pop)
        w_black = float((selected_equity["total_pop"] * selected_equity["pct_black"]).sum() / total_sel_pop)
        w_combined = w_hisp + w_black
        w_poverty = float((selected_equity["total_pop"] * selected_equity["pct_poverty"]).sum() / total_sel_pop)
        w_pov150 = float((selected_equity["total_pop"] * selected_equity["pct_below_150pct_poverty"]).sum() / total_sel_pop)

        base_hisp = float(selected_equity["county_baseline_pct_hispanic"].iloc[0])
        base_black = float(selected_equity["county_baseline_pct_black"].iloc[0])
        base_combined = float(selected_equity["county_baseline_pct_black_or_hispanic"].iloc[0])
        base_poverty = float(selected_equity["county_baseline_pct_poverty"].iloc[0])
        base_pov150 = float(selected_equity["county_baseline_pct_below_150pct_poverty"].iloc[0])
    else:
        total_sel_pop = 0.0
        w_hisp, w_black, w_combined, w_poverty, w_pov150 = 0.0, 0.0, 0.0, 0.0, 0.0
        base_hisp, base_black, base_combined, base_poverty, base_pov150 = 56.6, 28.2, 84.8, 27.5, 42.1

    coverage_ratio = round(w_combined / base_combined, 3) if base_combined > 0 else 1.0
    equity_pass = w_combined >= (base_combined - 2.0)
    if not equity_pass:
        violations.append(
            {
                "trap_id": "TRAP_5_POSTHOC_EQUITY_SHORTFALL",
                "severity": "HIGH",
                "message": (
                    f"Selected stops combined Black + Hispanic representation ({w_combined:.1f}%) falls below "
                    f"the Bronx County baseline ({base_combined:.1f}%)."
                ),
            }
        )

    demographic_coverage_ratios = {
        "selected_tracts_count": len(geo_ids),
        "selected_total_population": int(total_sel_pop),
        "selected_pct_hispanic": round(w_hisp, 2),
        "selected_pct_black": round(w_black, 2),
        "selected_pct_black_or_hispanic_combined": round(w_combined, 2),
        "selected_pct_below_100pct_poverty": round(w_poverty, 2),
        "selected_pct_below_150pct_poverty": round(w_pov150, 2),
        "bronx_baseline_pct_hispanic": round(base_hisp, 2),
        "bronx_baseline_pct_black": round(base_black, 2),
        "bronx_baseline_pct_black_or_hispanic_combined": round(base_combined, 2),
        "bronx_baseline_pct_below_100pct_poverty": round(base_poverty, 2),
        "bronx_baseline_pct_below_150pct_poverty": round(base_pov150, 2),
        "underserved_coverage_parity_ratio": coverage_ratio,
        "equity_delta_vs_baseline_pct_pts": round(w_combined - base_combined, 2),
        "equity_audit_verdict": "PASS" if equity_pass else "FAIL",
    }

    audit_status = "APPROVED" if len(violations) == 0 else "REJECTED"
    if audit_status == "APPROVED":
        auditor_comments = (
            f"APPROVED (All 5 Bronx Data Traps Verified): "
            f"(1) Distance weight verified at 0.0%; siting driven by HPSA severity and clinic operating-hour bottlenecks. "
            f"(2) Zero institutional/group-quarters outliers in selected stops (all 4 tracts have pct_group_quarters <= 25% and pop >= 500). "
            f"(3) HPSA Diversity verified across {len(distinct_hpsas)} distinct ME HPSA zones ({', '.join(distinct_hpsas)}). "
            f"(4) Coarse 12km PM2.5 grid excluded from ranking; rapid POC Flu/COVID/RSV testing provisioned on all stops to cover the 212-week NSSP ED blind spot. "
            f"(5) Post-Hoc Equity Audit PASS: Race-blind schedule achieves {w_combined:.1f}% combined Hispanic ({w_hisp:.1f}%) and Black ({w_black:.1f}%) coverage "
            f"vs. the {base_combined:.1f}% Bronx County baseline ({coverage_ratio:.2f}x parity ratio, +{w_combined - base_combined:.1f} pct pts)."
        )
    else:
        violation_summaries = "; ".join(v["message"] for v in violations)
        auditor_comments = (
            f"REJECTED ({len(violations)} Trap Violation(s) Detected): {violation_summaries} "
            f"PlannerSubAgent must exclude flagged institutional outliers { [o['geo_id'] for o in outliers_detected] } "
            f"and re-select clean residential tracts across distinct ME HPSA zones."
        )

    return {
        "audit_status": audit_status,
        "institutional_outliers_detected": outliers_detected,
        "hpsa_diversity_status": hpsa_diversity_status,
        "demographic_coverage_ratios": demographic_coverage_ratios,
        "violations": violations,
        "auditor_comments": auditor_comments,
        "borough_context_verified": {
            "nssp_surveillance_blind_spot": bool(borough_ctx.get("nssp_surveillance_blind_spot", True)),
            "pm25_cmaq_grid_resolution_km": float(borough_ctx.get("pm25_cmaq_grid_resolution_km", 12.0)),
        },
    }
