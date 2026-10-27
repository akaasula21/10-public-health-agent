"""GCP Cloud SQL (PostgreSQL) connection manager and CRUD repository layer.

Supports:
1. Explicit `DATABASE_URL` (e.g., `postgresql+psycopg2://...` or `postgresql+pg8000://...`).
2. Google Cloud SQL Python Connector (`CLOUD_SQL_CONNECTION_NAME` = `qwiklabs-gcp-03-c81d344a3430:us-central1:public-health-db`).
3. Direct Cloud SQL public IP (`CLOUD_SQL_HOST` = `136.71.50.206` when `CLOUD_SQL_PASSWORD` is provided).
4. Automatic, zero-config local SQLite fallback (`data/cache/public_health_broker.db`) when Cloud SQL credentials/network are unavailable.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import date, datetime, timezone
from functools import lru_cache
from typing import Any, Iterator

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from agent.config import (
    CLOUD_SQL_CONNECTION_NAME,
    CLOUD_SQL_DB_NAME,
    CLOUD_SQL_HOST,
    CLOUD_SQL_PASSWORD,
    CLOUD_SQL_PORT,
    CLOUD_SQL_USER,
    COUNTY_FIPS,
    COUNTY_NAME,
    DATABASE_URL,
    LOCAL_SQLITE_PATH,
)
from agent.db.models import (
    AdminAction,
    AgentSession,
    AuditLog,
    Base,
    OutreachFlyer,
    Schedule,
    ScheduleStop,
)

logger = logging.getLogger(__name__)


def _try_cloud_sql_engine() -> Engine | None:
    """Attempt to connect to the provisioned GCP Cloud SQL PostgreSQL instance."""
    if DATABASE_URL:
        try:
            eng = create_engine(DATABASE_URL, pool_pre_ping=True)
            with eng.connect() as conn:
                conn.exec_driver_sql("SELECT 1")
            logger.info("Connected to database via DATABASE_URL")
            return eng
        except Exception as exc:
            logger.warning("DATABASE_URL connection failed (%s); trying Cloud SQL connector/fallback", exc)

    if CLOUD_SQL_PASSWORD:
        # Try Cloud SQL Python Connector first if installed
        try:
            from google.cloud.sql.connector import Connector

            connector = Connector()

            def getconn():
                return connector.connect(
                    CLOUD_SQL_CONNECTION_NAME,
                    "pg8000",
                    user=CLOUD_SQL_USER,
                    password=CLOUD_SQL_PASSWORD,
                    db=CLOUD_SQL_DB_NAME,
                )

            eng = create_engine("postgresql+pg8000://", creator=getconn, pool_pre_ping=True)
            with eng.connect() as conn:
                conn.exec_driver_sql("SELECT 1")
            logger.info("Connected to GCP Cloud SQL via Connector (%s)", CLOUD_SQL_CONNECTION_NAME)
            return eng
        except Exception as exc:
            logger.warning("Cloud SQL Python Connector failed (%s)", exc)

        # Try direct TCP host if provided (e.g. 136.71.50.206)
        host = CLOUD_SQL_HOST or "136.71.50.206"
        for driver in ("psycopg2", "pg8000", "psycopg"):
            try:
                url = f"postgresql+{driver}://{CLOUD_SQL_USER}:{CLOUD_SQL_PASSWORD}@{host}:{CLOUD_SQL_PORT}/{CLOUD_SQL_DB_NAME}"
                eng = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
                with eng.connect() as conn:
                    conn.exec_driver_sql("SELECT 1")
                logger.info("Connected to GCP Cloud SQL via TCP (%s)", host)
                return eng
            except Exception:
                continue

    return None


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return a singleton SQLAlchemy Engine (Cloud SQL PostgreSQL or local SQLite fallback)."""
    pg_engine = _try_cloud_sql_engine()
    if pg_engine is not None:
        Base.metadata.create_all(pg_engine)
        return pg_engine

    LOCAL_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    sqlite_url = f"sqlite:///{LOCAL_SQLITE_PATH.as_posix()}"
    logger.info("Using local relational database mirror at %s", sqlite_url)
    engine = create_engine(sqlite_url, future=True)
    Base.metadata.create_all(engine)
    return engine


@contextmanager
def get_db_session() -> Iterator[Session]:
    """Provide a transactional SQLAlchemy session scope."""
    session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _stop_to_dict(s: ScheduleStop) -> dict[str, Any]:
    return {
        "id": s.id,
        "schedule_id": s.schedule_id,
        "saturday_index": int(s.saturday_index),
        "saturday_date": s.saturday_date.isoformat() if isinstance(s.saturday_date, date) else str(s.saturday_date),
        "geo_id": s.geo_id,
        "neighborhood": s.neighborhood,
        "hpsa_name": s.hpsa_name,
        "hpsa_score": int(s.hpsa_score),
        "landmark_name": s.landmark_name,
        "street_intersection": s.street_intersection,
        "subway_lines": list(s.subway_lines or []),
        "bus_lines": list(s.bus_lines or []),
        "lat": float(s.lat),
        "lon": float(s.lon),
        "total_pop": int(s.total_pop),
        "pct_uninsured": float(s.pct_uninsured),
        "pct_asthma": float(s.pct_asthma),
        "pct_diabetes": float(s.pct_diabetes),
        "van_setup_mode": s.van_setup_mode,
        "clinical_kits": s.clinical_kits,
        "weather_forecast": s.weather_forecast,
        "siting_rationale": s.siting_rationale,
        "is_active": bool(s.is_active),
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


def _audit_to_dict(a: AuditLog) -> dict[str, Any]:
    return {
        "id": a.id,
        "schedule_id": a.schedule_id,
        "iteration_number": int(a.iteration_number),
        "audit_status": a.audit_status,
        "institutional_outliers_detected": a.institutional_outliers_detected,
        "hpsa_diversity_status": a.hpsa_diversity_status,
        "demographic_coverage_ratios": a.demographic_coverage_ratios,
        "violations": a.violations,
        "auditor_comments": a.auditor_comments,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _flyer_to_dict(f: OutreachFlyer) -> dict[str, Any]:
    return {
        "id": f.id,
        "schedule_id": f.schedule_id,
        "stop_id": f.stop_id,
        "saturday_index": int(f.saturday_index),
        "flyer_headline_en": f.flyer_headline_en,
        "flyer_body_en": f.flyer_body_en,
        "flyer_headline_es": f.flyer_headline_es,
        "flyer_body_es": f.flyer_body_es,
        "sms_broadcast_en": f.sms_broadcast_en,
        "sms_broadcast_es": f.sms_broadcast_es,
        "chw_script_en": f.chw_script_en,
        "chw_script_es": f.chw_script_es,
        "created_at": f.created_at.isoformat() if f.created_at else None,
    }


def _action_to_dict(act: AdminAction) -> dict[str, Any]:
    return {
        "id": act.id,
        "schedule_id": act.schedule_id,
        "stop_id": act.stop_id,
        "action_type": act.action_type,
        "rejection_category": act.rejection_category,
        "rejection_reason": act.rejection_reason,
        "admin_user": act.admin_user,
        "timestamp": act.timestamp.isoformat() if act.timestamp else None,
    }


def create_schedule_with_stops(
    target_month: str,
    stops_payload: list[dict[str, Any]],
    status: str = "AUDITED",
) -> dict[str, Any]:
    """Create a new monthly Schedule and its 4 Saturday ScheduleStop rows."""
    with get_db_session() as session:
        sched = Schedule(
            county_fips=COUNTY_FIPS,
            county_name=COUNTY_NAME,
            target_month=target_month,
            status=status,
        )
        session.add(sched)
        session.flush()

        created_stops: list[ScheduleStop] = []
        for item in stops_payload:
            sat_date = item["saturday_date"]
            if isinstance(sat_date, str):
                sat_date = date.fromisoformat(sat_date)
            stop = ScheduleStop(
                schedule_id=sched.id,
                saturday_index=int(item["saturday_index"]),
                saturday_date=sat_date,
                geo_id=str(item["geo_id"]),
                neighborhood=str(item["neighborhood"]),
                hpsa_name=str(item["hpsa_name"]),
                hpsa_score=int(item["hpsa_score"]),
                landmark_name=str(item["landmark_name"]),
                street_intersection=str(item["street_intersection"]),
                subway_lines=list(item.get("subway_lines", [])),
                bus_lines=list(item.get("bus_lines", [])),
                lat=float(item["lat"]),
                lon=float(item["lon"]),
                total_pop=int(item["total_pop"]),
                pct_uninsured=float(item["pct_uninsured"]),
                pct_asthma=float(item["pct_asthma"]),
                pct_diabetes=float(item["pct_diabetes"]),
                van_setup_mode=str(item["van_setup_mode"]),
                clinical_kits=item.get("clinical_kits", []),
                weather_forecast=item.get("weather_forecast", {}),
                siting_rationale=str(item["siting_rationale"]),
                is_active=True,
            )
            session.add(stop)
            created_stops.append(stop)

        session.flush()
        return {
            "schedule_id": sched.id,
            "target_month": sched.target_month,
            "status": sched.status,
            "stops": [_stop_to_dict(s) for s in created_stops],
        }


def record_audit_log(
    schedule_id: str,
    iteration_number: int,
    audit_status: str,
    demographic_coverage_ratios: dict[str, Any],
    auditor_comments: str,
    institutional_outliers_detected: list[dict[str, Any]] | None = None,
    hpsa_diversity_status: str = "PASS",
    violations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Persist an AuditLog entry (supporting multi-iteration self-correction traces)."""
    with get_db_session() as session:
        entry = AuditLog(
            schedule_id=schedule_id,
            iteration_number=int(iteration_number),
            audit_status=audit_status,
            institutional_outliers_detected=institutional_outliers_detected or [],
            hpsa_diversity_status=hpsa_diversity_status,
            demographic_coverage_ratios=demographic_coverage_ratios,
            violations=violations or [],
            auditor_comments=auditor_comments,
        )
        session.add(entry)
        sched = session.get(Schedule, schedule_id)
        if sched and audit_status == "APPROVED":
            sched.status = "AUDITED"
        session.flush()
        return _audit_to_dict(entry)


def save_outreach_flyers(schedule_id: str, flyers_payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Persist bilingual English/Spanish flyers, SMS alerts, and CHW scripts."""
    with get_db_session() as session:
        saved: list[OutreachFlyer] = []
        for item in flyers_payload:
            flyer = OutreachFlyer(
                schedule_id=schedule_id,
                stop_id=str(item["stop_id"]),
                saturday_index=int(item["saturday_index"]),
                flyer_headline_en=str(item["flyer_headline_en"]),
                flyer_body_en=str(item["flyer_body_en"]),
                flyer_headline_es=str(item["flyer_headline_es"]),
                flyer_body_es=str(item["flyer_body_es"]),
                sms_broadcast_en=str(item["sms_broadcast_en"])[:200],
                sms_broadcast_es=str(item["sms_broadcast_es"])[:200],
                chw_script_en=str(item["chw_script_en"]),
                chw_script_es=str(item["chw_script_es"]),
            )
            session.add(flyer)
            saved.append(flyer)
        session.flush()
        return [_flyer_to_dict(f) for f in saved]


def record_admin_approval(
    schedule_id: str,
    stop_id: str | None = None,
    admin_user: str = "admin@bronxhealth.org",
) -> dict[str, Any]:
    """Record an admin approval action in `admin_actions` and mark schedule APPROVED."""
    with get_db_session() as session:
        act = AdminAction(
            schedule_id=schedule_id,
            stop_id=stop_id,
            action_type="APPROVE",
            admin_user=admin_user,
        )
        session.add(act)
        sched = session.get(Schedule, schedule_id)
        if sched:
            sched.status = "APPROVED"
        session.flush()
        return _action_to_dict(act)


def replace_rejected_stop(
    schedule_id: str,
    rejected_stop_id: str,
    rejection_category: str,
    rejection_reason: str,
    replacement_stop_payload: dict[str, Any],
    replacement_flyer_payload: dict[str, Any] | None = None,
    admin_user: str = "admin@bronxhealth.org",
) -> dict[str, Any]:
    """Deactivate a rejected Saturday stop, log the DENY/REPLAN action, and insert the replacement stop."""
    with get_db_session() as session:
        old_stop = session.get(ScheduleStop, rejected_stop_id)
        if old_stop is not None:
            old_stop.is_active = False

        deny_action = AdminAction(
            schedule_id=schedule_id,
            stop_id=rejected_stop_id,
            action_type="DENY",
            rejection_category=rejection_category,
            rejection_reason=rejection_reason,
            admin_user=admin_user,
        )
        session.add(deny_action)

        sat_date = replacement_stop_payload["saturday_date"]
        if isinstance(sat_date, str):
            sat_date = date.fromisoformat(sat_date)

        new_stop = ScheduleStop(
            schedule_id=schedule_id,
            saturday_index=int(replacement_stop_payload["saturday_index"]),
            saturday_date=sat_date,
            geo_id=str(replacement_stop_payload["geo_id"]),
            neighborhood=str(replacement_stop_payload["neighborhood"]),
            hpsa_name=str(replacement_stop_payload["hpsa_name"]),
            hpsa_score=int(replacement_stop_payload["hpsa_score"]),
            landmark_name=str(replacement_stop_payload["landmark_name"]),
            street_intersection=str(replacement_stop_payload["street_intersection"]),
            subway_lines=list(replacement_stop_payload.get("subway_lines", [])),
            bus_lines=list(replacement_stop_payload.get("bus_lines", [])),
            lat=float(replacement_stop_payload["lat"]),
            lon=float(replacement_stop_payload["lon"]),
            total_pop=int(replacement_stop_payload["total_pop"]),
            pct_uninsured=float(replacement_stop_payload["pct_uninsured"]),
            pct_asthma=float(replacement_stop_payload["pct_asthma"]),
            pct_diabetes=float(replacement_stop_payload["pct_diabetes"]),
            van_setup_mode=str(replacement_stop_payload["van_setup_mode"]),
            clinical_kits=replacement_stop_payload.get("clinical_kits", []),
            weather_forecast=replacement_stop_payload.get("weather_forecast", {}),
            siting_rationale=str(replacement_stop_payload["siting_rationale"]),
            is_active=True,
        )
        session.add(new_stop)
        session.flush()

        replan_action = AdminAction(
            schedule_id=schedule_id,
            stop_id=new_stop.id,
            action_type="REPLAN",
            rejection_category=rejection_category,
            rejection_reason=f"Replaced {old_stop.geo_id if old_stop else 'stop'} -> {new_stop.geo_id}: {rejection_reason}",
            admin_user=admin_user,
        )
        session.add(replan_action)

        saved_flyer = None
        if replacement_flyer_payload:
            flyer = OutreachFlyer(
                schedule_id=schedule_id,
                stop_id=new_stop.id,
                saturday_index=new_stop.saturday_index,
                flyer_headline_en=str(replacement_flyer_payload["flyer_headline_en"]),
                flyer_body_en=str(replacement_flyer_payload["flyer_body_en"]),
                flyer_headline_es=str(replacement_flyer_payload["flyer_headline_es"]),
                flyer_body_es=str(replacement_flyer_payload["flyer_body_es"]),
                sms_broadcast_en=str(replacement_flyer_payload["sms_broadcast_en"])[:200],
                sms_broadcast_es=str(replacement_flyer_payload["sms_broadcast_es"])[:200],
                chw_script_en=str(replacement_flyer_payload["chw_script_en"]),
                chw_script_es=str(replacement_flyer_payload["chw_script_es"]),
            )
            session.add(flyer)
            session.flush()
            saved_flyer = _flyer_to_dict(flyer)

        return {
            "denied_stop_id": rejected_stop_id,
            "new_stop": _stop_to_dict(new_stop),
            "admin_action": _action_to_dict(deny_action),
            "new_flyer": saved_flyer,
        }


def get_latest_schedule_bundle() -> dict[str, Any] | None:
    """Return the most recent Schedule with its active stops, audit logs, flyers, and admin actions."""
    with get_db_session() as session:
        stmt = select(Schedule).order_by(Schedule.created_at.desc()).limit(1)
        sched = session.execute(stmt).scalars().first()
        if sched is None:
            return None

        active_stops = [
            _stop_to_dict(s)
            for s in sorted(sched.stops, key=lambda x: (x.saturday_index, x.created_at or datetime.min.replace(tzinfo=timezone.utc)))
            if s.is_active
        ]
        inactive_stops = [_stop_to_dict(s) for s in sched.stops if not s.is_active]
        audit_logs = [
            _audit_to_dict(a) for a in sorted(sched.audit_logs, key=lambda x: x.iteration_number)
        ]
        active_stop_ids = {s["id"] for s in active_stops}
        flyers = [
            _flyer_to_dict(f)
            for f in sorted(sched.outreach_flyers, key=lambda x: x.saturday_index)
            if f.stop_id in active_stop_ids
        ]
        admin_actions = [
            _action_to_dict(act)
            for act in sorted(sched.admin_actions, key=lambda x: x.timestamp or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        ]

        return {
            "schedule": {
                "id": sched.id,
                "county_fips": sched.county_fips,
                "county_name": sched.county_name,
                "target_month": sched.target_month,
                "status": sched.status,
                "created_at": sched.created_at.isoformat() if sched.created_at else None,
            },
            "active_stops": active_stops,
            "replaced_stops_history": inactive_stops,
            "audit_logs": audit_logs,
            "outreach_flyers": flyers,
            "admin_actions": admin_actions,
        }


def upsert_agent_session(
    session_id: str,
    user_id: str,
    session_state: dict[str, Any],
    chat_history: list[dict[str, Any]],
) -> dict[str, Any]:
    """Persist or update an ADK agent session and chat history."""
    with get_db_session() as session:
        obj = session.get(AgentSession, session_id)
        if obj is None:
            obj = AgentSession(
                session_id=session_id,
                user_id=user_id,
                session_state=session_state,
                chat_history=chat_history,
            )
            session.add(obj)
        else:
            obj.user_id = user_id
            obj.session_state = session_state
            obj.chat_history = chat_history
        session.flush()
        return {
            "session_id": obj.session_id,
            "user_id": obj.user_id,
            "session_state": obj.session_state,
            "chat_history": obj.chat_history,
        }
