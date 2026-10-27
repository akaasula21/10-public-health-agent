-- ============================================================================
-- GCP Cloud SQL (PostgreSQL 16) Schema for Public Health Mobile Care Broker
-- Instance: public-health-db | Database: public_health_broker
-- Target Jurisdiction: Bronx County, NY (FIPS 36005)
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 1. Schedules Table (Master monthly plans)
CREATE TABLE IF NOT EXISTS schedules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    county_fips VARCHAR(5) NOT NULL DEFAULT '36005',
    county_name VARCHAR(100) NOT NULL DEFAULT 'Bronx County, NY',
    target_month VARCHAR(20) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'DRAFT', -- DRAFT, AUDITED, APPROVED, REJECTED
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. Schedule Stops Table (Individual Saturday van deployments)
CREATE TABLE IF NOT EXISTS schedule_stops (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    schedule_id UUID REFERENCES schedules(id) ON DELETE CASCADE,
    saturday_index INT NOT NULL CHECK (saturday_index BETWEEN 1 AND 4),
    saturday_date DATE NOT NULL,
    geo_id VARCHAR(11) NOT NULL,
    neighborhood VARCHAR(100) NOT NULL,
    hpsa_name VARCHAR(100) NOT NULL,
    hpsa_score INT NOT NULL,
    landmark_name VARCHAR(255) NOT NULL,
    street_intersection VARCHAR(255) NOT NULL,
    subway_lines TEXT[] NOT NULL,
    bus_lines TEXT[] NOT NULL,
    lat NUMERIC(9, 6) NOT NULL,
    lon NUMERIC(9, 6) NOT NULL,
    total_pop INT NOT NULL,
    pct_uninsured NUMERIC(5, 2) NOT NULL,
    pct_asthma NUMERIC(5, 2) NOT NULL,
    pct_diabetes NUMERIC(5, 2) NOT NULL,
    van_setup_mode VARCHAR(150) NOT NULL,
    clinical_kits JSONB NOT NULL,
    weather_forecast JSONB NOT NULL,
    siting_rationale TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. Admin Actions Table (Human-in-the-Loop audit trail)
CREATE TABLE IF NOT EXISTS admin_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    schedule_id UUID REFERENCES schedules(id) ON DELETE CASCADE,
    stop_id UUID REFERENCES schedule_stops(id),
    action_type VARCHAR(20) NOT NULL, -- APPROVE, DENY, REPLAN
    rejection_category VARCHAR(50),  -- ROAD_CONSTRUCTION, COMMUNITY_EVENT, CLEARANCE, CAPACITY
    rejection_reason TEXT,           -- Admin's verbatim explanation
    admin_user VARCHAR(100) DEFAULT 'admin@bronxhealth.org',
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. Audit Logs Table (Trap detection & self-correction trace for judges)
CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    schedule_id UUID REFERENCES schedules(id) ON DELETE CASCADE,
    iteration_number INT NOT NULL,
    audit_status VARCHAR(20) NOT NULL, -- APPROVED, REJECTED
    institutional_outliers_detected JSONB,
    hpsa_diversity_status VARCHAR(255),
    demographic_coverage_ratios JSONB NOT NULL,
    violations JSONB,
    auditor_comments TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5. Outreach Flyers Table (Exclusive Flyer Agent outputs)
CREATE TABLE IF NOT EXISTS outreach_flyers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    schedule_id UUID REFERENCES schedules(id) ON DELETE CASCADE,
    stop_id UUID REFERENCES schedule_stops(id) ON DELETE CASCADE,
    saturday_index INT NOT NULL,
    flyer_headline_en VARCHAR(255) NOT NULL,
    flyer_body_en TEXT NOT NULL,
    flyer_headline_es VARCHAR(255) NOT NULL,
    flyer_body_es TEXT NOT NULL,
    sms_broadcast_en VARCHAR(200) NOT NULL,
    sms_broadcast_es VARCHAR(200) NOT NULL,
    chw_script_en TEXT NOT NULL,
    chw_script_es TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 6. Agent Sessions Table (ADK state & chat history)
CREATE TABLE IF NOT EXISTS agent_sessions (
    session_id VARCHAR(100) PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL,
    session_state JSONB NOT NULL,
    chat_history JSONB NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_schedule_stops_schedule_id ON schedule_stops(schedule_id, is_active);
CREATE INDEX IF NOT EXISTS idx_audit_logs_schedule_id ON audit_logs(schedule_id, iteration_number);
CREATE INDEX IF NOT EXISTS idx_outreach_flyers_schedule_id ON outreach_flyers(schedule_id, saturday_index);
