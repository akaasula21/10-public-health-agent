"""Data loaders, BigQuery client, cleaning pipeline, and landmark catalogs."""

from agent.data.loader import CountyDataLoader, run_unified_loader
from agent.data.cleaner import (
    run_dataset_cleaner,
    build_clean_tracts_sql,
    build_clean_care_sites_sql,
    build_clean_county_context_sql,
    build_clean_equity_audit_sql,
)
from agent.data.bq_client import (
    get_bq_client,
    load_clean_tracts,
    load_clean_tracts_df,
    load_clean_care_sites,
    load_clean_care_sites_df,
    load_clean_equity_audit,
    load_clean_equity_audit_df,
    load_clean_county_context,
    load_clean_borough_context,
    load_tracts_geojson,
    load_bronx_tracts_geojson,
)
from agent.data.landmarks_catalog import (
    lookup_tract_landmark_context,
    lookup_bronx_landmark_context,
)

__all__ = [
    "CountyDataLoader",
    "run_unified_loader",
    "run_dataset_cleaner",
    "build_clean_tracts_sql",
    "build_clean_care_sites_sql",
    "build_clean_county_context_sql",
    "build_clean_equity_audit_sql",
    "get_bq_client",
    "load_clean_tracts",
    "load_clean_tracts_df",
    "load_clean_care_sites",
    "load_clean_care_sites_df",
    "load_clean_equity_audit",
    "load_clean_equity_audit_df",
    "load_clean_county_context",
    "load_clean_borough_context",
    "load_tracts_geojson",
    "load_bronx_tracts_geojson",
    "lookup_tract_landmark_context",
    "lookup_bronx_landmark_context",
]
