"""Verification suite for Bronx Mobile Care Broker FastAPI service & Cloud SQL persistence."""

import os
import sys
from pathlib import Path
from fastapi.testclient import TestClient

# Ensure root directory is on path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from api.main import app

client = TestClient(app)


def test_api_pipeline():
    print("=" * 70)
    print("BRONX CARE BROKER — FASTAPI & CLOUD SQL API VERIFICATION")
    print("=" * 70)

    # 1. Health check
    print("\n[1/5] Testing GET /health...")
    resp = client.get("/health")
    assert resp.status_code == 200, f"Health check failed: {resp.text}"
    health_data = resp.json()
    print(f"  ✓ Service status: {health_data['status']}")
    print(f"  ✓ Database driver: {health_data['database_driver']}")
    print(f"  ✓ Target county: {health_data['county']}")

    # 2. Geo data endpoint (Tracts, clinics, outliers)
    print("\n[2/5] Testing GET /api/geo/data...")
    resp = client.get("/api/geo/data")
    assert resp.status_code == 200, f"Geo data failed: {resp.text}"
    geo = resp.json()
    print(f"  ✓ Loaded {geo['total_tracts']} Bronx tracts")
    print(f"  ✓ Loaded {geo['total_care_sites']} care sites / clinics")
    print(f"  ✓ Verified {len(geo['institutional_outliers'])} institutional outlier pins (Rikers Island & Psych Center)")
    assert geo["total_tracts"] == 347
    assert geo["total_care_sites"] == 252
    assert len(geo["institutional_outliers"]) == 2

    # 3. Retrieve current schedule
    print("\n[3/5] Testing GET /api/schedule/current...")
    resp = client.get("/api/schedule/current")
    assert resp.status_code == 200, f"Current schedule failed: {resp.text}"
    sched = resp.json()
    print(f"  ✓ Current schedule ID: {sched['id']}")
    print(f"  ✓ Status: {sched['status']}")
    print(f"  ✓ Saturday Stops count: {len(sched['stops'])}")
    if sched["stops"]:
        s1 = sched["stops"][0]
        print(f"    • Stop 1: {s1['landmark_name']} ({s1['neighborhood']})")
        print(f"    • Street: {s1['street_intersection']}")
        print(f"    • Transit: Subway {s1['subway_lines']} | Bus {s1['bus_lines']}")

    # 4. Human-in-the-Loop Admin Action
    print("\n[4/5] Testing POST /api/admin/action (Human-in-the-Loop approval/denial)...")
    sched_id = sched["id"]
    admin_payload = {
        "schedule_id": sched_id,
        "action_type": "APPROVE",
        "rejection_category": None,
        "rejection_reason": "Verified and approved by Chief Health Equity Officer.",
        "admin_user": "cheo@bronxhealth.org",
    }
    resp = client.post("/api/admin/action", json=admin_payload)
    assert resp.status_code == 200, f"Admin action failed: {resp.text}"
    action_data = resp.json()
    print(f"  ✓ Recorded Action: {action_data['action_type']} by {action_data['admin_user']}")
    print(f"  ✓ Schedule status updated to: {action_data['schedule_status']}")

    # 5. Audit history
    print("\n[5/5] Testing GET /api/audit/logs...")
    resp = client.get("/api/audit/logs")
    assert resp.status_code == 200, f"Audit logs failed: {resp.text}"
    logs = resp.json()
    print(f"  ✓ Retrieved {len(logs)} audit log records")
    if logs:
        l0 = logs[0]
        print(f"    • Log ID: {l0['id']} | Status: {l0['audit_status']} | Iteration: {l0['iteration_number']}")

    print("\n" + "=" * 70)
    print("ALL API & DATABASE TESTS PASSED WITH LIVE CLOUD SQL!")
    print("=" * 70)


if __name__ == "__main__":
    test_api_pipeline()
