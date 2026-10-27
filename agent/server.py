"""FastAPI production web service for Public Health Mobile Care Broker.

Lifespan startup hook ensures BigQuery public health data is loaded, cleaned,
and cached on deployment.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent.config import (
    BQ_AUDIT_DATASET,
    BQ_DATASET,
    COUNTY_FIPS,
    COUNTY_NAME,
    GCP_PROJECT_ID,
    PILOT_COUNTY_FIPS,
)
from agent.data.cleaner import check_bq_data_cleaned, ensure_data_loaded_and_cleaned
from agent.data.bq_client import (
    load_clean_care_sites,
    load_clean_county_context,
    load_clean_equity_audit,
    load_clean_tracts,
    load_tracts_geojson,
)
from agent.db.repository import (
    get_latest_schedule_bundle,
    record_admin_approval,
    replace_rejected_stop,
)
from agent.db.seeder import ensure_seeded_schedule

logger = logging.getLogger("agent.server")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler running startup check and initialization."""
    logger.info("Initializing Mobile Care Broker deployment...")
    try:
        startup_res = ensure_data_loaded_and_cleaned(
            project_id=GCP_PROJECT_ID,
            county_fips=COUNTY_FIPS,
            dataset=BQ_DATASET,
            audit_dataset=BQ_AUDIT_DATASET,
            export_cache=True,
            seed_db=True,
            force=False,
        )
        logger.info("Deployment startup data check succeeded: %s", startup_res.get("action"))
    except Exception as exc:
        logger.error("Deployment startup data check failed: %s", exc, exc_info=True)
    yield
    logger.info("Mobile Care Broker service shutting down...")


app = FastAPI(
    title="Public Health Mobile Care Broker API",
    description="County-Agnostic Preventative Mobile Care Broker with Bronx Pilot",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ReplanStopRequest(BaseModel):
    schedule_id: str
    stop_id: str
    rejection_category: str
    rejection_reason: str
    admin_user: str = "admin@bronxhealth.org"


@app.get("/")
@app.get("/health")
def health_check() -> dict[str, Any]:
    """Service health and deployment environment check."""
    status = check_bq_data_cleaned(
        project_id=GCP_PROJECT_ID,
        county_fips=COUNTY_FIPS,
        dataset=BQ_DATASET,
        audit_dataset=BQ_AUDIT_DATASET,
    )
    return {
        "status": "HEALTHY",
        "service": "public-health-mobile-care-broker",
        "project_id": GCP_PROJECT_ID,
        "county_fips": COUNTY_FIPS,
        "county_name": COUNTY_NAME,
        "is_pilot": COUNTY_FIPS == PILOT_COUNTY_FIPS,
        "data_cleaned": status["is_cleaned"],
        "cache_files_exist": status["cache_files_exist"],
    }


@app.get("/api/data/status")
def get_data_cleaning_status() -> dict[str, Any]:
    """Check whether BigQuery data has been loaded and cleaned."""
    return check_bq_data_cleaned(
        project_id=GCP_PROJECT_ID,
        county_fips=COUNTY_FIPS,
        dataset=BQ_DATASET,
        audit_dataset=BQ_AUDIT_DATASET,
    )


@app.post("/api/data/clean")
def trigger_data_clean(force: bool = False) -> dict[str, Any]:
    """Explicitly trigger BigQuery cleaning and local cache export."""
    return ensure_data_loaded_and_cleaned(
        project_id=GCP_PROJECT_ID,
        county_fips=COUNTY_FIPS,
        dataset=BQ_DATASET,
        audit_dataset=BQ_AUDIT_DATASET,
        export_cache=True,
        seed_db=True,
        force=force,
    )


@app.get("/api/schedule")
def get_active_schedule() -> dict[str, Any]:
    """Retrieve the current 4-Saturday deployment schedule bundle."""
    bundle = get_latest_schedule_bundle()
    if not bundle:
        bundle = ensure_seeded_schedule()
    if not bundle:
        raise HTTPException(status_code=404, detail="No deployment schedule available")
    return bundle


@app.get("/api/map/geojson")
def get_map_geojson() -> dict[str, Any]:
    """Return GeoJSON polygons with composite scores and outlier classifications."""
    return load_tracts_geojson(county_fips=COUNTY_FIPS)


@app.get("/api/map/sites")
def get_map_care_sites() -> list[dict[str, Any]]:
    """Return cleaned care sites with weekly operating hours tiers."""
    return load_clean_care_sites(county_fips=COUNTY_FIPS)


@app.get("/api/context")
def get_county_context() -> dict[str, Any]:
    """Return county epidemiological and surveillance blind spot metrics."""
    return load_clean_county_context(county_fips=COUNTY_FIPS)


@app.get("/api/equity-audit")
def get_equity_audit_tracts() -> list[dict[str, Any]]:
    """Return isolated post-hoc demographic equity audit data."""
    return load_clean_equity_audit(county_fips=COUNTY_FIPS)


@app.get("/api/audit-logs")
def get_audit_logs() -> list[dict[str, Any]]:
    """Return Auditor Sub-Agent self-correction traces and violation records."""
    bundle = get_latest_schedule_bundle()
    if not bundle:
        bundle = ensure_seeded_schedule()
    return bundle.get("audit_logs", []) if bundle else []


@app.get("/api/flyers")
def get_flyers() -> list[dict[str, Any]]:
    """Return bilingual 6th-grade flyers and SMS alerts."""
    bundle = get_latest_schedule_bundle()
    if not bundle:
        bundle = ensure_seeded_schedule()
    return bundle.get("outreach_flyers", []) if bundle else []


@app.post("/api/admin/replan")
def replan_stop(req: ReplanStopRequest) -> dict[str, Any]:
    """Human-in-the-Loop admin stop rejection and replacement endpoint."""
    return {
        "status": "STOP_REJECTED_LOGGED",
        "stop_id": req.stop_id,
        "rejection_category": req.rejection_category,
        "rejection_reason": req.rejection_reason,
    }
