"""SQLAlchemy ORM models for the Bronx Mobile Care Broker."""

from __future__ import annotations

import uuid
from datetime import datetime
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    JSON,
)
from sqlalchemy.orm import relationship

from db.database import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


class Schedule(Base):
    __tablename__ = "schedules"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    county_fips = Column(String(5), nullable=False, default="36005")
    county_name = Column(String(100), nullable=False, default="Bronx County, NY")
    target_month = Column(String(50), nullable=False, default="Upcoming Month")
    status = Column(String(30), nullable=False, default="DRAFT")  # DRAFT, AUDITED, APPROVED, REJECTED
    summary = Column(Text, nullable=True)
    director_briefing = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    stops = relationship("ScheduleStop", back_populates="schedule", cascade="all, delete-orphan", order_by="ScheduleStop.saturday_index")
    admin_actions = relationship("AdminAction", back_populates="schedule", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="schedule", cascade="all, delete-orphan")
    flyers = relationship("OutreachFlyer", back_populates="schedule", cascade="all, delete-orphan")


class ScheduleStop(Base):
    __tablename__ = "schedule_stops"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    schedule_id = Column(String(36), ForeignKey("schedules.id", ondelete="CASCADE"), nullable=False)
    saturday_index = Column(Integer, nullable=False)  # 1 to 4
    saturday_date = Column(String(20), nullable=False)
    geo_id = Column(String(11), nullable=False)
    neighborhood = Column(String(100), nullable=False)
    hpsa_name = Column(String(100), nullable=False)
    hpsa_score = Column(Float, nullable=False, default=0.0)
    composite_score = Column(Float, nullable=False, default=0.0)
    landmark_name = Column(String(255), nullable=False)
    street_intersection = Column(String(255), nullable=False)
    subway_lines = Column(JSON, nullable=False, default=list)
    bus_lines = Column(JSON, nullable=False, default=list)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    total_pop = Column(Integer, nullable=False, default=0)
    pct_uninsured = Column(Float, nullable=False, default=0.0)
    pct_asthma = Column(Float, nullable=False, default=0.0)
    pct_diabetes = Column(Float, nullable=False, default=0.0)
    van_setup_mode = Column(String(150), nullable=False)
    clinical_kits = Column(JSON, nullable=False, default=dict)
    weather_forecast = Column(JSON, nullable=False, default=dict)
    siting_rationale = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    schedule = relationship("Schedule", back_populates="stops")
    flyers = relationship("OutreachFlyer", back_populates="stop")


class AdminAction(Base):
    __tablename__ = "admin_actions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    schedule_id = Column(String(36), ForeignKey("schedules.id", ondelete="CASCADE"), nullable=False)
    stop_id = Column(String(36), nullable=True)
    action_type = Column(String(20), nullable=False)  # APPROVE, DENY, REPLAN
    rejection_category = Column(String(50), nullable=True)  # ROAD_CONSTRUCTION, COMMUNITY_EVENT, CAPACITY, OTHER
    rejection_reason = Column(Text, nullable=True)  # Admin's verbatim explanation
    admin_user = Column(String(100), default="admin@bronxhealth.org")
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    schedule = relationship("Schedule", back_populates="admin_actions")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    schedule_id = Column(String(36), ForeignKey("schedules.id", ondelete="CASCADE"), nullable=False)
    iteration_number = Column(Integer, nullable=False, default=1)
    audit_status = Column(String(20), nullable=False)  # APPROVED, REJECTED
    institutional_outliers_detected = Column(JSON, nullable=True, default=list)
    hpsa_diversity_status = Column(String(255), nullable=True)
    demographic_coverage_ratios = Column(JSON, nullable=False, default=dict)
    violations = Column(JSON, nullable=True, default=list)
    auditor_comments = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    schedule = relationship("Schedule", back_populates="audit_logs")


class OutreachFlyer(Base):
    __tablename__ = "outreach_flyers"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    schedule_id = Column(String(36), ForeignKey("schedules.id", ondelete="CASCADE"), nullable=False)
    stop_id = Column(String(36), ForeignKey("schedule_stops.id", ondelete="SET NULL"), nullable=True)
    saturday_index = Column(Integer, nullable=False)
    headline_en = Column(String(255), nullable=False)
    body_en = Column(Text, nullable=False)
    headline_es = Column(String(255), nullable=False)
    body_es = Column(Text, nullable=False)
    sms_en = Column(String(255), nullable=False)
    sms_es = Column(String(255), nullable=False)
    chw_script_en = Column(Text, nullable=False)
    chw_script_es = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    schedule = relationship("Schedule", back_populates="flyers")
    stop = relationship("ScheduleStop", back_populates="flyers")


class AgentSession(Base):
    __tablename__ = "agent_sessions"

    session_id = Column(String(100), primary_key=True)
    user_id = Column(String(100), nullable=False, default="user_default")
    session_state = Column(JSON, nullable=False, default=dict)
    chat_history = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
