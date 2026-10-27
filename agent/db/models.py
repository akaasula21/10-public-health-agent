"""SQLAlchemy 2.0 ORM models for the 6 GCP Cloud SQL (PostgreSQL) tables.

Includes cross-dialect TypeDecorators (`StringArrayType` and `JSONBType`) so the
exact same models run natively on Cloud SQL PostgreSQL 15/16 (`TEXT[]`, `JSONB`, `UUID`)
and transparently fall back to SQLite when offline.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
     Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.types import JSON, TypeDecorator

Base = declarative_base()


class UUIDStringType(TypeDecorator):
    """Stores UUID as native PostgreSQL UUID or 36-char string in SQLite."""

    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=False))
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value: Any, dialect) -> str | None:
        if value is None:
            return None
        return str(value)

    def process_result_value(self, value: Any, dialect) -> str | None:
        if value is None:
            return None
        return str(value)


class StringArrayType(TypeDecorator):
    """Stores list[str] as native PostgreSQL TEXT[] or JSON array in SQLite."""

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_ARRAY(Text))
        return dialect.type_descriptor(Text)

    def process_bind_param(self, value: list[str] | str | None, dialect) -> Any:
        if value is None:
            return [] if dialect.name == "postgresql" else "[]"
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                value = [str(x) for x in parsed] if isinstance(parsed, list) else [value]
            except Exception:
                value = [value]
        else:
            value = [str(x) for x in value]
        if dialect.name == "postgresql":
            return value
        return json.dumps(value)

    def process_result_value(self, value: Any, dialect) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(x) for x in value]
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return [str(x) for x in parsed] if isinstance(parsed, list) else [value]
            except Exception:
                return [value]
        return list(value)


class JSONBType(TypeDecorator):
    """Stores dict/list as native PostgreSQL JSONB or standard JSON in SQLite."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_JSONB())
        return dialect.type_descriptor(JSON())


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> str:
    return str(uuid.uuid4())


class Schedule(Base):
    """1. Master monthly plans (`schedules`)."""

    __tablename__ = "schedules"

    id = Column(UUIDStringType, primary_key=True, default=_new_uuid)
    county_fips = Column(String(5), nullable=False, default="36005")
    county_name = Column(String(100), nullable=False, default="Bronx County, NY")
    target_month = Column(String(20), nullable=False)
    status = Column(String(30), nullable=False, default="DRAFT")  # DRAFT, AUDITED, APPROVED, REJECTED
    created_at = Column(DateTime(timezone=True), default=_utc_now)
    updated_at = Column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now)

    stops = relationship("ScheduleStop", back_populates="schedule", cascade="all, delete-orphan")
    admin_actions = relationship("AdminAction", back_populates="schedule", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="schedule", cascade="all, delete-orphan")
    outreach_flyers = relationship("OutreachFlyer", back_populates="schedule", cascade="all, delete-orphan")


class ScheduleStop(Base):
    """2. Individual Saturday van deployments (`schedule_stops`)."""

    __tablename__ = "schedule_stops"
    __table_args__ = (
        CheckConstraint("saturday_index BETWEEN 1 AND 4", name="chk_saturday_index_1_4"),
    )

    id = Column(UUIDStringType, primary_key=True, default=_new_uuid)
    schedule_id = Column(UUIDStringType, ForeignKey("schedules.id", ondelete="CASCADE"), nullable=False)
    saturday_index = Column(Integer, nullable=False)
    saturday_date = Column(Date, nullable=False)
    geo_id = Column(String(11), nullable=False)
    neighborhood = Column(String(100), nullable=False)
    hpsa_name = Column(String(100), nullable=False)
    hpsa_score = Column(Integer, nullable=False)
    landmark_name = Column(String(255), nullable=False)
    street_intersection = Column(String(255), nullable=False)
    subway_lines = Column(StringArrayType, nullable=False)
    bus_lines = Column(StringArrayType, nullable=False)
    lat = Column(Numeric(9, 6), nullable=False)
    lon = Column(Numeric(9, 6), nullable=False)
    total_pop = Column(Integer, nullable=False)
    pct_uninsured = Column(Numeric(5, 2), nullable=False)
    pct_asthma = Column(Numeric(5, 2), nullable=False)
    pct_diabetes = Column(Numeric(5, 2), nullable=False)
    van_setup_mode = Column(String(150), nullable=False)
    clinical_kits = Column(JSONBType, nullable=False)
    weather_forecast = Column(JSONBType, nullable=False)
    siting_rationale = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utc_now)

    schedule = relationship("Schedule", back_populates="stops")


class AdminAction(Base):
    """3. Human-in-the-Loop audit trail (`admin_actions`)."""

    __tablename__ = "admin_actions"

    id = Column(UUIDStringType, primary_key=True, default=_new_uuid)
    schedule_id = Column(UUIDStringType, ForeignKey("schedules.id", ondelete="CASCADE"), nullable=False)
    stop_id = Column(UUIDStringType, ForeignKey("schedule_stops.id"), nullable=True)
    action_type = Column(String(20), nullable=False)  # APPROVE, DENY, REPLAN
    rejection_category = Column(String(50), nullable=True)  # ROAD_CONSTRUCTION, COMMUNITY_EVENT, CLEARANCE, CAPACITY
    rejection_reason = Column(Text, nullable=True)
    admin_user = Column(String(100), default="admin@bronxhealth.org")
    timestamp = Column(DateTime(timezone=True), default=_utc_now)

    schedule = relationship("Schedule", back_populates="admin_actions")


class AuditLog(Base):
    """4. Trap detection & self-correction trace (`audit_logs`)."""

    __tablename__ = "audit_logs"

    id = Column(UUIDStringType, primary_key=True, default=_new_uuid)
    schedule_id = Column(UUIDStringType, ForeignKey("schedules.id", ondelete="CASCADE"), nullable=False)
    iteration_number = Column(Integer, nullable=False)
    audit_status = Column(String(20), nullable=False)  # APPROVED, REJECTED
    institutional_outliers_detected = Column(JSONBType, nullable=True)
    hpsa_diversity_status = Column(String(255), nullable=True)
    demographic_coverage_ratios = Column(JSONBType, nullable=False)
    violations = Column(JSONBType, nullable=True)
    auditor_comments = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utc_now)

    schedule = relationship("Schedule", back_populates="audit_logs")


class OutreachFlyer(Base):
    """5. Exclusive Flyer Agent outputs (`outreach_flyers`)."""

    __tablename__ = "outreach_flyers"

    id = Column(UUIDStringType, primary_key=True, default=_new_uuid)
    schedule_id = Column(UUIDStringType, ForeignKey("schedules.id", ondelete="CASCADE"), nullable=False)
    stop_id = Column(UUIDStringType, ForeignKey("schedule_stops.id", ondelete="CASCADE"), nullable=False)
    saturday_index = Column(Integer, nullable=False)
    flyer_headline_en = Column(String(255), nullable=False)
    flyer_body_en = Column(Text, nullable=False)
    flyer_headline_es = Column(String(255), nullable=False)
    flyer_body_es = Column(Text, nullable=False)
    sms_broadcast_en = Column(String(200), nullable=False)
    sms_broadcast_es = Column(String(200), nullable=False)
    chw_script_en = Column(Text, nullable=False)
    chw_script_es = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utc_now)

    schedule = relationship("Schedule", back_populates="outreach_flyers")


class AgentSession(Base):
    """6. ADK state & chat history (`agent_sessions`)."""

    __tablename__ = "agent_sessions"

    session_id = Column(String(100), primary_key=True)
    user_id = Column(String(100), nullable=False, default="director@bronxhealth.org")
    session_state = Column(JSONBType, nullable=False, default=dict)
    chat_history = Column(JSONBType, nullable=False, default=list)
    updated_at = Column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now)
