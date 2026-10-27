"""FastAPI service for the Bronx Mobile Care Broker."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List

from fastapi import Depends, FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from agent.agent import run_broker
from db.database import get_db, init_db, engine
from db.models import Schedule
from db.repository import (
    get_all_schedules,
    get_audit_logs,
    get_current_schedule,
    get_schedule_by_id,
    record_admin_action,
    replan_schedule_stop,
    save_schedule_run,
)
from api.copilot import answer_copilot_query
from api.schemas import (
    AdminActionRequest,
    AdminActionResponse,
    AuditLogResponse,
    ChatRequest,
    ChatResponse,
    GenerateScheduleRequest,
    ReplanStopRequest,
    ScheduleResponse,
    ScheduleSummaryResponse,
)

logger = logging.getLogger("broker.api")
logging.basicConfig(level=logging.INFO)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database on startup...")
    init_db()
    yield
    logger.info("Shutting down Bronx Mobile Care Broker API...")


app = FastAPI(
    title="Bronx Dynamic Public Health Equity & Preventative Mobile Care Broker",
    description="Google ADK multi-agent broker for siting mobile healthcare vans in Bronx County, NY.",
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

# Mount static assets
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "Bronx Mobile Care Broker API",
        "database_driver": engine.url.drivername,
        "county": "Bronx County, NY (36005)",
    }


@app.get("/api/schedules", response_model=List[ScheduleSummaryResponse])
def list_schedules(db: Session = Depends(get_db)):
    """Retrieve all deployment schedules (past and present) for the history switcher."""
    return get_all_schedules(db)


@app.get("/api/schedule/current", response_model=ScheduleResponse)
@app.get("/api/schedule/latest", response_model=ScheduleResponse)
def get_current(db: Session = Depends(get_db)):
    """Retrieve the active 4-Saturday deployment schedule."""
    schedule = get_current_schedule(db)
    if not schedule:
        # If no schedule exists yet, return 404 or prompt generation
        raise HTTPException(status_code=404, detail="No schedule generated yet. Call POST /api/schedule/generate.")
    return schedule


@app.get("/api/schedule/{schedule_id}", response_model=ScheduleResponse)
def get_schedule(schedule_id: str, db: Session = Depends(get_db)):
    """Retrieve a specific schedule by ID."""
    schedule = get_schedule_by_id(db, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail=f"Schedule {schedule_id} not found.")
    return schedule


@app.post("/api/schedule/generate", response_model=ScheduleResponse)
async def generate_schedule(req: GenerateScheduleRequest, db: Session = Depends(get_db)):
    """Trigger the Google ADK multi-agent broker to generate and audit a 4-Saturday schedule."""
    prompt = (
        req.user_prompt
        or f"Generate the complete 4-Saturday mobile clinic deployment plan for {req.target_month} in Bronx County, NY (36005). "
        "Enforce HPSA diversity across 4 distinct zones, race-blind composite scoring, institutional outlier checks, "
        "and produce community flyers and the executive briefing."
    )
    logger.info(f"Triggering ADK pipeline for {req.target_month}...")

    try:
        broker_res = await run_broker(prompt)
        if isinstance(broker_res, tuple) and len(broker_res) == 2:
            final_state, events = broker_res
        else:
            final_state = broker_res.get("session_state", broker_res)
            events = broker_res.get("events", [])
    except Exception as e:
        logger.error(f"Error running ADK multi-agent pipeline: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"ADK Agent execution failed: {str(e)}")

    proposed_schedule = final_state.get("proposed_schedule", {})
    audit_verdict = final_state.get("audit_verdict", {})
    outreach_flyers = final_state.get("outreach_flyers", "")
    director_briefing = final_state.get("director_briefing", "")

    schedule = save_schedule_run(
        db=db,
        proposed_schedule_data=proposed_schedule,
        audit_verdict_data=audit_verdict,
        outreach_flyers_text=outreach_flyers,
        director_briefing_text=director_briefing,
        target_month=req.target_month,
    )
    return schedule


@app.post("/api/admin/action", response_model=AdminActionResponse)
def admin_action(req: AdminActionRequest, db: Session = Depends(get_db)):
    """Human-in-the-Loop decision: approve or deny a schedule stop."""
    try:
        action = record_admin_action(
            db=db,
            schedule_id=req.schedule_id,
            action_type=req.action_type,
            rejection_reason=req.rejection_reason,
            rejection_category=req.rejection_category,
            stop_id=req.stop_id,
            admin_user=req.admin_user,
        )
        schedule = get_schedule_by_id(db, req.schedule_id)
        return AdminActionResponse(
            id=action.id,
            schedule_id=action.schedule_id,
            action_type=action.action_type,
            rejection_category=action.rejection_category,
            rejection_reason=action.rejection_reason,
            admin_user=action.admin_user,
            schedule_status=schedule.status if schedule else "UNKNOWN",
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/schedule/{schedule_id}/replan-stop/{stop_id}", response_model=ScheduleResponse)
def replan_stop(
    schedule_id: str,
    stop_id: str,
    req: ReplanStopRequest,
    db: Session = Depends(get_db),
):
    """Human-in-the-Loop decision: Relocate a single Saturday stop due to street conditions."""
    try:
        updated_schedule = replan_schedule_stop(
            db=db,
            schedule_id=schedule_id,
            stop_id=stop_id,
            rejection_category=req.rejection_category,
            rejection_reason=req.rejection_reason,
            admin_user=req.admin_user,
        )
        return updated_schedule
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/chat", response_model=ChatResponse)
def chat_copilot(req: ChatRequest, db: Session = Depends(get_db)):
    """AI Care Copilot: conversational clinical and operational questions grounded in the active deployment."""
    schedule = None
    if req.schedule_id:
        schedule = get_schedule_by_id(db, req.schedule_id)
    if not schedule:
        schedule = get_current_schedule(db)

    result = answer_copilot_query(query=req.query, schedule=schedule)
    return ChatResponse(
        reply=result["reply"],
        schedule_id=result.get("schedule_id"),
        citations=result.get("citations", []),
    )


@app.get("/api/audit/logs", response_model=List[AuditLogResponse])
def fetch_audit_logs(schedule_id: str = None, db: Session = Depends(get_db)):
    """Retrieve audit trail and trap detections."""
    logs = get_audit_logs(db, schedule_id)
    return logs


@app.get("/api/geo/data")
def get_geo_data():
    """Return Bronx census tract metadata, care sites, and outlier pins for the map."""
    tracts_file = DATA_DIR / "planner_tracts.json"
    clinics_file = DATA_DIR / "care_sites.json"

    tracts = []
    if tracts_file.exists():
        with open(tracts_file, "r") as f:
            tracts = json.load(f)

    clinics = []
    if clinics_file.exists():
        with open(clinics_file, "r") as f:
            clinics = json.load(f)

    # Highlight institutional outliers (Trap 2)
    outliers = [
        {
            "geo_id": "36005000100",
            "name": "Rikers Island (Correctional Facility)",
            "lat": 40.7915,
            "lon": -73.8837,
            "pct_group_quarters": 83.2,
            "rejection_reason": "Trap 2: Institutional Group Quarters outlier. Secure correctional island with zero unescorted residential public access.",
        },
        {
            "geo_id": "36005028400",
            "name": "Bronx Psychiatric Center / Institutional Campus",
            "lat": 40.8512,
            "lon": -73.8423,
            "pct_group_quarters": 39.8,
            "rejection_reason": "Trap 2: Institutional Inpatient Campus. Group quarters skew census health metrics; not a walkable residential neighborhood.",
        },
    ]

    return {
        "county": "Bronx County, NY",
        "fips": "36005",
        "total_tracts": len(tracts),
        "total_care_sites": len(clinics),
        "tracts": tracts,
        "care_sites": clinics,
        "institutional_outliers": outliers,
    }


@app.get("/")
def serve_index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {
        "message": "Bronx Dynamic Public Health Equity & Preventative Mobile Care Broker API is running.",
        "docs_url": "/docs",
        "current_schedule_url": "/api/schedule/current",
    }
