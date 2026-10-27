"""Public Health Equity & Mobile Care Broker Multi-Agent Package."""

from agent.data.cleaner import check_bq_data_cleaned, ensure_data_loaded_and_cleaned

try:
    from agent.agent import (
        root_agent,
        planner_agent,
        auditor_agent,
        flyer_agent,
        director_agent,
        siting_and_audit_loop,
        run_broker,
    )
    __all__ = [
        "check_bq_data_cleaned",
        "ensure_data_loaded_and_cleaned",
        "root_agent",
        "planner_agent",
        "auditor_agent",
        "flyer_agent",
        "director_agent",
        "siting_and_audit_loop",
        "run_broker",
    ]
except ImportError:
    # When running in environments where google.adk is not yet installed
    # (e.g. local data loading, BigQuery cleaning, CLI scripting)
    __all__ = [
        "check_bq_data_cleaned",
        "ensure_data_loaded_and_cleaned",
    ]
