"""Central county-agnostic configuration for the Public Health Mobile Care Broker.

Bronx County, NY (FIPS 36005) is configured as the default pilot county (`PILOT_COUNTY_FIPS = "36005"`),
while supporting any US county via `COUNTY_FIPS` environment variable, CLI flags, or `get_county_config()`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Repository paths
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# GCP & BigQuery configuration
GCP_PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "qwiklabs-gcp-03-c81d344a3430")
BQ_LOCATION = os.environ.get("BQ_LOCATION", "US")
BQ_DATASET = os.environ.get("BQ_DATASET", "a4i_health")
BQ_AUDIT_DATASET = os.environ.get("BQ_AUDIT_DATASET", "a4i_health_audit")

# Pre-staged GCS bucket for Challenge 5 fast-path base table snapshots
GCS_CHALLENGE_BUCKET = os.environ.get(
    "GCS_CHALLENGE_BUCKET",
    "gs://class-demo/a4i-2026/challenge-5-public-health",
)

# Pilot Jurisdiction Constant (Bronx County, NY)
PILOT_COUNTY_FIPS = "36005"

# 2-digit State FIPS to USPS State Abbreviation lookup (all 50 states + DC + territories)
STATE_FIPS_TO_ABBR: dict[str, str] = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA",
    "08": "CO", "09": "CT", "10": "DE", "11": "DC", "12": "FL",
    "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN",
    "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME",
    "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS",
    "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND",
    "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI",
    "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
    "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI",
    "56": "WY", "60": "AS", "66": "GU", "69": "MP", "72": "PR",
    "78": "VI",
}


@dataclass(frozen=True)
class CountyConfig:
    """Configuration metadata for a target US county."""

    county_fips: str
    county_name: str
    state_abbr: str
    centroid_lat: float
    centroid_lon: float
    default_zoom: float = 11.5
    is_pilot: bool = False
    pre_staged_gcs: bool = False
    noaa_station_ids: tuple[str, ...] = ()
    transit_agency: str = "Local Public Transit"
    health_dept_name: str = "County Department of Public Health"
    jurisdiction_label: str = "County"

    @property
    def county_fips_int(self) -> int:
        return int(self.county_fips)

    @property
    def state_fips(self) -> str:
        return self.county_fips[:2]

    @property
    def county_code_3(self) -> str:
        return self.county_fips[2:]

    @property
    def short_name(self) -> str:
        """Short label without 'County, ST' suffix (e.g., 'Bronx', 'Fulton', 'Cook')."""
        base = self.county_name.split(",")[0].strip()
        if base.endswith(" County"):
            return base[: -len(" County")].strip()
        return base


# Registry of Challenge 5 pre-staged counties + regional neighbors, with Bronx (36005) as Pilot
KNOWN_COUNTIES: dict[str, CountyConfig] = {
    "36005": CountyConfig(
        county_fips="36005",
        county_name="Bronx County, NY",
        state_abbr="NY",
        centroid_lat=40.8448,
        centroid_lon=-73.8648,
        default_zoom=12.0,
        is_pilot=True,
        pre_staged_gcs=True,
        noaa_station_ids=("725030", "725053"),  # LaGuardia & Central Park
        transit_agency="MTA Subway / Bx Bus",
        health_dept_name="NYC DOHMH / Bronx Health Equity Bureau",
        jurisdiction_label="Borough",
    ),
    "13121": CountyConfig(
        county_fips="13121",
        county_name="Fulton County, GA",
        state_abbr="GA",
        centroid_lat=33.7902,
        centroid_lon=-84.4670,
        default_zoom=10.5,
        is_pilot=False,
        pre_staged_gcs=True,
        noaa_station_ids=("722190", "722195"),  # Atlanta Hartsfield-Jackson & Fulton Co Airport
        transit_agency="MARTA Rail / Bus",
        health_dept_name="Fulton County Board of Health",
        jurisdiction_label="County",
    ),
    "17031": CountyConfig(
        county_fips="17031",
        county_name="Cook County, IL",
        state_abbr="IL",
        centroid_lat=41.8376,
        centroid_lon=-87.6866,
        default_zoom=10.0,
        is_pilot=False,
        pre_staged_gcs=True,
        noaa_station_ids=("725300", "725340"),  # Chicago O'Hare & Midway
        transit_agency="CTA 'L' / Pace Bus",
        health_dept_name="Cook County Dept of Public Health / CDPH",
        jurisdiction_label="County",
    ),
    "06085": CountyConfig(
        county_fips="06085",
        county_name="Santa Clara County, CA",
        state_abbr="CA",
        centroid_lat=37.2310,
        centroid_lon=-121.6970,
        default_zoom=10.2,
        is_pilot=False,
        pre_staged_gcs=True,
        noaa_station_ids=("724945", "745090"),  # San Jose Intl & Moffett Federal Airfield
        transit_agency="VTA Light Rail / Bus",
        health_dept_name="Santa Clara County Public Health Department",
        jurisdiction_label="County",
    ),
    "48201": CountyConfig(
        county_fips="48201",
        county_name="Harris County, TX",
        state_abbr="TX",
        centroid_lat=29.8570,
        centroid_lon=-95.3936,
        default_zoom=9.8,
        is_pilot=False,
        pre_staged_gcs=True,
        noaa_station_ids=("722430", "722440"),  # George Bush Intercontinental & Hobby
        transit_agency="METRO Rail / Bus",
        health_dept_name="Harris County Public Health",
        jurisdiction_label="County",
    ),
    "48453": CountyConfig(
        county_fips="48453",
        county_name="Travis County, TX",
        state_abbr="TX",
        centroid_lat=30.3347,
        centroid_lon=-97.7819,
        default_zoom=10.5,
        is_pilot=False,
        pre_staged_gcs=True,
        noaa_station_ids=("722540", "722544"),  # Austin-Bergstrom & Camp Mabry
        transit_agency="CapMetro Rail / Bus",
        health_dept_name="Austin Public Health",
        jurisdiction_label="County",
    ),
    # Additional NYC / Regional Counties for seamless expansion
    "36061": CountyConfig(
        county_fips="36061",
        county_name="New York County, NY",
        state_abbr="NY",
        centroid_lat=40.7831,
        centroid_lon=-73.9712,
        default_zoom=12.0,
        noaa_station_ids=("725053", "725030"),
        transit_agency="MTA Subway / M Bus",
        health_dept_name="NYC DOHMH",
        jurisdiction_label="Borough",
    ),
    "36047": CountyConfig(
        county_fips="36047",
        county_name="Kings County, NY",
        state_abbr="NY",
        centroid_lat=40.6501,
        centroid_lon=-73.9496,
        default_zoom=11.5,
        noaa_station_ids=("744860", "725053"),
        transit_agency="MTA Subway / B Bus",
        health_dept_name="NYC DOHMH",
        jurisdiction_label="Borough",
    ),
    "36081": CountyConfig(
        county_fips="36081",
        county_name="Queens County, NY",
        state_abbr="NY",
        centroid_lat=40.7282,
        centroid_lon=-73.7949,
        default_zoom=11.2,
        noaa_station_ids=("725030", "744860"),
        transit_agency="MTA Subway / Q Bus",
        health_dept_name="NYC DOHMH",
        jurisdiction_label="Borough",
    ),
    "36085": CountyConfig(
        county_fips="36085",
        county_name="Richmond County, NY",
        state_abbr="NY",
        centroid_lat=40.5795,
        centroid_lon=-74.1502,
        default_zoom=11.5,
        noaa_station_ids=("725020", "725053"),
        transit_agency="SIR / MTA S Bus",
        health_dept_name="NYC DOHMH",
        jurisdiction_label="Borough",
    ),
    "36119": CountyConfig(
        county_fips="36119",
        county_name="Westchester County, NY",
        state_abbr="NY",
        centroid_lat=41.1220,
        centroid_lon=-73.7949,
        default_zoom=10.5,
        noaa_station_ids=("725037", "725030"),
        transit_agency="Bee-Line Bus / Metro-North",
        health_dept_name="Westchester County Department of Health",
        jurisdiction_label="County",
    ),
}

PRE_STAGED_COUNTY_FIPS: tuple[str, ...] = tuple(
    fips for fips, cfg in KNOWN_COUNTIES.items() if cfg.pre_staged_gcs
)


def normalize_county_fips(county_fips: str | int | None = None) -> str:
    """Normalize a county FIPS input into a zero-padded 5-character string."""
    if county_fips is None or str(county_fips).strip() == "":
        return PILOT_COUNTY_FIPS
    cleaned = str(county_fips).strip().zfill(5)
    if len(cleaned) != 5 or not cleaned.isdigit():
        raise ValueError(
            f"Invalid COUNTY_FIPS '{county_fips}': must be a 5-digit US county FIPS code (e.g., '36005')."
        )
    return cleaned


def get_county_config(
    county_fips: str | int | None = None,
    county_name: str | None = None,
    state_abbr: str | None = None,
    centroid_lat: float | None = None,
    centroid_lon: float | None = None,
) -> CountyConfig:
    """Resolve `CountyConfig` for any US county, defaulting to the Bronx pilot (`36005`)."""
    fips = normalize_county_fips(county_fips)
    base = KNOWN_COUNTIES.get(fips)
    inferred_state = (state_abbr or (base.state_abbr if base else STATE_FIPS_TO_ABBR.get(fips[:2], "US"))).upper()
    inferred_name = county_name or (base.county_name if base else f"County FIPS {fips}, {inferred_state}")

    if base is not None:
        return CountyConfig(
            county_fips=fips,
            county_name=inferred_name,
            state_abbr=inferred_state,
            centroid_lat=centroid_lat if centroid_lat is not None else base.centroid_lat,
            centroid_lon=centroid_lon if centroid_lon is not None else base.centroid_lon,
            default_zoom=base.default_zoom,
            is_pilot=base.is_pilot,
            pre_staged_gcs=base.pre_staged_gcs,
            noaa_station_ids=base.noaa_station_ids,
            transit_agency=base.transit_agency,
            health_dept_name=base.health_dept_name,
            jurisdiction_label=base.jurisdiction_label,
        )

    return CountyConfig(
        county_fips=fips,
        county_name=inferred_name,
        state_abbr=inferred_state,
        centroid_lat=centroid_lat if centroid_lat is not None else 39.8283,
        centroid_lon=centroid_lon if centroid_lon is not None else -98.5795,
        default_zoom=10.5,
        is_pilot=(fips == PILOT_COUNTY_FIPS),
        pre_staged_gcs=False,
        noaa_station_ids=(),
        transit_agency="Local Public Transit",
        health_dept_name=f"{inferred_name.split(',')[0].strip()} Health Department",
        jurisdiction_label="County",
    )


# Active Target Jurisdiction (defaults to Pilot County: Bronx County, NY - 36005)
COUNTY_FIPS = normalize_county_fips(os.environ.get("COUNTY_FIPS", PILOT_COUNTY_FIPS))
COUNTY_CONFIG = get_county_config(
    COUNTY_FIPS,
    county_name=os.environ.get("COUNTY_NAME") or None,
    state_abbr=os.environ.get("STATE_ABBR") or None,
)
COUNTY_FIPS_INT = COUNTY_CONFIG.county_fips_int
COUNTY_NAME = COUNTY_CONFIG.county_name
STATE_ABBR = COUNTY_CONFIG.state_abbr
IS_PILOT_COUNTY = COUNTY_CONFIG.is_pilot

# Cleaned BigQuery Views / Tables created by Dataset Cleaner
# County-agnostic view names + backward-compatible Bronx aliases
CLEAN_TRACTS_GENERIC_VIEW = f"{GCP_PROJECT_ID}.{BQ_DATASET}.v_clean_tracts"
CLEAN_TRACTS_VIEW = f"{GCP_PROJECT_ID}.{BQ_DATASET}.v_clean_bronx_tracts"
CLEAN_CARE_SITES_VIEW = f"{GCP_PROJECT_ID}.{BQ_DATASET}.v_clean_care_sites"
CLEAN_COUNTY_CONTEXT_VIEW = f"{GCP_PROJECT_ID}.{BQ_DATASET}.v_clean_county_context"
CLEAN_BOROUGH_CONTEXT_VIEW = f"{GCP_PROJECT_ID}.{BQ_DATASET}.v_clean_borough_context"
CLEAN_EQUITY_AUDIT_VIEW = f"{GCP_PROJECT_ID}.{BQ_AUDIT_DATASET}.v_clean_equity_audit"


def get_cache_paths(county_fips: str | int | None = None) -> dict[str, Path]:
    """Return local cache file paths for a given county FIPS.

    For the pilot county (`36005` Bronx), returns the canonical `clean_bronx_tracts.parquet`
    and `bronx_tracts_2020.geojson` paths (while also supporting county-keyed filenames).
    For any other county, namespaces cache artifacts by `county_fips` so switching counties
    never serves stale data from another jurisdiction.
    """
    fips = normalize_county_fips(county_fips or COUNTY_FIPS)
    if fips == PILOT_COUNTY_FIPS:
        return {
            "tracts_parquet": CACHE_DIR / "clean_bronx_tracts.parquet",
            "tracts_county_parquet": CACHE_DIR / f"clean_tracts_{fips}.parquet",
            "care_sites_parquet": CACHE_DIR / "clean_care_sites.parquet",
            "care_sites_county_parquet": CACHE_DIR / f"clean_care_sites_{fips}.parquet",
            "equity_audit_parquet": CACHE_DIR / "clean_equity_audit.parquet",
            "equity_audit_county_parquet": CACHE_DIR / f"clean_equity_audit_{fips}.parquet",
            "context_json": CACHE_DIR / "clean_borough_context.json",
            "context_county_json": CACHE_DIR / f"clean_county_context_{fips}.json",
            "tracts_geojson": CACHE_DIR / "bronx_tracts_2020.geojson",
            "tracts_county_geojson": CACHE_DIR / f"tracts_2020_{fips}.geojson",
        }
    return {
        "tracts_parquet": CACHE_DIR / f"clean_tracts_{fips}.parquet",
        "tracts_county_parquet": CACHE_DIR / f"clean_tracts_{fips}.parquet",
        "care_sites_parquet": CACHE_DIR / f"clean_care_sites_{fips}.parquet",
        "care_sites_county_parquet": CACHE_DIR / f"clean_care_sites_{fips}.parquet",
        "equity_audit_parquet": CACHE_DIR / f"clean_equity_audit_{fips}.parquet",
        "equity_audit_county_parquet": CACHE_DIR / f"clean_equity_audit_{fips}.parquet",
        "context_json": CACHE_DIR / f"clean_county_context_{fips}.json",
        "context_county_json": CACHE_DIR / f"clean_county_context_{fips}.json",
        "tracts_geojson": CACHE_DIR / f"tracts_2020_{fips}.geojson",
        "tracts_county_geojson": CACHE_DIR / f"tracts_2020_{fips}.geojson",
    }


# Default Local Cache Paths (populated by scripts/load_county_data.py or scripts/clean_bronx_data.py)
_DEFAULT_PATHS = get_cache_paths(COUNTY_FIPS)
CACHE_TRACTS_PARQUET = _DEFAULT_PATHS["tracts_parquet"]
CACHE_CARE_SITES_PARQUET = _DEFAULT_PATHS["care_sites_parquet"]
CACHE_EQUITY_AUDIT_PARQUET = _DEFAULT_PATHS["equity_audit_parquet"]
CACHE_COUNTY_CONTEXT_JSON = _DEFAULT_PATHS["context_json"]
CACHE_BOROUGH_CONTEXT_JSON = _DEFAULT_PATHS["context_json"]
CACHE_TRACTS_GEOJSON = _DEFAULT_PATHS["tracts_geojson"]

# GCP Cloud SQL (PostgreSQL 16) Configuration
CLOUD_SQL_INSTANCE_NAME = os.environ.get("CLOUD_SQL_INSTANCE_NAME", "public-health-db")
CLOUD_SQL_CONNECTION_NAME = os.environ.get(
    "CLOUD_SQL_CONNECTION_NAME",
    f"{GCP_PROJECT_ID}:{os.environ.get('CLOUD_SQL_REGION', 'us-central1')}:{CLOUD_SQL_INSTANCE_NAME}",
)
CLOUD_SQL_DB_NAME = os.environ.get("CLOUD_SQL_DB_NAME", "public_health_broker")
CLOUD_SQL_USER = os.environ.get("CLOUD_SQL_USER", "postgres")
CLOUD_SQL_SECRET_NAME = os.environ.get("CLOUD_SQL_SECRET_NAME", "CloudSQLSecret")


def _resolve_cloud_sql_password() -> str:
    """Resolve Cloud SQL password from env var, falling back to Secret Manager."""
    pwd = os.environ.get("CLOUD_SQL_PASSWORD", "")
    if pwd:
        return pwd
    # 1. Attempt lookup via Google Cloud Secret Manager SDK
    try:
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{GCP_PROJECT_ID}/secrets/{CLOUD_SQL_SECRET_NAME}/versions/latest"
        resp = client.access_secret_version(request={"name": name})
        return resp.payload.data.decode("UTF-8").strip()
    except Exception:
        pass
    # 2. Attempt fallback via Secret Manager REST endpoint using default credentials
    try:
        import base64
        import google.auth
        import google.auth.transport.requests
        import requests

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        auth_req = google.auth.transport.requests.Request()
        creds.refresh(auth_req)
        headers = {"Authorization": f"Bearer {creds.token}"}
        url = f"https://secretmanager.googleapis.com/v1/projects/{GCP_PROJECT_ID}/secrets/{CLOUD_SQL_SECRET_NAME}/versions/latest:access"
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            return base64.b64decode(resp.json()["payload"]["data"]).decode("utf-8").strip()
    except Exception:
        pass
    return ""


CLOUD_SQL_PASSWORD = _resolve_cloud_sql_password()
CLOUD_SQL_HOST = os.environ.get("CLOUD_SQL_HOST", "")
CLOUD_SQL_PORT = int(os.environ.get("CLOUD_SQL_PORT", "5432"))

# Direct SQLAlchemy URL override or local SQLite fallback
DATABASE_URL = os.environ.get("DATABASE_URL", "")
LOCAL_SQLITE_PATH = CACHE_DIR / "public_health_broker.db"

# Siting Scoring Weights
# In dense urban counties like the Bronx pilot (where 94% of tracts have 0 extra km if uninsured
# and median distance to care is 0.39 km), physical_distance_km is weighted at 0.00 (Trap 1).
# For counties where HRSA HPSA designations are absent or uninsured distance gaps exist,
# `get_scoring_weights()` provides county-appropriate defaults.
SCORING_WEIGHTS = {
    "hpsa_severity": 0.25,
    "clinic_hours_bottleneck": 0.25,
    "uninsured_rate": 0.20,
    "chronic_disease_burden": 0.20,
    "transit_language_barriers": 0.10,
    "physical_distance_km": 0.00,  # Strictly 0% per Trap 1 guardrail in dense Bronx pilot
}

SCORING_WEIGHTS_DISTANCE_GAP_COUNTY = {
    "hpsa_severity": 0.10,
    "clinic_hours_bottleneck": 0.20,
    "uninsured_rate": 0.20,
    "chronic_disease_burden": 0.20,
    "transit_language_barriers": 0.15,
    "physical_distance_km": 0.15,  # Enabled for counties with physical safety-net distance gaps
}


def get_scoring_weights(county_fips: str | int | None = None, *, has_distance_gap: bool | None = None) -> dict[str, float]:
    """Return scoring weights tailored to the county's spatial access profile.

    - For Bronx pilot (`36005`) or when `has_distance_gap is False`, strictly enforces
      `physical_distance_km = 0.00` (Trap 1 guardrail).
    - For counties with significant physical distance gaps to safety-net care (`has_distance_gap=True`),
      includes `physical_distance_km = 0.15`.
    """
    fips = normalize_county_fips(county_fips or COUNTY_FIPS)
    if fips == PILOT_COUNTY_FIPS or has_distance_gap is False:
        return dict(SCORING_WEIGHTS)
    if has_distance_gap is True:
        return dict(SCORING_WEIGHTS_DISTANCE_GAP_COUNTY)
    return dict(SCORING_WEIGHTS)


# Trap 2 Guardrail Thresholds
MAX_GROUP_QUARTERS_PCT = 25.0
MIN_RESIDENTIAL_POPULATION = 500

# Trap 3 & 4 Environmental & Surveillance Constants
COUNTY_CENTROID_LAT = COUNTY_CONFIG.centroid_lat
COUNTY_CENTROID_LON = COUNTY_CONFIG.centroid_lon
BRONX_CENTROID_LAT = KNOWN_COUNTIES[PILOT_COUNTY_FIPS].centroid_lat
BRONX_CENTROID_LON = KNOWN_COUNTIES[PILOT_COUNTY_FIPS].centroid_lon
PM25_SEASONAL_SPIKE_THRESHOLD = 35.0

