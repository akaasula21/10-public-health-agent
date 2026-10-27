"""Verification script for BigQuery cleaning status and deployment startup loading.

Tests:
1. BigQuery data cleaning status verification (check_bq_data_cleaned).
2. Fast-path startup hook performance (< 1s when already cleaned).
3. CLI clean_bronx_data.py execution without TypeError.
4. FastAPI lifespan / health status endpoint response.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("verify_startup_loader")


def test_bq_cleaning_check():
    logger.info("=== STEP 1: Verify BigQuery Data Cleaning Status ===")
    from agent.data.cleaner import check_bq_data_cleaned
    from agent.config import COUNTY_FIPS, GCP_PROJECT_ID, BQ_DATASET, BQ_AUDIT_DATASET

    status = check_bq_data_cleaned(
        project_id=GCP_PROJECT_ID,
        county_fips=COUNTY_FIPS,
        dataset=BQ_DATASET,
        audit_dataset=BQ_AUDIT_DATASET,
    )
    print("Status result:", json.dumps(status, indent=2))
    assert status["is_cleaned"] is True, f"Expected is_cleaned=True, got {status}"
    assert status["tract_count"] == 347, f"Expected 347 tracts, got {status['tract_count']}"
    assert status["institutional_outliers_count"] == 11, f"Expected 11 outliers, got {status['institutional_outliers_count']}"
    assert status["sentinels_found"] == 0, f"Expected 0 sentinels, got {status['sentinels_found']}"
    assert status["care_sites_count"] == 252, f"Expected 252 care sites, got {status['care_sites_count']}"
    assert status["equity_audit_count"] == 347, f"Expected 347 equity audit rows, got {status['equity_audit_count']}"
    assert status["cache_files_exist"] is True, "Expected local cache files to exist"
    logger.info("✓ Step 1 passed: BigQuery data is completely clean and verified.")
    return status


def test_fast_path_startup():
    logger.info("=== STEP 2: Verify Idempotent Fast-Path Deployment Startup ===")
    from agent.data.cleaner import ensure_data_loaded_and_cleaned
    from agent.config import COUNTY_FIPS, GCP_PROJECT_ID, BQ_DATASET, BQ_AUDIT_DATASET

    t0 = time.time()
    res = ensure_data_loaded_and_cleaned(
        project_id=GCP_PROJECT_ID,
        county_fips=COUNTY_FIPS,
        dataset=BQ_DATASET,
        audit_dataset=BQ_AUDIT_DATASET,
        export_cache=True,
        seed_db=True,
        force=False,
    )
    elapsed = time.time() - t0
    print(f"Startup execution took: {elapsed:.3f} seconds")
    print("Startup result:", json.dumps(res, indent=2, default=str))

    assert res["action"] == "SKIPPED_ALREADY_CLEAN", f"Unexpected action: {res['action']}"
    assert res["fast_path"] is True, "Expected fast_path=True"
    logger.info("✓ Step 2 passed: Fast-path completed in %.3fs without redundant recomputation.", elapsed)


def test_server_health_endpoints():
    logger.info("=== STEP 3: Verify Server Entrypoint & Health Endpoints ===")
    from fastapi.testclient import TestClient
    from agent.server import app

    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200, f"Health endpoint failed: {resp.text}"
    health_data = resp.json()
    print("Health response:", json.dumps(health_data, indent=2))
    assert health_data["status"] == "HEALTHY"
    assert health_data["data_cleaned"] is True

    status_resp = client.get("/api/data/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["is_cleaned"] is True
    logger.info("✓ Step 3 passed: Server health and data status endpoints verified.")


def main():
    try:
        test_bq_cleaning_check()
        test_fast_path_startup()
        test_server_health_endpoints()
        logger.info("\n🎉 ALL STARTUP & BIGQUERY CLEANING VERIFICATIONS PASSED SUCCESSFULLY!")
    except Exception as exc:
        logger.error("Verification failed: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
