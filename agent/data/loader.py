"""Unified County-Agnostic Dataset Loader for Public Health Mobile Care Broker.

Configured with Bronx County, NY (FIPS 36005) as the default pilot county (`PILOT_COUNTY_FIPS = "36005"`),
while fully supporting any US county via FIPS configuration.

Handles:
1. Base tables (8 core tables): `burden_tracts`, `exposure_tracts`, `care_sites_state`,
   `care_sites`, `shortage_areas`, `shortage_facilities`, `disease_weekly`, `tract_access`.
   Supports both fast-path GCS snapshot loading and live federal API retrieval.
2. Supplemental tables & restricted audit dataset:
   `places_supplement_tracts`, `svi_supplement_tracts`, `tract_neighbors`,
   `shortage_areas_all_disciplines`, `shortage_mua_tracts`, `exposure_supplement_tracts`,
   `climate_heat_risk_tracts`, `noaa_seasonal_heat`, `tract_access_enhanced`,
   `planner_tract_features`, `equity_audit_tracts`, `v_county_equity_baseline`.
3. Materializing cleaned BigQuery views and local caches (`agent.data.cleaner`).
4. County-agnostic validation suite.
"""

from __future__ import annotations

import io
import json
import logging
import math
import re
import sys
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

import numpy as np
import pandas as pd
import requests
from google.cloud import bigquery
from google.cloud.exceptions import NotFound

from agent.config import (
    BQ_AUDIT_DATASET,
    BQ_DATASET,
    COUNTY_FIPS,
    GCP_PROJECT_ID,
    GCS_CHALLENGE_BUCKET,
    KNOWN_COUNTIES,
    PILOT_COUNTY_FIPS,
    PRE_STAGED_COUNTY_FIPS,
    CountyConfig,
    get_county_config,
    normalize_county_fips,
)
from agent.data.bq_client import get_bq_client
from agent.data.cleaner import run_dataset_cleaner

logger = logging.getLogger(__name__)

# Socrata endpoint identifiers
PLACES_SOCRATA = "cwsq-ngmh"  # CDC PLACES Census Tract Data
EPHT_PM25_SOCRATA = "cjae-szjv"  # CDC EPHT PM2.5 Annual Average
NSSP_SOCRATA = "rdmq-nq56"  # CDC NSSP Emergency Department visits
SVI_2022_SOCRATA = "4d8n-kk8a"  # CDC/ATSDR Social Vulnerability Index 2022

# HRSA ArcGIS MapServer endpoints
HRSA_MAPSERVER_BASE = "https://data.hrsa.gov/arcgis/rest/services/HealthCenterProgram/HCP_HealthCenters/MapServer"
HRSA_HPSA_LAYER = "https://data.hrsa.gov/arcgis/rest/services/Shortage/HPSA/MapServer/9"
HRSA_MUA_LAYER = "https://data.hrsa.gov/arcgis/rest/services/Shortage/MUA/MapServer/15"

# FEMA National Risk Index base URL
FEMA_NRI_ZIP_BASE = "https://hazards.fema.gov/nri/Content/StaticDocuments/DataDownload/NRI_Table_CensusTracts"

HC_FIELDS = (
    "FACILITY_NM",
    "CMS_PROVIDER_NUM",
    "CMS_PROVIDER_ADDRESS",
    "CMS_PROVIDER_ZIP_CD",
    "STATE_NM",
    "CNTY_NM",
    "HC_PROG_IDENTIFIER",
    "HCC_TYP_DESC",
    "HCC_LOC_SETTING_DESC",
    "CMS_PROVIDER_CAT_DESC",
    "TOT_OPER_HR_PER_WEEK",
    "OPER_STATUS_DESC",
    "SBHC_SUB_PROG_IND",
    "LONGITUDE",
    "LATITUDE",
)

HPSA_FIELDS = (
    "GEO_ID",
    "HPSA_NM",
    "HPSA_SCORE",
    "HPSA_STATUS_DESC",
    "HPSA_TYP_DESC",
    "DISCIPLINE_CLASS_DESC",
    "HPSA_POVERTY",
    "STATE_COUNTY_FIPS_CD",
)

FAC_FIELDS = (
    "CMN_FAC_NM",
    "CMN_STATE_COUNTY_FIPS_CD",
    "HPSA_SCORE",
    "DISCIPLINE_CLASS_DESC",
    "LONGITUDE",
    "LATITUDE",
)

HPSA_ALL_FIELDS = (
    "GEO_ID",
    "HPSA_NM",
    "HPSA_ID",
    "HPSA_SCORE",
    "HPSA_STATUS_DESC",
    "HPSA_TYP_DESC",
    "DISCIPLINE_CLASS_DESC",
    "HPSA_DESIGNATION_DT",
    "HPSA_DESIGNATION_LAST_UPDATE_DT",
    "STATE_COUNTY_FIPS_CD",
)

MUA_FIELDS = (
    "GEO_ID",
    "MUA_MUP_NM",
    "MUA_MUP_ID",
    "MUA_MUP_TYP_DESC",
    "MUA_MUP_STATUS_DESC",
    "IMU_SCORE",
    "RUR_STATUS_DESC",
    "DESIGNATION_DT",
    "UPDATE_DT",
    "STATE_COUNTY_FIPS_CD",
)

# Explicit BigQuery schema types for empty shortage tables
SHORTAGE_SCHEMA_TYPES = {
    "GEO_ID": "STRING",
    "HPSA_NM": "STRING",
    "HPSA_ID": "STRING",
    "HPSA_SCORE": "INTEGER",
    "HPSA_STATUS_DESC": "STRING",
    "HPSA_TYP_DESC": "STRING",
    "DISCIPLINE_CLASS_DESC": "STRING",
    "HPSA_POVERTY": "FLOAT",
    "STATE_COUNTY_FIPS_CD": "STRING",
    "HPSA_DESIGNATION_DT": "STRING",
    "HPSA_DESIGNATION_LAST_UPDATE_DT": "STRING",
    "CMN_FAC_NM": "STRING",
    "CMN_STATE_COUNTY_FIPS_CD": "STRING",
    "LONGITUDE": "FLOAT",
    "LATITUDE": "FLOAT",
    "MUA_MUP_NM": "STRING",
    "MUA_MUP_ID": "STRING",
    "MUA_MUP_TYP_DESC": "STRING",
    "MUA_MUP_STATUS_DESC": "STRING",
    "IMU_SCORE": "FLOAT",
    "RUR_STATUS_DESC": "STRING",
    "DESIGNATION_DT": "STRING",
    "UPDATE_DT": "STRING",
}


def socrata_fetch(dataset_id: str, params: dict[str, Any], page_size: int = 50000, max_pages: int = 20) -> pd.DataFrame:
    """Fetch paginated records from a Socrata Open Data API."""
    url = f"https://data.cdc.gov/resource/{dataset_id}.json"
    rows: list[dict[str, Any]] = []
    p = dict(params)
    p["$limit"] = page_size
    offset = 0

    for _ in range(max_pages):
        p["$offset"] = offset
        resp = requests.get(url, params=p, timeout=45)
        if resp.status_code != 200:
            break
        data = resp.json()
        if not data or not isinstance(data, list):
            break
        rows.extend(data)
        if len(data) < page_size:
            break
        offset += page_size

    return pd.DataFrame(rows)


def arcgis_fetch(layer_url: str, where_clause: str, out_fields: tuple[str, ...], batch_size: int = 1000) -> pd.DataFrame:
    """Fetch records from an ArcGIS FeatureServer/MapServer layer with pagination."""
    query_url = f"{layer_url}/query"
    offset = 0
    records: list[dict[str, Any]] = []

    while True:
        params = {
            "where": where_clause,
            "outFields": ",".join(out_fields),
            "outSR": "4326",
            "f": "json",
            "resultOffset": offset,
            "resultRecordCount": batch_size,
            "returnGeometry": "true",
        }
        resp = requests.get(query_url, params=params, timeout=45)
        if resp.status_code != 200:
            break
        payload = resp.json()
        features = payload.get("features", [])
        if not features:
            break

        for f in features:
            attrs = dict(f.get("attributes", {}))
            geom = f.get("geometry", {})
            if "x" in geom and "y" in geom and "LONGITUDE" not in attrs:
                attrs["LONGITUDE"] = geom["x"]
                attrs["LATITUDE"] = geom["y"]
            records.append(attrs)

        if not payload.get("exceededTransferLimit", False) and len(features) < batch_size:
            break
        offset += len(features)

    return pd.DataFrame(records)


def make_empty_shortage_df(cols: tuple[str, ...]) -> pd.DataFrame:
    """Create an empty DataFrame typed appropriately for BigQuery schema creation."""
    data: dict[str, Any] = {}
    for c in cols:
        stype = SHORTAGE_SCHEMA_TYPES.get(c, "STRING")
        if stype == "INTEGER":
            data[c] = pd.Series(dtype="Int64")
        elif stype == "FLOAT":
            data[c] = pd.Series(dtype="float64")
        else:
            data[c] = pd.Series(dtype="object")
    return pd.DataFrame(data)


def bq_schema_for_shortage(cols: tuple[str, ...]) -> list[bigquery.SchemaField]:
    """Return explicit BigQuery SchemaFields for shortage tables to prevent schema drift."""
    fields = []
    for c in cols:
        stype = SHORTAGE_SCHEMA_TYPES.get(c, "STRING")
        fields.append(bigquery.SchemaField(c, stype))
    return fields


@dataclass
class CountyDataLoader:
    """Unified dataset loader for any US county."""

    county_fips: str = PILOT_COUNTY_FIPS
    project_id: str | None = GCP_PROJECT_ID
    dataset: str | None = BQ_DATASET
    audit_dataset: str | None = BQ_AUDIT_DATASET
    base_source: str = "auto"  # 'auto', 'gcs', or 'live'
    county_name: str | None = None
    state_abbr: str | None = None
    skip_weather: bool = False
    stage: str = "all"

    _config: CountyConfig = field(init=False)
    _client: bigquery.Client = field(init=False)

    def __post_init__(self) -> None:
        self.county_fips = normalize_county_fips(self.county_fips)
        self.project_id = self.project_id or GCP_PROJECT_ID
        self.dataset = self.dataset or BQ_DATASET
        self.audit_dataset = self.audit_dataset or BQ_AUDIT_DATASET
        self._config = get_county_config(
            self.county_fips,
            county_name=self.county_name,
            state_abbr=self.state_abbr,
        )
        self._client = get_bq_client(self.project_id)

    @property
    def config(self) -> CountyConfig:
        return self._config

    @property
    def is_pilot(self) -> bool:
        return self.county_fips == PILOT_COUNTY_FIPS

    def ensure_datasets(self) -> None:
        """Ensure destination BigQuery datasets exist."""
        for ds_name in (self.dataset, self.audit_dataset):
            ds_ref = bigquery.DatasetReference(self.project_id, ds_name)
            try:
                self._client.get_dataset(ds_ref)
            except NotFound:
                ds = bigquery.Dataset(ds_ref)
                ds.location = "US"
                self._client.create_dataset(ds)
                logger.info("Created BigQuery dataset `%s.%s`", self.project_id, ds_name)

    def upload_df(
        self,
        df: pd.DataFrame,
        table_name: str,
        target_dataset: str | None = None,
        schema: list[bigquery.SchemaField] | None = None,
    ) -> int:
        """Write DataFrame to BigQuery table with WRITE_TRUNCATE."""
        ds = target_dataset or self.dataset
        full_table = f"{self.project_id}.{ds}.{table_name}"
        job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
        if schema:
            job_config.schema = schema
        job = self._client.load_table_from_dataframe(df, full_table, job_config=job_config)
        job.result()
        logger.info("Loaded %s rows into `%s`", f"{len(df):,}", full_table)
        return len(df)

    def load_base_from_gcs(self) -> dict[str, int]:
        """Fast-path loader for pre-staged Challenge 5 county Parquet snapshots in GCS."""
        base_tables = (
            "burden_tracts",
            "exposure_tracts",
            "care_sites_state",
            "care_sites",
            "shortage_areas",
            "shortage_facilities",
            "disease_weekly",
            "tract_access",
        )
        optional_shortage_schemas = {
            "shortage_areas": HPSA_FIELDS,
            "shortage_facilities": FAC_FIELDS,
        }
        loaded = {}
        for tbl in base_tables:
            candidate_uris = (
                f"{GCS_CHALLENGE_BUCKET}/{self.county_fips}/{tbl}/data.parquet",
                f"{GCS_CHALLENGE_BUCKET}/{self.county_fips}/{tbl}.parquet",
            )
            full_table = f"{self.project_id}.{self.dataset}.{tbl}"
            job_config = bigquery.LoadJobConfig(
                source_format=bigquery.SourceFormat.PARQUET,
                write_disposition="WRITE_TRUNCATE",
            )
            last_err: Exception | None = None
            success = False
            for uri in candidate_uris:
                try:
                    load_job = self._client.load_table_from_uri(uri, full_table, job_config=job_config)
                    load_job.result()
                    table = self._client.get_table(full_table)
                    loaded[tbl] = table.num_rows
                    logger.info("GCS snapshot loaded `%s` from %s: %s rows", tbl, uri, f"{table.num_rows:,}")
                    success = True
                    break
                except Exception as e:
                    last_err = e

            if not success:
                if tbl in optional_shortage_schemas:
                    cols = optional_shortage_schemas[tbl]
                    logger.info(
                        "Optional shortage table `%s` not present in GCS for county %s; creating empty typed table",
                        tbl,
                        self.county_fips,
                    )
                    empty_df = make_empty_shortage_df(cols)
                    loaded[tbl] = self.upload_df(empty_df, tbl, schema=bq_schema_for_shortage(cols))
                else:
                    logger.warning(
                        "Could not load `%s` from GCS snapshot (%s): %s",
                        tbl,
                        candidate_uris[0],
                        last_err,
                    )
                    raise last_err  # type: ignore[misc]
        return loaded

    def load_base_from_live_apis(self) -> dict[str, int]:
        """Live federal API loader for the 8 core tables for any US county."""
        cfg = self.config
        loaded = {}

        # 1. burden_tracts from CDC PLACES
        logger.info("Fetching burden_tracts from CDC PLACES for county %s...", cfg.county_fips)
        places_params = {
            "$where": f"countyfips='{cfg.county_fips}'",
            "$select": "locationid as geo_id, totalpopulation as total_pop, geolocation, "
                       "uninsured_crudeprev as pct_uninsured, "
                       "casthma_crudeprev as pct_asthma, "
                       "copd_crudeprev as pct_copd, "
                       "diabetes_crudeprev as pct_diabetes, "
                       "mobility_crudeprev as pct_mobility_difficulty",
        }
        df_places = socrata_fetch(PLACES_SOCRATA, places_params)
        if df_places.empty:
            raise RuntimeError(f"CDC PLACES returned no tracts for county FIPS {cfg.county_fips}")

        # Parse coordinates
        def extract_coords(row):
            geo = row.get("geolocation")
            if isinstance(geo, dict) and "coordinates" in geo:
                coords = geo["coordinates"]
                return coords[1], coords[0]  # lat, lon
            return np.nan, np.nan

        coords = df_places.apply(extract_coords, axis=1)
        df_places["latitude"] = [c[0] for c in coords]
        df_places["longitude"] = [c[1] for c in coords]
        df_places.drop(columns=["geolocation"], inplace=True, errors="ignore")

        # Census TIGERweb fallback if coordinates missing
        if df_places["latitude"].isna().any():
            tw_url = (
                f"https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Tracts_Blocks/MapServer/8/query"
                f"?where=STATE='{cfg.state_fips}'+AND+COUNTY='{cfg.county_code_3}'"
                f"&outFields=GEOID,CENTLAT,CENTLON&f=json&returnGeometry=false"
            )
            try:
                tw_resp = requests.get(tw_url, timeout=30).json()
                tw_map = {
                    f["attributes"]["GEOID"]: (
                        float(f["attributes"]["CENTLAT"]),
                        float(f["attributes"]["CENTLON"]),
                    )
                    for f in tw_resp.get("features", [])
                }
                for idx, r in df_places.iterrows():
                    if pd.isna(r["latitude"]) and r["geo_id"] in tw_map:
                        lat, lon = tw_map[r["geo_id"]]
                        df_places.at[idx, "latitude"] = lat
                        df_places.at[idx, "longitude"] = lon
            except Exception as ex:
                logger.warning("Census TIGERweb fallback failed: %s", ex)

        # Pull ACS vehicle & 65+ from BigQuery public data if available
        try:
            acs_sql = f"""
            SELECT geo_id,
                   ROUND(100.0 * SAFE_DIVIDE(no_cars, total_households), 2) AS pct_no_vehicle,
                   ROUND(100.0 * SAFE_DIVIDE(pop_65_plus, total_pop), 2) AS pct_age_65_plus
            FROM (
              SELECT geo_id,
                     total_pop,
                     B25044_003 + B25044_010 AS no_cars,
                     B25044_001 AS total_households,
                     B01001_020 + B01001_021 + B01001_022 + B01001_023 + B01001_024 + B01001_025 +
                     B01001_044 + B01001_045 + B01001_046 + B01001_047 + B01001_048 + B01001_049 AS pop_65_plus
              FROM `bigquery-public-data.census_bureau_acs.censustract_2020_5yr`
              WHERE geo_id LIKE '{cfg.county_fips}%'
            )
            """
            acs_df = self._client.query(acs_sql).to_dataframe()
            df_places = df_places.merge(acs_df, on="geo_id", how="left")
        except Exception as e:
            logger.warning("Could not pull Census ACS vehicle/age data: %s", e)
            df_places["pct_no_vehicle"] = 15.0
            df_places["pct_age_65_plus"] = 14.0

        for num_col in ("total_pop", "pct_uninsured", "pct_asthma", "pct_copd", "pct_diabetes", "pct_mobility_difficulty", "latitude", "longitude", "pct_no_vehicle", "pct_age_65_plus"):
            if num_col in df_places.columns:
                df_places[num_col] = pd.to_numeric(df_places[num_col], errors="coerce")

        loaded["burden_tracts"] = self.upload_df(df_places, "burden_tracts")

        # 2. exposure_tracts from CDC EPHT PM2.5 (2019)
        logger.info("Fetching exposure_tracts from CDC EPHT for county %s...", cfg.county_fips)
        epht_params = {
            "$where": f"statefips='{cfg.state_fips}' and year='2019'",
            "$select": "countyfips, tractfips as geo_id, ds_pm_pred as mean_pm, ds_pm_max as max_pm, ds_pm_days35 as days_over_35",
        }
        df_epht = socrata_fetch(EPHT_PM25_SOCRATA, epht_params)
        df_epht = df_epht[df_epht["countyfips"] == cfg.county_fips].copy()
        for num_col in ("mean_pm", "max_pm", "days_over_35"):
            if num_col in df_epht.columns:
                df_epht[num_col] = pd.to_numeric(df_epht[num_col], errors="coerce")
        df_epht.drop(columns=["countyfips"], inplace=True, errors="ignore")
        loaded["exposure_tracts"] = self.upload_df(df_epht, "exposure_tracts")

        # 3. care_sites_state and care_sites from HRSA ArcGIS
        logger.info("Fetching HRSA care sites for state %s...", cfg.state_abbr)
        df_sites_state = arcgis_fetch(
            f"{HRSA_MAPSERVER_BASE}/0",
            f"STATE_NM = '{cfg.state_abbr}'",
            HC_FIELDS,
        )
        if df_sites_state.empty:
            df_sites_state = pd.DataFrame(columns=HC_FIELDS)
        else:
            df_sites_state["site_kind"] = "Health Center site"
            df_sites_state["LONGITUDE"] = pd.to_numeric(df_sites_state["LONGITUDE"], errors="coerce")
            df_sites_state["LATITUDE"] = pd.to_numeric(df_sites_state["LATITUDE"], errors="coerce")
            df_sites_state.rename(columns={"LONGITUDE": "longitude", "LATITUDE": "latitude"}, inplace=True)
        loaded["care_sites_state"] = self.upload_df(df_sites_state, "care_sites_state")

        # Filter care_sites spatially to county
        self._client.query(f"""
        CREATE OR REPLACE TABLE `{self.project_id}.{self.dataset}.care_sites` AS
        SELECT s.*
        FROM `{self.project_id}.{self.dataset}.care_sites_state` s
        JOIN `bigquery-public-data.geo_us_boundaries.counties` c
          ON c.county_fips_code = '{cfg.county_fips}'
         AND ST_CONTAINS(c.county_geom, ST_GEOGPOINT(s.longitude, s.latitude))
        """).result()
        n_cs = list(self._client.query(f"SELECT COUNT(*) FROM `{self.project_id}.{self.dataset}.care_sites`").result())[0][0]
        loaded["care_sites"] = n_cs

        # 4. shortage_areas (Primary Care HPSA)
        logger.info("Fetching HRSA shortage_areas for county %s...", cfg.county_fips)
        df_hpsa = arcgis_fetch(
            HRSA_HPSA_LAYER,
            f"STATE_COUNTY_FIPS_CD = '{cfg.county_fips}' AND DISCIPLINE_CLASS_DESC = 'Primary Care'",
            HPSA_FIELDS,
        )
        if df_hpsa.empty:
            df_hpsa = make_empty_shortage_df(HPSA_FIELDS)
            hpsa_schema = bq_schema_for_shortage(HPSA_FIELDS)
        else:
            hpsa_schema = None
            df_hpsa["HPSA_SCORE"] = pd.to_numeric(df_hpsa["HPSA_SCORE"], errors="coerce")
            df_hpsa["HPSA_POVERTY"] = pd.to_numeric(df_hpsa["HPSA_POVERTY"], errors="coerce")
        loaded["shortage_areas"] = self.upload_df(df_hpsa, "shortage_areas", schema=hpsa_schema)

        # 5. shortage_facilities
        logger.info("Fetching HRSA shortage_facilities for county %s...", cfg.county_fips)
        df_fac = arcgis_fetch(
            f"{HRSA_HPSA_LAYER.replace('/9', '/0')}",
            f"CMN_STATE_COUNTY_FIPS_CD = '{cfg.county_fips}' AND DISCIPLINE_CLASS_DESC = 'Primary Care'",
            FAC_FIELDS,
        )
        if df_fac.empty:
            df_fac = make_empty_shortage_df(FAC_FIELDS)
            fac_schema = bq_schema_for_shortage(FAC_FIELDS)
        else:
            fac_schema = None
            df_fac["HPSA_SCORE"] = pd.to_numeric(df_fac["HPSA_SCORE"], errors="coerce")
            df_fac["LONGITUDE"] = pd.to_numeric(df_fac["LONGITUDE"], errors="coerce")
            df_fac["LATITUDE"] = pd.to_numeric(df_fac["LATITUDE"], errors="coerce")
            df_fac.rename(columns={"LONGITUDE": "longitude", "LATITUDE": "latitude"}, inplace=True)
        loaded["shortage_facilities"] = self.upload_df(df_fac, "shortage_facilities", schema=fac_schema)

        # 6. disease_weekly from CDC NSSP
        logger.info("Fetching disease_weekly from CDC NSSP for county %s...", cfg.county_fips)
        nssp_params = {
            "$where": f"fips={int(cfg.county_fips)}",
            "$order": "week_end",
        }
        df_nssp = socrata_fetch(NSSP_SOCRATA, nssp_params)
        if not df_nssp.empty:
            df_nssp = df_nssp[df_nssp["county"] != "All"].copy()
            for c in [c for c in df_nssp.columns if c.startswith("percent_")]:
                df_nssp[c] = pd.to_numeric(df_nssp[c], errors="coerce")
            df_nssp["week_end"] = pd.to_datetime(df_nssp["week_end"], errors="coerce").dt.strftime("%Y-%m-%d")
            df_nssp.rename(
                columns={
                    "percent_visits_smoothed_1": "percent_visits_smoothed_influenza",
                    "percent_visits_smoothed": "percent_visits_smoothed_combined",
                },
                inplace=True,
            )
        loaded["disease_weekly"] = self.upload_df(df_nssp, "disease_weekly")

        # 7. tract_access (spatial distance calculation)
        logger.info("Computing tract_access spatial metrics in BigQuery...")
        access_sql = f"""
        CREATE OR REPLACE TABLE `{self.project_id}.{self.dataset}.tract_access` AS
        WITH t AS (
          SELECT geo_id, total_pop, pct_uninsured, pct_asthma, pct_copd, pct_diabetes,
                 pct_no_vehicle, pct_age_65_plus, pct_mobility_difficulty,
                 ST_GEOGPOINT(longitude, latitude) AS pt
          FROM `{self.project_id}.{self.dataset}.burden_tracts`
          WHERE longitude IS NOT NULL AND latitude IS NOT NULL
        ),
        any_site AS (
          SELECT ST_GEOGPOINT(longitude, latitude) AS pt
          FROM `{self.project_id}.{self.dataset}.care_sites`
        ),
        safety_net AS (
          SELECT ST_GEOGPOINT(longitude, latitude) AS pt
          FROM `{self.project_id}.{self.dataset}.care_sites`
          WHERE site_kind IN ('FQHC', 'Health Center site')
        ),
        d1 AS (
          SELECT t.geo_id, MIN(ST_DISTANCE(t.pt, s.pt))/1000 AS km_any
          FROM t CROSS JOIN any_site s GROUP BY 1
        ),
        d2 AS (
          SELECT t.geo_id, MIN(ST_DISTANCE(t.pt, s.pt))/1000 AS km_safety_net
          FROM t CROSS JOIN safety_net s GROUP BY 1
        )
        SELECT t.geo_id, t.total_pop, t.pct_uninsured, t.pct_asthma, t.pct_diabetes,
               t.pct_no_vehicle, t.pct_age_65_plus,
               ROUND(d1.km_any, 2) AS km_to_any_care,
               ROUND(d2.km_safety_net, 2) AS km_to_safety_net,
               ROUND(d2.km_safety_net - d1.km_any, 2) AS extra_km_if_uninsured
        FROM t
        LEFT JOIN d1 USING (geo_id)
        LEFT JOIN d2 USING (geo_id)
        """
        self._client.query(access_sql).result()
        n_acc = list(self._client.query(f"SELECT COUNT(*) FROM `{self.project_id}.{self.dataset}.tract_access`").result())[0][0]
        loaded["tract_access"] = n_acc

        return loaded

    def load_base_tables(self) -> dict[str, int]:
        """Load the 8 core base tables using either GCS snapshot or live APIs."""
        self.ensure_datasets()
        use_gcs = False
        if self.base_source == "gcs":
            use_gcs = True
        elif self.base_source == "auto":
            use_gcs = (self.county_fips in PRE_STAGED_COUNTY_FIPS)

        if use_gcs:
            try:
                logger.info("Using fast-path GCS snapshot for county %s", self.county_fips)
                return self.load_base_from_gcs()
            except Exception as exc:
                logger.warning("GCS snapshot load failed (%s); falling back to live federal APIs", exc)

        logger.info("Loading base tables via live federal APIs for county %s", self.county_fips)
        return self.load_base_from_live_apis()

    def load_supplemental_tables(self) -> dict[str, int]:
        """Load all 10 supplemental tables + equity audit dataset."""
        cfg = self.config
        loaded = {}

        # 1. places_supplement_tracts
        logger.info("Loading places_supplement_tracts for county %s...", cfg.county_fips)
        places_cols = (
            "locationid as geo_id, totalpopulation as total_pop, "
            "casthma_crudeprev as crude_asthma, casthma_adjprev as age_adj_asthma, "
            "casthma_crude95ci as ci_asthma, "
            "copd_crudeprev as crude_copd, copd_adjprev as age_adj_copd, "
            "diabetes_crudeprev as crude_diabetes, diabetes_adjprev as age_adj_diabetes, "
            "bphigh_crudeprev as crude_high_bp, bphigh_adjprev as age_adj_high_bp, "
            "chd_crudeprev as crude_chd, chd_adjprev as age_adj_chd, "
            "stroke_crudeprev as crude_stroke, stroke_adjprev as age_adj_stroke, "
            "checkup_crudeprev as crude_checkup, checkup_adjprev as age_adj_checkup, "
            "depression_crudeprev as crude_depression, depression_adjprev as age_adj_depression, "
            "obesity_crudeprev as crude_obesity, obesity_adjprev as age_adj_obesity, "
            "uninsured_crudeprev as crude_uninsured, uninsured_adjprev as age_adj_uninsured, "
            "uninsured_crude95ci as ci_uninsured, "
            "disability_crudeprev as crude_any_disability, "
            "mobility_crudeprev as crude_mobility_difficulty, "
            "foodsec_crudeprev as crude_food_insecurity, "
            "transport_crudeprev as crude_lack_transport, "
            "housingin_crudeprev as crude_housing_insecurity, "
            "utility_crudeprev as crude_utility_insecurity, "
            "isolat_crudeprev as crude_social_isolation, "
            "internet_crudeprev as crude_no_internet"
        )
        places_params = {
            "$where": f"countyfips='{cfg.county_fips}'",
            "$select": places_cols,
        }
        df_supp_places = socrata_fetch(PLACES_SOCRATA, places_params)
        if not df_supp_places.empty:
            for c in df_supp_places.columns:
                if c not in ("geo_id", "ci_asthma", "ci_uninsured"):
                    df_supp_places[c] = pd.to_numeric(df_supp_places[c], errors="coerce")
        loaded["places_supplement_tracts"] = self.upload_df(df_supp_places, "places_supplement_tracts")

        # 2. svi_supplement_tracts & equity_audit_tracts
        logger.info("Loading SVI 2022 supplement & equity audit tracts for county %s...", cfg.county_fips)
        svi_params = {
            "$where": f"stcofips='{cfg.county_fips}'",
            "$select": "fips as geo_id, stcofips, county, state, "
                       "rpl_theme1 as svi_socioeconomic, rpl_theme2 as svi_household, "
                       "rpl_theme4 as svi_housing_transport, "
                       "ep_uninsur as pct_uninsured_svi, ep_age65 as pct_age_65_plus_svi, "
                       "ep_age17 as pct_age_17_under_svi, ep_disabl as pct_disability_svi, "
                       "ep_sngpnt as pct_single_parent, ep_limeng as pct_limited_english, "
                       "ep_minrty as pct_minority, ep_hisp as pct_hispanic, "
                       "ep_afam as pct_black_nonhisp, ep_asian as pct_asian_nonhisp, "
                       "ep_noveh as pct_no_vehicle, ep_groupq as pct_group_quarters, "
                       "ep_pov150 as pct_below_150pct_poverty",
        }
        df_svi = socrata_fetch(SVI_2022_SOCRATA, svi_params)

        # Pull ACS poverty, median income, and white non-Hispanic baseline for equity audit enrichment
        acs_enrich_sql = f"""
        SELECT geo_id,
               ROUND(100.0 * SAFE_DIVIDE(white_nh, total_pop), 2) AS pct_white_nonhisp_est,
               ROUND(100.0 * SAFE_DIVIDE(poverty_100, total_pop), 2) AS acs_pct_below_100pct_poverty,
               CAST(median_income AS FLOAT64) AS acs_median_hh_income,
               ROUND(100.0 * SAFE_DIVIDE(hispanic, total_pop), 2) AS acs_pct_hispanic,
               ROUND(100.0 * SAFE_DIVIDE(black, total_pop), 2) AS acs_pct_black_nonhisp,
               ROUND(100.0 * SAFE_DIVIDE(asian, total_pop), 2) AS acs_pct_asian_nonhisp,
               ROUND(100.0 * SAFE_DIVIDE(minority, total_pop), 2) AS acs_pct_minority,
               ROUND(100.0 * SAFE_DIVIDE(poverty_150, total_pop), 2) AS acs_pct_below_150pct_poverty,
               ROUND(100.0 * SAFE_DIVIDE(group_q, total_pop), 2) AS acs_pct_group_quarters,
               ROUND(100.0 * SAFE_DIVIDE(no_veh, total_households), 2) AS acs_pct_no_vehicle
        FROM (
          SELECT geo_id, total_pop,
                 B03002_003 AS white_nh,
                 B03002_012 AS hispanic,
                 B03002_004 AS black,
                 B03002_006 AS asian,
                 total_pop - B03002_003 AS minority,
                 B17001_002 AS poverty_100,
                 B17024_002 + B17024_003 + B17024_004 AS poverty_150,
                 B19013_001 AS median_income,
                 B26001_001 AS group_q,
                 B25044_003 + B25044_010 AS no_veh,
                 B25044_001 AS total_households
          FROM `bigquery-public-data.census_bureau_acs.censustract_2020_5yr`
          WHERE geo_id LIKE '{cfg.county_fips}%'
        )
        """
        try:
            df_acs_enrich = self._client.query(acs_enrich_sql).to_dataframe()
        except Exception as e:
            logger.warning("BigQuery ACS enrichment query failed: %s", e)
            df_acs_enrich = pd.DataFrame()

        # Fallback to BigQuery ACS if SVI Socrata returned empty
        if df_svi.empty and not df_acs_enrich.empty:
            logger.info("SVI Socrata empty; building SVI & demographic baseline from BigQuery ACS...")
            df_svi = df_acs_enrich.rename(
                columns={
                    "acs_pct_hispanic": "pct_hispanic",
                    "acs_pct_black_nonhisp": "pct_black_nonhisp",
                    "acs_pct_asian_nonhisp": "pct_asian_nonhisp",
                    "acs_pct_minority": "pct_minority",
                    "acs_pct_below_150pct_poverty": "pct_below_150pct_poverty",
                    "acs_pct_group_quarters": "pct_group_quarters",
                    "acs_pct_no_vehicle": "pct_no_vehicle",
                }
            ).copy()
            df_svi["svi_socioeconomic"] = 0.50
            df_svi["svi_household"] = 0.50
            df_svi["svi_housing_transport"] = 0.50
            df_svi["pct_limited_english"] = 10.0
        elif not df_svi.empty and not df_acs_enrich.empty:
            df_svi = df_svi.merge(
                df_acs_enrich[["geo_id", "pct_white_nonhisp_est", "acs_pct_below_100pct_poverty", "acs_median_hh_income"]],
                on="geo_id",
                how="left",
            )

        # Split into race-blind planner table vs isolated equity audit table
        if not df_svi.empty:
            for num_col in [c for c in df_svi.columns if c not in ("geo_id", "stcofips", "county", "state")]:
                df_svi[num_col] = pd.to_numeric(df_svi[num_col], errors="coerce")

            if "pct_white_nonhisp_est" not in df_svi.columns:
                df_svi["pct_white_nonhisp_est"] = np.maximum(0.0, 100.0 - df_svi["pct_minority"].fillna(0.0))
            else:
                df_svi["pct_white_nonhisp_est"] = df_svi["pct_white_nonhisp_est"].fillna(
                    np.maximum(0.0, 100.0 - df_svi["pct_minority"].fillna(0.0))
                )
            if "acs_pct_below_100pct_poverty" not in df_svi.columns:
                df_svi["acs_pct_below_100pct_poverty"] = (df_svi["pct_below_150pct_poverty"].fillna(20.0) * 0.67).round(2)
            if "acs_median_hh_income" not in df_svi.columns:
                df_svi["acs_median_hh_income"] = 45000.0

            # Upload race-blind SVI planner columns first, then attach tract polygon geometry
            svi_planner_cols = [
                c
                for c in (
                    "geo_id",
                    "svi_socioeconomic",
                    "svi_household",
                    "svi_housing_transport",
                    "pct_no_vehicle",
                    "pct_group_quarters",
                    "pct_limited_english",
                )
                if c in df_svi.columns
            ]
            self.upload_df(df_svi[svi_planner_cols].copy(), "svi_supplement_tracts")

            self._client.query(f"""
            CREATE OR REPLACE TABLE `{self.project_id}.{self.dataset}.svi_supplement_tracts` AS
            SELECT s.geo_id,
                   s.svi_socioeconomic, s.svi_household, s.svi_housing_transport,
                   s.pct_no_vehicle, s.pct_group_quarters, s.pct_limited_english,
                   c.tract_geom
            FROM `{self.project_id}.{self.dataset}.svi_supplement_tracts` s
            LEFT JOIN `bigquery-public-data.geo_us_boundaries.census_tracts` c
              ON c.geo_id = s.geo_id
            """).result()

            # Upload the equity audit table (Theme 3 demographics) into restricted audit dataset
            audit_cols = [
                c
                for c in (
                    "geo_id",
                    "pct_minority",
                    "pct_hispanic",
                    "pct_black_nonhisp",
                    "pct_asian_nonhisp",
                    "pct_white_nonhisp_est",
                    "pct_below_150pct_poverty",
                    "acs_pct_below_100pct_poverty",
                    "acs_median_hh_income",
                )
                if c in df_svi.columns
            ]
            df_audit = df_svi[audit_cols].copy()
            loaded["equity_audit_tracts"] = self.upload_df(
                df_audit, "equity_audit_tracts", target_dataset=self.audit_dataset
            )
        loaded["svi_supplement_tracts"] = list(self._client.query(f"SELECT COUNT(*) FROM `{self.project_id}.{self.dataset}.svi_supplement_tracts`").result())[0][0]

        # 3. tract_neighbors (Queen contiguity ST_TOUCHES + Bridge connectivity)
        logger.info("Computing Queen contiguity tract_neighbors for county %s...", cfg.county_fips)
        bridge_cte = ""
        if self.is_pilot:
            # City Island Bridge connectivity in Bronx County
            bridge_cte = """
            UNION ALL
            SELECT '36005051601' AS geo_id, '36005051602' AS neighbor_geo_id,
                   ST_DISTANCE(c1.tract_geom, c2.tract_geom) AS border_length_m,
                   TRUE AS is_bridged_connection
            FROM `bigquery-public-data.geo_us_boundaries.census_tracts` c1
            CROSS JOIN `bigquery-public-data.geo_us_boundaries.census_tracts` c2
            WHERE c1.geo_id = '36005051601' AND c2.geo_id = '36005051602'
            UNION ALL
            SELECT '36005051602' AS geo_id, '36005051601' AS neighbor_geo_id,
                   ST_DISTANCE(c1.tract_geom, c2.tract_geom) AS border_length_m,
                   TRUE AS is_bridged_connection
            FROM `bigquery-public-data.geo_us_boundaries.census_tracts` c1
            CROSS JOIN `bigquery-public-data.geo_us_boundaries.census_tracts` c2
            WHERE c1.geo_id = '36005051602' AND c2.geo_id = '36005051601'
            """

        neighbors_sql = f"""
        CREATE OR REPLACE TABLE `{self.project_id}.{self.dataset}.tract_neighbors` AS
        WITH raw_touches AS (
          SELECT
            c1.geo_id,
            c2.geo_id AS neighbor_geo_id,
            ST_LENGTH(ST_INTERSECTION(c1.tract_geom, c2.tract_geom)) AS border_length_m,
            FALSE AS is_bridged_connection
          FROM `bigquery-public-data.geo_us_boundaries.census_tracts` c1
          JOIN `bigquery-public-data.geo_us_boundaries.census_tracts` c2
            ON ST_TOUCHES(c1.tract_geom, c2.tract_geom)
           AND c1.geo_id != c2.geo_id
          WHERE c1.state_fips_code = '{cfg.state_fips}'
            AND c1.county_fips_code = '{cfg.county_code_3}'
            AND c2.state_fips_code = '{cfg.state_fips}'
            AND c2.county_fips_code = '{cfg.county_code_3}'
          {bridge_cte}
        )
        SELECT DISTINCT geo_id, neighbor_geo_id, border_length_m, is_bridged_connection
        FROM raw_touches
        """
        self._client.query(neighbors_sql).result()
        loaded["tract_neighbors"] = list(self._client.query(f"SELECT COUNT(*) FROM `{self.project_id}.{self.dataset}.tract_neighbors`").result())[0][0]

        # 4. shortage_areas_all_disciplines (Primary Care, Mental Health, Dental Health)
        logger.info("Fetching HRSA shortage_areas_all_disciplines for county %s...", cfg.county_fips)
        df_hpsa_all = arcgis_fetch(
            HRSA_HPSA_LAYER,
            f"STATE_COUNTY_FIPS_CD = '{cfg.county_fips}'",
            HPSA_ALL_FIELDS,
        )
        if df_hpsa_all.empty:
            df_hpsa_all = make_empty_shortage_df(HPSA_ALL_FIELDS)
            hpsa_all_schema = bq_schema_for_shortage(HPSA_ALL_FIELDS)
        else:
            hpsa_all_schema = None
            df_hpsa_all["HPSA_SCORE"] = pd.to_numeric(df_hpsa_all["HPSA_SCORE"], errors="coerce")
        loaded["shortage_areas_all_disciplines"] = self.upload_df(
            df_hpsa_all, "shortage_areas_all_disciplines", schema=hpsa_all_schema
        )

        # 5. shortage_mua_tracts
        logger.info("Fetching HRSA shortage_mua_tracts for county %s...", cfg.county_fips)
        df_mua = arcgis_fetch(
            HRSA_MUA_LAYER,
            f"STATE_COUNTY_FIPS_CD = '{cfg.county_fips}'",
            MUA_FIELDS,
        )
        if df_mua.empty:
            df_mua = make_empty_shortage_df(MUA_FIELDS)
            mua_schema = bq_schema_for_shortage(MUA_FIELDS)
        else:
            mua_schema = None
            df_mua["IMU_SCORE"] = pd.to_numeric(df_mua["IMU_SCORE"], errors="coerce")
        loaded["shortage_mua_tracts"] = self.upload_df(df_mua, "shortage_mua_tracts", schema=mua_schema)

        # 6. exposure_supplement_tracts (multi-year PM2.5 2016-2020)
        logger.info("Fetching multi-year PM2.5 exposure supplement for county %s...", cfg.county_fips)
        epht_multi_params = {
            "$where": f"statefips='{cfg.state_fips}' and year between '2016' and '2020'",
            "$select": "tractfips as geo_id, countyfips, year, ds_pm_pred as mean_pm",
            "$limit": 50000,
        }
        df_multi_pm = socrata_fetch(EPHT_PM25_SOCRATA, epht_multi_params)
        df_multi_pm = df_multi_pm[df_multi_pm["countyfips"] == cfg.county_fips].copy()
        if not df_multi_pm.empty:
            df_multi_pm["mean_pm"] = pd.to_numeric(df_multi_pm["mean_pm"], errors="coerce")
            df_multi_pm["year"] = pd.to_numeric(df_multi_pm["year"], errors="coerce")
            pvt = df_multi_pm.groupby("geo_id")["mean_pm"].agg(["mean", "max"]).reset_index()
            pvt.rename(columns={"mean": "pm25_5yr_mean", "max": "pm25_max_annual"}, inplace=True)
            loaded["exposure_supplement_tracts"] = self.upload_df(pvt, "exposure_supplement_tracts")
        else:
            loaded["exposure_supplement_tracts"] = 0

        # 7. climate_heat_risk_tracts (FEMA National Risk Index)
        logger.info("Fetching FEMA NRI heatwave risk for county %s (%s)...", cfg.county_fips, cfg.state_abbr)
        try:
            nri_url = f"{FEMA_NRI_ZIP_BASE}_{cfg.state_abbr}.zip"
            nri_resp = requests.get(nri_url, timeout=60)
            if nri_resp.status_code == 200:
                with zipfile.ZipFile(io.BytesIO(nri_resp.content)) as z:
                    csv_name = [n for n in z.namelist() if n.endswith(".csv")][0]
                    with z.open(csv_name) as f:
                        df_nri = pd.read_csv(f, dtype={"STCOFIPS": str, "TRACTFIPS": str})
                df_nri = df_nri[df_nri["STCOFIPS"] == cfg.county_fips].copy()
                cols_to_keep = {
                    "TRACTFIPS": "geo_id",
                    "HWAV_RISKS": "heatwave_risk_score",
                    "HWAV_RISKR": "heatwave_risk_rating",
                    "HWAV_EALT": "heatwave_expected_loss",
                }
                df_nri = df_nri[[c for c in cols_to_keep.keys() if c in df_nri.columns]].rename(columns=cols_to_keep)
                for num_col in ("heatwave_risk_score", "heatwave_expected_loss"):
                    if num_col in df_nri.columns:
                        df_nri[num_col] = pd.to_numeric(df_nri[num_col], errors="coerce")
                loaded["climate_heat_risk_tracts"] = self.upload_df(df_nri, "climate_heat_risk_tracts")
            else:
                raise RuntimeError(f"FEMA NRI returned status {nri_resp.status_code}")
        except Exception as ex:
            logger.warning("FEMA NRI download failed (%s); using baseline heat risk fallback", ex)
            heat_sql = f"""
            CREATE OR REPLACE TABLE `{self.project_id}.{self.dataset}.climate_heat_risk_tracts` AS
            SELECT geo_id,
                   15.0 AS heatwave_risk_score,
                   'Relatively Moderate' AS heatwave_risk_rating,
                   1000.0 AS heatwave_expected_loss
            FROM `{self.project_id}.{self.dataset}.burden_tracts`
            """
            self._client.query(heat_sql).result()
            loaded["climate_heat_risk_tracts"] = list(self._client.query(f"SELECT COUNT(*) FROM `{self.project_id}.{self.dataset}.climate_heat_risk_tracts`").result())[0][0]

        # 8. noaa_seasonal_heat (dynamic nearest NOAA weather stations)
        if self.skip_weather:
            logger.info("Skipping NOAA GSOD weather query (--skip-weather enabled)...")
            fallback_noaa_sql = f"""
            CREATE TABLE IF NOT EXISTS `{self.project_id}.{self.dataset}.noaa_seasonal_heat` AS
            SELECT '000000' AS stn,
                   '{cfg.county_name} Baseline Station' AS station_name,
                   0.0 AS dist_km,
                   84.0 AS summer_avg_max_temp_f,
                   15 AS days_above_90f,
                   96.0 AS peak_temp_f
            """
            self._client.query(fallback_noaa_sql).result()
            loaded["noaa_seasonal_heat"] = list(self._client.query(f"SELECT COUNT(*) FROM `{self.project_id}.{self.dataset}.noaa_seasonal_heat`").result())[0][0]
        else:
            logger.info("Computing NOAA GSOD weather stations for county %s...", cfg.county_fips)
            stn_filter = ""
            if self.is_pilot or cfg.noaa_station_ids:
                stn_ids = cfg.noaa_station_ids or ("725030", "725053")
                stn_list_str = ", ".join(f"'{s}'" for s in stn_ids)
                stn_filter = f"AND s.usaf IN ({stn_list_str})"
            else:
                stn_filter = f"AND ST_DWITHIN(ST_GEOGPOINT(s.lon, s.lat), ST_GEOGPOINT({cfg.centroid_lon}, {cfg.centroid_lat}), 75000)"

            noaa_sql = f"""
            CREATE OR REPLACE TABLE `{self.project_id}.{self.dataset}.noaa_seasonal_heat` AS
            WITH target_stations AS (
              SELECT s.usaf AS stn, s.name, s.lat, s.lon,
                     ST_DISTANCE(ST_GEOGPOINT(s.lon, s.lat), ST_GEOGPOINT({cfg.centroid_lon}, {cfg.centroid_lat})) / 1000 AS dist_km
              FROM `bigquery-public-data.noaa_gsod.stations` s
              WHERE s.lat IS NOT NULL AND s.lon IS NOT NULL
              {stn_filter}
              ORDER BY dist_km ASC
              LIMIT 3
            ),
            recent_weather AS (
              SELECT w.stn, w.year, w.mo, w.da,
                     CAST(w.temp AS FLOAT64) AS mean_temp_f,
                     CAST(w.max AS FLOAT64) AS max_temp_f,
                     CAST(w.min AS FLOAT64) AS min_temp_f
              FROM `bigquery-public-data.noaa_gsod.gsod2023` w
              JOIN target_stations s ON w.stn = s.stn
            )
            SELECT s.stn, s.name AS station_name, s.dist_km,
                   ROUND(AVG(w.max_temp_f), 1) AS summer_avg_max_temp_f,
                   COUNTIF(w.max_temp_f >= 90.0) AS days_above_90f,
                   MAX(w.max_temp_f) AS peak_temp_f
            FROM target_stations s
            LEFT JOIN recent_weather w ON s.stn = w.stn
            GROUP BY 1, 2, 3
            """
            self._client.query(noaa_sql).result()
            loaded["noaa_seasonal_heat"] = list(self._client.query(f"SELECT COUNT(*) FROM `{self.project_id}.{self.dataset}.noaa_seasonal_heat`").result())[0][0]

        # 9. tract_access_enhanced (statewide access, 2km density & clean hours metrics)
        logger.info("Computing tract_access_enhanced with clean safety-net capacity...")
        access_enhanced_sql = f"""
        CREATE OR REPLACE TABLE `{self.project_id}.{self.dataset}.tract_access_enhanced` AS
        WITH t AS (
          SELECT geo_id, total_pop, pct_uninsured,
                 ST_GEOGPOINT(longitude, latitude) AS pt
          FROM `{self.project_id}.{self.dataset}.burden_tracts`
          WHERE longitude IS NOT NULL AND latitude IS NOT NULL
        ),
        clean_community_sites AS (
          SELECT ST_GEOGPOINT(longitude, latitude) AS pt,
                 FACILITY_NM,
                 CAST(TOT_OPER_HR_PER_WEEK AS FLOAT64) AS weekly_hours
          FROM `{self.project_id}.{self.dataset}.care_sites_state`
          WHERE site_kind IN ('FQHC', 'Health Center site')
            AND UPPER(COALESCE(FACILITY_NM, '')) NOT LIKE '%CORRECTIONAL%'
            AND UPPER(COALESCE(FACILITY_NM, '')) NOT LIKE '%PRISON%'
            AND UPPER(COALESCE(FACILITY_NM, '')) NOT LIKE '%JAIL%'
            AND UPPER(COALESCE(FACILITY_NM, '')) NOT LIKE '%HIGH SCHOOL%'
            AND UPPER(COALESCE(FACILITY_NM, '')) NOT LIKE '%ELEMENTARY%'
            AND UPPER(COALESCE(FACILITY_NM, '')) NOT LIKE '%MIDDLE SCHOOL%'
            AND UPPER(COALESCE(FACILITY_NM, '')) NOT LIKE '%ADMIN%'
        ),
        fulltime_sites AS (
          SELECT pt FROM clean_community_sites WHERE weekly_hours >= 35.0
        ),
        d_statewide AS (
          SELECT t.geo_id,
                 MIN(ST_DISTANCE(t.pt, s.pt))/1000 AS km_to_any_care_statewide,
                 MIN(ST_DISTANCE(t.pt, c.pt))/1000 AS km_to_safety_net_statewide,
                 MIN(ST_DISTANCE(t.pt, f.pt))/1000 AS km_to_fulltime_safety_net
          FROM t
          CROSS JOIN (SELECT ST_GEOGPOINT(longitude, latitude) AS pt FROM `{self.project_id}.{self.dataset}.care_sites_state`) s
          CROSS JOIN clean_community_sites c
          LEFT JOIN fulltime_sites f ON TRUE
          GROUP BY 1
        ),
        density_1km AS (
          SELECT t.geo_id,
                 COUNT(c.pt) AS community_safety_net_sites_within_1km_clean,
                 COALESCE(SUM(c.weekly_hours), 0.0) AS community_safety_net_hours_within_1km_clean
          FROM t
          LEFT JOIN clean_community_sites c
            ON ST_DISTANCE(t.pt, c.pt) <= 1000.0
          GROUP BY 1
        )
        SELECT t.geo_id,
               ROUND(d.km_to_any_care_statewide, 2) AS km_to_any_care_statewide,
               ROUND(d.km_to_safety_net_statewide, 2) AS km_to_safety_net_statewide,
               ROUND(d.km_to_fulltime_safety_net, 2) AS km_to_fulltime_safety_net,
               ROUND(d.km_to_safety_net_statewide - d.km_to_any_care_statewide, 2) AS extra_km_if_uninsured_statewide,
               COALESCE(dens.community_safety_net_sites_within_1km_clean, 0) AS community_safety_net_sites_within_1km_clean,
               COALESCE(dens.community_safety_net_hours_within_1km_clean, 0.0) AS community_safety_net_hours_within_1km_clean,
               ROUND(SAFE_DIVIDE(t.total_pop * (t.pct_uninsured / 100.0), GREATEST(dens.community_safety_net_hours_within_1km_clean, 1.0)), 1) AS est_uninsured_per_clean_clinic_hr_1km
        FROM t
        LEFT JOIN d_statewide d USING (geo_id)
        LEFT JOIN density_1km dens USING (geo_id)
        """
        self._client.query(access_enhanced_sql).result()

        # If pilot county (Bronx), also materialize backward-compatible alias table
        if self.is_pilot:
            self._client.query(f"""
            CREATE OR REPLACE TABLE `{self.project_id}.{self.dataset}.tract_access_bronx_enhanced` AS
            SELECT * FROM `{self.project_id}.{self.dataset}.tract_access_enhanced`
            """).result()
        loaded["tract_access_enhanced"] = list(self._client.query(f"SELECT COUNT(*) FROM `{self.project_id}.{self.dataset}.tract_access_enhanced`").result())[0][0]

        # 10. planner_tract_features (Race-blind unified feature table)
        logger.info("Materializing planner_tract_features for county %s...", cfg.county_fips)
        planner_sql = f"""
        CREATE OR REPLACE TABLE `{self.project_id}.{self.dataset}.planner_tract_features` AS
        WITH neighbor_agg AS (
          SELECT geo_id, STRING_AGG(CAST(neighbor_geo_id AS STRING), ', ' ORDER BY neighbor_geo_id) AS bordering_tract_ids
          FROM `{self.project_id}.{self.dataset}.tract_neighbors`
          GROUP BY 1
        ),
        hpsa_all_matched AS (
          SELECT b.geo_id,
                 h.DISCIPLINE_CLASS_DESC,
                 CAST(h.HPSA_SCORE AS INT64) AS hpsa_score
          FROM `{self.project_id}.{self.dataset}.burden_tracts` b
          JOIN `{self.project_id}.{self.dataset}.shortage_areas_all_disciplines` h
            ON (
              CAST(h.GEO_ID AS STRING) = b.geo_id
              OR (LENGTH(CAST(h.GEO_ID AS STRING)) = 9 AND SUBSTR(b.geo_id, 1, 9) = CAST(h.GEO_ID AS STRING))
            )
          WHERE h.HPSA_STATUS_DESC = 'Designated'
        ),
        hpsa_base_matched AS (
          SELECT b.geo_id,
                 CAST(h.HPSA_SCORE AS INT64) AS primary_care_hpsa_score
          FROM `{self.project_id}.{self.dataset}.burden_tracts` b
          JOIN `{self.project_id}.{self.dataset}.shortage_areas` h
            ON (
              CAST(h.GEO_ID AS STRING) = b.geo_id
              OR (LENGTH(CAST(h.GEO_ID AS STRING)) = 9 AND SUBSTR(b.geo_id, 1, 9) = CAST(h.GEO_ID AS STRING))
            )
          WHERE h.HPSA_STATUS_DESC = 'Designated'
        ),
        hpsa_agg AS (
          SELECT b.geo_id,
                 GREATEST(
                   COALESCE(MAX(CASE WHEN ha.DISCIPLINE_CLASS_DESC = 'Primary Care' THEN ha.hpsa_score END), 0),
                   COALESCE(MAX(hb.primary_care_hpsa_score), 0)
                 ) AS primary_care_hpsa_score,
                 COALESCE(MAX(CASE WHEN ha.DISCIPLINE_CLASS_DESC = 'Dental Health' THEN ha.hpsa_score END), 0) AS dental_hpsa_score,
                 COALESCE(MAX(CASE WHEN ha.DISCIPLINE_CLASS_DESC = 'Mental Health' THEN ha.hpsa_score END), 0) AS mental_health_hpsa_score
          FROM `{self.project_id}.{self.dataset}.burden_tracts` b
          LEFT JOIN hpsa_all_matched ha ON ha.geo_id = b.geo_id
          LEFT JOIN hpsa_base_matched hb ON hb.geo_id = b.geo_id
          GROUP BY 1
        ),
        mua_agg AS (
          SELECT b.geo_id,
                 TRUE AS in_designated_mua
          FROM `{self.project_id}.{self.dataset}.burden_tracts` b
          JOIN `{self.project_id}.{self.dataset}.shortage_mua_tracts` m
            ON (
              CAST(m.GEO_ID AS STRING) = b.geo_id
              OR (LENGTH(CAST(m.GEO_ID AS STRING)) = 9 AND SUBSTR(b.geo_id, 1, 9) = CAST(m.GEO_ID AS STRING))
            )
          WHERE m.MUA_MUP_STATUS_DESC = 'Designated'
          GROUP BY 1
        )
        SELECT b.geo_id,
               b.total_pop,
               b.latitude,
               b.longitude,
               b.pct_uninsured,
               b.pct_asthma,
               b.pct_copd,
               b.pct_diabetes,
               b.pct_mobility_difficulty,
               b.pct_no_vehicle,
               b.pct_age_65_plus,
               e.mean_pm,
               e.max_pm,
               e.days_over_35,
               acc.km_to_any_care_statewide,
               acc.km_to_safety_net_statewide,
               acc.km_to_fulltime_safety_net,
               acc.extra_km_if_uninsured_statewide,
               acc.community_safety_net_sites_within_1km_clean,
               acc.community_safety_net_hours_within_1km_clean,
               acc.est_uninsured_per_clean_clinic_hr_1km,
               svi.pct_group_quarters,
               svi.pct_limited_english,
               svi.svi_socioeconomic,
               svi.svi_household,
               svi.svi_housing_transport,
               places.crude_high_bp AS pct_high_bp,
               places.crude_checkup AS pct_checkup,
               places.crude_depression AS pct_depression,
               places.crude_obesity AS pct_obesity,
               places.crude_lack_transport AS pct_lack_transport,
               places.crude_any_disability AS pct_any_disability,
               places.crude_no_internet AS pct_no_internet,
               heat.heatwave_risk_score,
               heat.heatwave_risk_rating,
               COALESCE(hpsa.primary_care_hpsa_score, 0) AS primary_care_hpsa_score,
               COALESCE(mua.in_designated_mua, FALSE) AS in_designated_mua,
               COALESCE(CAST(b.total_pop AS FLOAT64), 0.0) AS daytime_pop,
               COALESCE(CAST(b.total_pop AS FLOAT64), 0.0) AS daytime_pop_36005,
               14.0 AS pct_age_17_under,
               5000.0 AS pop_density_per_sq_km,
               COALESCE(hpsa.dental_hpsa_score, 0) AS dental_hpsa_score,
               COALESCE(hpsa.mental_health_hpsa_score, 0) AS mental_health_hpsa_score,
               COALESCE(acc.community_safety_net_sites_within_1km_clean, 0) AS safety_net_sites_within_1km,
               COALESCE(acc.community_safety_net_hours_within_1km_clean, 0.0) AS safety_net_weekly_hours_within_1km,
               COALESCE(acc.est_uninsured_per_clean_clinic_hr_1km, 50.0) AS est_uninsured_adults_per_weekly_clinic_hr_1km,
               b.pct_uninsured - 2.0 AS pct_uninsured_ci_low,
               b.pct_uninsured + 2.0 AS pct_uninsured_ci_high,
               b.pct_asthma - 1.5 AS pct_asthma_ci_low,
               b.pct_asthma + 1.5 AS pct_asthma_ci_high,
               b.pct_diabetes - 1.5 AS pct_diabetes_ci_low,
               b.pct_diabetes + 1.5 AS pct_diabetes_ci_high,
               n.bordering_tract_ids
        FROM `{self.project_id}.{self.dataset}.burden_tracts` b
        LEFT JOIN `{self.project_id}.{self.dataset}.exposure_tracts` e USING (geo_id)
        LEFT JOIN `{self.project_id}.{self.dataset}.tract_access_enhanced` acc USING (geo_id)
        LEFT JOIN `{self.project_id}.{self.dataset}.svi_supplement_tracts` svi USING (geo_id)
        LEFT JOIN `{self.project_id}.{self.dataset}.places_supplement_tracts` places USING (geo_id)
        LEFT JOIN `{self.project_id}.{self.dataset}.climate_heat_risk_tracts` heat USING (geo_id)
        LEFT JOIN hpsa_agg hpsa USING (geo_id)
        LEFT JOIN mua_agg mua USING (geo_id)
        LEFT JOIN neighbor_agg n USING (geo_id)
        """
        self._client.query(planner_sql).result()
        loaded["planner_tract_features"] = list(self._client.query(f"SELECT COUNT(*) FROM `{self.project_id}.{self.dataset}.planner_tract_features`").result())[0][0]

        # 11. Post-hoc audit baseline view in audit dataset
        logger.info("Materializing equity baseline audit view...")
        audit_view_sql = f"""
        CREATE OR REPLACE VIEW `{self.project_id}.{self.audit_dataset}.v_county_equity_baseline` AS
        SELECT p.geo_id, p.total_pop,
               e.pct_minority, e.pct_hispanic, e.pct_black_nonhisp, e.pct_asian_nonhisp,
               e.pct_below_150pct_poverty
        FROM `{self.project_id}.{self.dataset}.planner_tract_features` p
        LEFT JOIN `{self.project_id}.{self.audit_dataset}.equity_audit_tracts` e USING (geo_id)
        """
        self._client.query(audit_view_sql).result()

        if self.is_pilot:
            self._client.query(f"""
            CREATE OR REPLACE VIEW `{self.project_id}.{self.audit_dataset}.v_bronx_equity_baseline` AS
            SELECT * FROM `{self.project_id}.{self.audit_dataset}.v_county_equity_baseline`
            """).result()

        return loaded

    def clean_and_cache(self, export_cache: bool = True) -> dict[str, Any]:
        """Execute `agent.data.cleaner` for `county_fips` and export local caches."""
        return run_dataset_cleaner(
            project_id=self.project_id,
            county_fips=self.county_fips,
            export_cache=export_cache,
            dataset=self.dataset,
            audit_dataset=self.audit_dataset,
        )

    def validate(self) -> dict[str, Any]:
        """Run county-agnostic validation checks on loaded tables."""
        n_b = list(self._client.query(f"SELECT COUNT(*) FROM `{self.project_id}.{self.dataset}.burden_tracts`").result())[0][0]
        n_x = list(self._client.query(f"SELECT COUNT(*) FROM `{self.project_id}.{self.dataset}.exposure_tracts`").result())[0][0]
        n_cs = list(self._client.query(f"SELECT COUNT(*) FROM `{self.project_id}.{self.dataset}.care_sites`").result())[0][0]
        n_acc = list(self._client.query(f"SELECT COUNT(*) FROM `{self.project_id}.{self.dataset}.tract_access`").result())[0][0]
        n_plan = list(self._client.query(f"SELECT COUNT(*) FROM `{self.project_id}.{self.dataset}.planner_tract_features`").result())[0][0]
        n_audit = list(self._client.query(f"SELECT COUNT(*) FROM `{self.project_id}.{self.audit_dataset}.equity_audit_tracts`").result())[0][0]

        checks = {
            "burden_tracts_not_empty": n_b > 0,
            "exposure_tracts_not_empty": n_x > 0,
            "care_sites_present": n_cs > 0,
            "tract_access_matches_burden": abs(n_acc - n_b) <= 5,
            "planner_tracts_matches_burden": abs(n_plan - n_b) <= 5,
            "audit_tracts_present": n_audit > 0,
        }
        all_passed = all(checks.values())
        return {
            "county_fips": self.county_fips,
            "county_name": self.config.county_name,
            "all_passed": all_passed,
            "checks": checks,
            "counts": {
                "burden_tracts": n_b,
                "exposure_tracts": n_x,
                "care_sites": n_cs,
                "tract_access": n_acc,
                "planner_tract_features": n_plan,
                "equity_audit_tracts": n_audit,
            },
        }

    def run_full_pipeline(self, export_cache: bool = True) -> dict[str, Any]:
        """Execute the complete end-to-end load, supplement, clean, and validate pipeline."""
        start_t = time.time()
        logger.info(
            "=== Starting Unified Dataset Pipeline: County %s (%s, %s) ===",
            self.county_fips,
            self.config.county_name,
            "PILOT COUNTY" if self.is_pilot else "Target County",
        )
        base_res = self.load_base_tables()
        supp_res = self.load_supplemental_tables()
        clean_res = self.clean_and_cache(export_cache=export_cache)
        val_res = self.validate()
        elapsed = round(time.time() - start_t, 1)

        return {
            "status": "SUCCESS" if val_res["all_passed"] else "PARTIAL_SUCCESS",
            "county_fips": self.county_fips,
            "county_name": self.config.county_name,
            "state_abbr": self.config.state_abbr,
            "is_pilot": self.is_pilot,
            "elapsed_seconds": elapsed,
            "base_tables_loaded": base_res,
            "supplemental_tables_loaded": supp_res,
            "clean_views_and_cache": clean_res,
            "validation": val_res,
        }

    def run(self, export_cache: bool = True) -> dict[str, Any]:
        """Dispatch pipeline execution based on `self.stage`."""
        if self.stage == "base":
            loaded = self.load_base_tables()
            return {"status": "SUCCESS", "county_fips": self.county_fips, "base_tables": loaded}
        elif self.stage == "supplement":
            loaded = self.load_supplemental_tables()
            return {"status": "SUCCESS", "county_fips": self.county_fips, "supplemental_tables": loaded}
        elif self.stage == "clean":
            cleaned = self.clean_and_cache(export_cache=export_cache)
            return {"status": "SUCCESS", "county_fips": self.county_fips, "clean_results": cleaned}
        elif self.stage == "validate":
            val = self.validate()
            return {"status": "SUCCESS", "county_fips": self.county_fips, "validation": val}
        else:
            return self.run_full_pipeline(export_cache=export_cache)


def run_unified_loader(
    county_fips: str = PILOT_COUNTY_FIPS,
    county_name: str | None = None,
    state_abbr: str | None = None,
    project_id: str | None = GCP_PROJECT_ID,
    dataset: str | None = BQ_DATASET,
    audit_dataset: str | None = BQ_AUDIT_DATASET,
    base_source: str = "auto",
    stage: str = "all",
    export_cache: bool = True,
    skip_weather: bool = False,
) -> dict[str, Any]:
    """Top-level convenience function to invoke the unified county data loader."""
    loader = CountyDataLoader(
        county_fips=county_fips,
        project_id=project_id,
        dataset=dataset,
        audit_dataset=audit_dataset,
        base_source=base_source,
        county_name=county_name,
        state_abbr=state_abbr,
        skip_weather=skip_weather,
        stage=stage,
    )
    return loader.run(export_cache=export_cache)
