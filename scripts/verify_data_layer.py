#!/usr/bin/env python3
"""End-to-end verification script for the Bronx Dataset Cleaner & Data Layer."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.data.cleaner import run_dataset_cleaner
from agent.db.repository import (
    get_latest_schedule_bundle,
    record_admin_approval,
    replace_rejected_stop,
)
from agent.db.seeder import build_bilingual_flyer_for_stop, ensure_seeded_schedule
from agent.tools.bq_scoring import get_bronx_map_data, query_director_sql, score_bronx_tracts


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print("1. Running Bronx Dataset Cleaner (BigQuery Views + Local Parquet/GeoJSON Cache)...")
    clean_summary = run_dataset_cleaner()
    assert clean_summary["total_populated_tracts"] == 347
    assert clean_summary["eligible_residential_tracts"] == 336
    assert clean_summary["institutional_outlier_tracts"] == 11
    assert clean_summary["care_sites_cleaned"] == 252
    assert clean_summary["geojson_polygons_exported"] == 347
    print("   [PASS] Cleaner verified:", json.dumps({k: v for k, v in clean_summary.items() if k != "borough_context"}))

    print("\n2. Seeding Database with Schedule, 4 Saturday Stops, Self-Correction Audit Logs & Bilingual Flyers...")
    bundle = ensure_seeded_schedule(target_month="November 2026", force_reseed=True)
    assert len(bundle["active_stops"]) == 4
    assert len(bundle["audit_logs"]) == 2
    assert bundle["audit_logs"][0]["audit_status"] == "REJECTED"
    assert bundle["audit_logs"][1]["audit_status"] == "APPROVED"
    assert len(bundle["outreach_flyers"]) == 4

    print("   [PASS] Audit Iteration 1:", bundle["audit_logs"][0]["audit_status"], "->", bundle["audit_logs"][0]["auditor_comments"][:140] + "...")
    print("   [PASS] Audit Iteration 2:", bundle["audit_logs"][1]["audit_status"], "->", bundle["audit_logs"][1]["auditor_comments"][:140] + "...")
    print("   [PASS] 4 Active Saturday Stops across distinct ME HPSA zones:")
    for s in bundle["active_stops"]:
        print(
            f"      Sat {s['saturday_index']} ({s['saturday_date']}): Tract {s['geo_id']} | "
            f"{s['hpsa_name']} (Score {s['hpsa_score']}) | {s['neighborhood']} @ {s['landmark_name']}"
        )

    print("\n3. Testing HITL Deny-with-Reason & Re-Plan Persistence (`replace_rejected_stop`)...")
    schedule_id = bundle["schedule"]["id"]
    sat1_stop = bundle["active_stops"][0]
    active_geo_ids = [s["geo_id"] for s in bundle["active_stops"]]
    replan_res = score_bronx_tracts(
        exclude_geo_ids=active_geo_ids,
        enforce_outlier_guardrail=True,
        enforce_hpsa_diversity=True,
        top_n=1,
    )
    replacement_candidate = replan_res["proposed_stops"][0]
    replacement_candidate["saturday_index"] = sat1_stop["saturday_index"]
    replacement_candidate["saturday_date"] = sat1_stop["saturday_date"]
    replacement_flyer = build_bilingual_flyer_for_stop(replacement_candidate)

    replaced = replace_rejected_stop(
        schedule_id=schedule_id,
        rejected_stop_id=sat1_stop["id"],
        rejection_category="ROAD_CONSTRUCTION",
        rejection_reason="ConEd utility trenching blocking curb access on Saturday 1",
        replacement_stop_payload=replacement_candidate,
        replacement_flyer_payload=replacement_flyer,
    )
    assert replaced["new_stop"]["geo_id"] != sat1_stop["geo_id"]
    approval = record_admin_approval(schedule_id=schedule_id, stop_id=replaced["new_stop"]["id"])
    assert approval["action_type"] == "APPROVE"
    updated_bundle = get_latest_schedule_bundle()
    assert updated_bundle is not None
    assert len(updated_bundle["active_stops"]) == 4
    assert len(updated_bundle["replaced_stops_history"]) == 1
    assert len(updated_bundle["admin_actions"]) >= 3
    print(
        f"   [PASS] Replaced Sat 1 Stop {sat1_stop['geo_id']} -> {replaced['new_stop']['geo_id']} "
        f"({replaced['new_stop']['neighborhood']}) and logged DENY, REPLAN, and APPROVE actions."
    )

    # Re-seed clean initial state so default schedule starts fresh with 4 baseline stops
    ensure_seeded_schedule(target_month="November 2026", force_reseed=True)

    print("\n4. Testing Tab 2 Map Data Payload (`get_bronx_map_data`)...")
    map_data = get_bronx_map_data()
    assert len(map_data["tract_geojson"]["features"]) == 347
    assert len(map_data["care_sites"]) == 252
    assert len(map_data["outlier_warning_pins"]) == 11
    assert len(map_data["active_stops"]) == 4
    print(
        f"   [PASS] Map payload ready: {len(map_data['tract_geojson']['features'])} polygons, "
        f"{len(map_data['care_sites'])} clinics, {len(map_data['outlier_warning_pins'])} Red Warning Pins, "
        f"{len(map_data['active_stops'])} active van stops."
    )

    print("\n5. Testing Tab 4 Director SQL Guardrail (`query_director_sql`)...")
    blocked = query_director_sql("DROP TABLE a4i_health.burden_tracts")
    assert blocked["status"] == "BLOCKED"
    valid_q = query_director_sql(
        "SELECT hpsa_name, hpsa_score, COUNT(*) AS tracts, ROUND(AVG(pct_uninsured), 1) AS avg_uninsured "
        "FROM `qwiklabs-gcp-03-c81d344a3430.a4i_health.v_clean_bronx_tracts` "
        "WHERE NOT is_institutional_outlier GROUP BY 1, 2 ORDER BY hpsa_score DESC"
    )
    assert valid_q["status"] == "SUCCESS"
    print("   [PASS] Director SQL guardrail blocked DDL and returned HPSA summary:", valid_q["rows"])
    print("\nALL DATASET CLEANER & DATA LAYER VERIFICATION CHECKS PASSED!")


if __name__ == "__main__":
    main()
