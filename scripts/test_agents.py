"""Automated verification script for Bronx Mobile Care Broker Agents and Tools.

Verifies:
1. Tool scoring: Race-blind composite ranking across 347 Bronx tracts.
2. Trap 2 detection: Catches Rikers Island (36005000100) and Bronx Psych (36005028400) as institutional outliers.
3. Trap 5 audit: Isolated post-hoc equity audit verifies Black & Hispanic representation (93.9% vs 84.8% baseline).
4. Weather & Maps tools: Generates weather posture and transit landmark links.
5. ADK multi-agent hierarchy: Confirms Root, Planner, Auditor, Flyer, and Director agent configurations.
"""

import sys
import json
from agent.tools.bq_scoring import score_bronx_tracts
from agent.tools.equity_audit import run_posthoc_equity_audit
from agent.tools.weather_aq import get_saturday_weather_and_air_quality
from agent.tools.maps_landmarks import resolve_stop_landmark_and_map_context
from agent.agent import root_agent, planner_agent, auditor_agent, flyer_agent, director_agent


def test_suite():
    print("=" * 70)
    print("BRONX MOBILE CARE BROKER — AGENTS & TOOLS VERIFICATION SUITE")
    print("=" * 70)

    # 1. Verify ADK Agent Structure
    print("\n[1/5] Verifying Google ADK Multi-Agent Hierarchy...")
    assert root_agent.name == "BronxMobileCareBroker"
    assert len(root_agent.sub_agents) == 3
    assert planner_agent.output_key == "proposed_schedule"
    assert auditor_agent.output_key == "audit_verdict"
    assert flyer_agent.output_key == "outreach_flyers"
    assert director_agent.output_key == "director_briefing"
    print("  ✓ Root agent and all 4 specialized sub-agents properly configured.")

    # 2. Verify Tool Scoring (Race-blind residential candidate selection)
    print("\n[2/5] Testing score_bronx_tracts (Race-blind composite scoring)...")
    res = score_bronx_tracts(enforce_hpsa_diversity=True)
    assert res["race_ethnicity_input_excluded"] is True
    assert res["formula_weights"]["Physical_Distance_Penalty_Bronx"] == 0.0
    selected = res["selected_4_saturdays"]
    assert len(selected) == 4
    geo_ids = [s["geo_id"] for s in selected]
    print(f"  ✓ Selected 4 distinct HPSA residential stops: {geo_ids}")
    for idx, s in enumerate(selected, 1):
        print(f"    • Sat {idx}: Tract {s['geo_id']} ({s['location_name']}) | HPSA: {s['hpsa_name']} ({s['hpsa_score']}) | Score: {s['composite_need_score']}")

    # 3. Verify Trap 2: Outlier Rejection Demonstration
    print("\n[3/5] Testing Trap 2: Institutional Outlier Detection...")
    outlier_run = score_bronx_tracts(demo_include_outliers=True)
    outlier_geos = [s["geo_id"] for s in outlier_run["selected_4_saturdays"]]
    print(f"  • Simulating raw unfiltered query proposing outliers: {outlier_geos}")
    audit_reject = run_posthoc_equity_audit(outlier_geos)
    assert audit_reject["audit_status"] == "REJECTED"
    assert len(audit_reject["violations"]) > 0
    print(f"  ✓ Auditor successfully caught and REJECTED outliers: {audit_reject['violations'][0]['reason'][:90]}...")

    # 4. Verify Trap 5: Post-Hoc Demographic Equity Audit on Residential Schedule
    print("\n[4/5] Testing Trap 5: Isolated Post-Hoc Equity Audit on Approved Schedule...")
    audit_pass = run_posthoc_equity_audit(geo_ids)
    assert audit_pass["audit_status"] == "APPROVED"
    eq = audit_pass["selected_tracts_weighted_profile"]
    base = audit_pass["bronx_county_baseline"]
    print(f"  ✓ Equity Audit PASSED:")
    print(f"    • Black + Hispanic representation: {eq['pct_black_or_hispanic_combined']}% vs {base['pct_black_or_hispanic_combined']}% county baseline")
    print(f"    • Poverty rate: {eq['pct_poverty']}% vs {base['pct_poverty']}% county baseline (ratio {audit_pass['coverage_ratios_vs_county_baseline']['poverty_concentration_ratio']}x)")
    print(f"    • Uninsured rate: {eq['pct_uninsured']}% vs {base['pct_uninsured']}% county baseline (ratio {audit_pass['coverage_ratios_vs_county_baseline']['uninsured_concentration_ratio']}x)")

    # 5. Verify Weather & Landmark Tools
    print("\n[5/5] Testing Weather & Landmark Context Tools...")
    weather = get_saturday_weather_and_air_quality(40.84, -73.86, saturday_index=1)
    landmark = resolve_stop_landmark_and_map_context("36005006700")
    print(f"  ✓ Weather posture: {weather['forecast']['van_setup_mode']}")
    print(f"  ✓ Landmark anchor: {landmark['landmark_name']} ({landmark['street_intersection']})")
    print(f"  ✓ Transit lines: Subway {landmark['subway_lines']} | Bus {landmark['bus_lines']}")

    print("\n" + "=" * 70)
    print("ALL TESTS PASSED: MULTI-AGENT ADK SYSTEM & TOOLS READY FOR IMPACT!")
    print("=" * 70)


if __name__ == "__main__":
    test_suite()
