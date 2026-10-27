"""BigQuery client wrapper with automatic credential resolution and county-aware local cache support."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

import pandas as pd
from google.cloud import bigquery

from agent.config import (
    BQ_LOCATION,
    CLEAN_BOROUGH_CONTEXT_VIEW,
    CLEAN_CARE_SITES_VIEW,
    CLEAN_COUNTY_CONTEXT_VIEW,
    CLEAN_EQUITY_AUDIT_VIEW,
    CLEAN_TRACTS_GENERIC_VIEW,
    CLEAN_TRACTS_VIEW,
    COUNTY_FIPS,
    GCP_PROJECT_ID,
    PILOT_COUNTY_FIPS,
    get_cache_paths,
    normalize_county_fips,
)

logger = logging.getLogger(__name__)


@lru_cache(maxsize=4)
def get_bq_client(project_id: str = GCP_PROJECT_ID) -> bigquery.Client:
    """Return a cached BigQuery client with ADC and pydata_google_auth fallback."""
    try:
        return bigquery.Client(project=project_id, location=BQ_LOCATION)
    except Exception as exc:
        logger.warning("Default BigQuery credentials failed (%s); trying pydata_google_auth", exc)
        import pydata_google_auth

        scopes = ["https://www.googleapis.com/auth/cloud-platform"]
        credentials = pydata_google_auth.get_user_credentials(scopes, use_local_webserver=True)
        return bigquery.Client(project=project_id, location=BQ_LOCATION, credentials=credentials)


def run_query_df(
    sql: str,
    params: list[Any] | None = None,
    project_id: str = GCP_PROJECT_ID,
) -> pd.DataFrame:
    """Execute a BigQuery SQL query and return a pandas DataFrame."""
    client = get_bq_client(project_id)
    job_config = bigquery.QueryJobConfig()
    if params:
        job_config.query_parameters = params
    return client.query(sql, job_config=job_config).to_dataframe()


def load_clean_tracts_df(
    prefer_cache: bool = True,
    county_fips: str = COUNTY_FIPS,
) -> pd.DataFrame:
    """Load the cleaned census tracts DataFrame for `county_fips` from local cache or BigQuery."""
    fips = normalize_county_fips(county_fips)
    paths = get_cache_paths(fips)
    if prefer_cache and paths["tracts_parquet"].exists():
        return pd.read_parquet(paths["tracts_parquet"])
    view_name = CLEAN_TRACTS_VIEW if fips == PILOT_COUNTY_FIPS else CLEAN_TRACTS_GENERIC_VIEW
    try:
        df = run_query_df(
            f"SELECT * FROM `{view_name}` "
            f"WHERE STARTS_WITH(CAST(geo_id AS STRING), '{fips}') "
            f"ORDER BY geo_id"
        )
    except Exception:
        df = run_query_df(
            f"SELECT * FROM `{CLEAN_TRACTS_VIEW}` "
            f"WHERE STARTS_WITH(CAST(geo_id AS STRING), '{fips}') "
            f"ORDER BY geo_id"
        )
    paths["tracts_parquet"].parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(paths["tracts_parquet"], index=False)
    return df


def load_clean_care_sites_df(
    prefer_cache: bool = True,
    county_fips: str = COUNTY_FIPS,
) -> pd.DataFrame:
    """Load the cleaned care sites DataFrame for `county_fips` from local cache or BigQuery."""
    fips = normalize_county_fips(county_fips)
    paths = get_cache_paths(fips)
    if prefer_cache and paths["care_sites_parquet"].exists():
        return pd.read_parquet(paths["care_sites_parquet"])
    df = run_query_df(f"SELECT * FROM `{CLEAN_CARE_SITES_VIEW}` ORDER BY site_id")
    paths["care_sites_parquet"].parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(paths["care_sites_parquet"], index=False)
    return df


def load_clean_equity_audit_df(
    prefer_cache: bool = True,
    county_fips: str = COUNTY_FIPS,
) -> pd.DataFrame:
    """Load the isolated post-hoc demographic equity audit DataFrame from cache or BigQuery."""
    fips = normalize_county_fips(county_fips)
    paths = get_cache_paths(fips)
    if prefer_cache and paths["equity_audit_parquet"].exists():
        return pd.read_parquet(paths["equity_audit_parquet"])
    df = run_query_df(
        f"SELECT * FROM `{CLEAN_EQUITY_AUDIT_VIEW}` "
        f"WHERE STARTS_WITH(CAST(geo_id AS STRING), '{fips}') "
        f"ORDER BY geo_id"
    )
    paths["equity_audit_parquet"].parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(paths["equity_audit_parquet"], index=False)
    return df


def load_clean_county_context(
    prefer_cache: bool = True,
    county_fips: str = COUNTY_FIPS,
) -> dict[str, Any]:
    """Load county-level multi-scale environmental and surveillance blind-spot metadata."""
    fips = normalize_county_fips(county_fips)
    paths = get_cache_paths(fips)
    if prefer_cache and paths["context_json"].exists():
        return json.loads(paths["context_json"].read_text(encoding="utf-8"))
    view_name = CLEAN_BOROUGH_CONTEXT_VIEW if fips == PILOT_COUNTY_FIPS else CLEAN_COUNTY_CONTEXT_VIEW
    try:
        df = run_query_df(f"SELECT * FROM `{view_name}` LIMIT 1")
    except Exception:
        df = run_query_df(f"SELECT * FROM `{CLEAN_BOROUGH_CONTEXT_VIEW}` LIMIT 1")
    record = df.iloc[0].to_dict() if not df.empty else {}
    paths["context_json"].parent.mkdir(parents=True, exist_ok=True)
    paths["context_json"].write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    return record


def load_clean_borough_context(
    prefer_cache: bool = True,
    county_fips: str = COUNTY_FIPS,
) -> dict[str, Any]:
    """Backward-compatible alias for `load_clean_county_context`."""
    return load_clean_county_context(prefer_cache=prefer_cache, county_fips=county_fips)


def load_tracts_geojson(county_fips: str = COUNTY_FIPS) -> dict[str, Any]:
    """Load the cached 2020 census tract polygon GeoJSON FeatureCollection for `county_fips`."""
    fips = normalize_county_fips(county_fips)
    paths = get_cache_paths(fips)
    if paths["tracts_geojson"].exists():
        return json.loads(paths["tracts_geojson"].read_text(encoding="utf-8"))
    try:
        from agent.data.cleaner import export_tracts_geojson

        tracts_df = load_clean_tracts_df(prefer_cache=True, county_fips=fips)
        export_tracts_geojson(tracts_df, county_fips=fips, output_path=paths["tracts_geojson"])
        if paths["tracts_geojson"].exists():
            return json.loads(paths["tracts_geojson"].read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not dynamically export GeoJSON for county %s: %s", fips, exc)
    raise FileNotFoundError(
        f"GeoJSON cache not found at {paths['tracts_geojson']}. "
        f"Run `python scripts/load_county_data.py --county-fips {fips}` or `python scripts/clean_bronx_data.py --county-fips {fips}` first."
    )


# Backward-compatible convenience aliases
load_clean_tracts = load_clean_tracts_df
load_clean_care_sites = load_clean_care_sites_df
load_clean_equity_audit = load_clean_equity_audit_df


def load_bronx_tracts_geojson() -> dict[str, Any]:
    """Backward-compatible alias for `load_tracts_geojson`."""
    return load_tracts_geojson(county_fips=COUNTY_FIPS)


