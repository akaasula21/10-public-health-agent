"""Pydantic schemas for the Bronx Mobile Care Broker API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ScheduleStopResponse(BaseModel):
    id: str
    saturday_index: int
    saturday_date: str
    geo_id: str
    neighborhood: str
    hpsa_name: str
    hpsa_score: float
    composite_score: float
    landmark_name: str
    street_intersection: str
    subway_lines: List[str] = Field(default_factory=list)
    bus_lines: List[str] = Field(default_factory=list)
    lat: float
    lon: float
    total_pop: int
    pct_uninsured: float
    pct_asthma: float
    pct_diabetes: float
    van_setup_mode: str
    clinical_kits: Dict[str, Any] = Field(default_factory=dict)
    weather_forecast: Dict[str, Any] = Field(default_factory=dict)
    siting_rationale: str
    is_active: bool

    class Config:
        from_attributes = True


class OutreachFlyerResponse(BaseModel):
    id: str
    saturday_index: int
    headline_en: str
    body_en: str
    headline_es: str
    body_es: str
    sms_en: str
    sms_es: str
    chw_script_en: str
    chw_script_es: str

    class Config:
        from_attributes = True


class AuditLogResponse(BaseModel):
    id: str
    iteration_number: int
    audit_status: str
    institutional_outliers_detected: Optional[List[Any]] = None
    hpsa_diversity_status: Optional[str] = None
    demographic_coverage_ratios: Dict[str, Any] = Field(default_factory=dict)
    violations: Optional[List[Any]] = None
    auditor_comments: str
    created_at: Any

    class Config:
        from_attributes = True


class ScheduleResponse(BaseModel):
    id: str
    county_fips: str
    county_name: str
    target_month: str
    status: str
    summary: Optional[str] = None
    director_briefing: Optional[str] = None
    created_at: Any
    stops: List[ScheduleStopResponse] = Field(default_factory=list)
    audit_logs: List[AuditLogResponse] = Field(default_factory=list)
    flyers: List[OutreachFlyerResponse] = Field(default_factory=list)

    class Config:
        from_attributes = True


class GenerateScheduleRequest(BaseModel):
    target_month: str = "Upcoming Month"
    user_prompt: Optional[str] = None
    force_refresh: bool = False


class AdminActionRequest(BaseModel):
    schedule_id: str
    action_type: str = Field(..., description="APPROVE, DENY, or REPLAN")
    rejection_category: Optional[str] = Field(
        None, description="ROAD_CONSTRUCTION, COMMUNITY_EVENT, CAPACITY, CLEARANCE, OTHER"
    )
    rejection_reason: Optional[str] = Field(None, description="Verbatim justification from human administrator")
    admin_user: str = "admin@bronxhealth.org"
    stop_id: Optional[str] = None


class AdminActionResponse(BaseModel):
    id: str
    schedule_id: str
    action_type: str
    rejection_category: Optional[str] = None
    rejection_reason: Optional[str] = None
    admin_user: str
    schedule_status: str
