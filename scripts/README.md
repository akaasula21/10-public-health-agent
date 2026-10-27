# scripts/

Headless CLI loaders and dataset cleaning tools for Challenge 5: Dynamic Public Health Equity & Mobile Care Broker.

The pipeline is completely county-agnostic and parameterizable by 5-digit county FIPS, with **Bronx County, NY (`36005`)** configured as the primary choice for the pilot deployment.

---

## 1. Unified County Data Loader (`scripts/load_county_data.py`)

The primary entrypoint is [`scripts/load_county_data.py`](load_county_data.py), backed by [`agent.data.loader.CountyDataLoader`](../agent/data/loader.py). It orchestrates all four pipeline stages:
1. **Base Tables**: 8 core tables (`burden_tracts`, `exposure_tracts`, `tract_access`, `care_sites`, `care_sites_state`, `shortage_areas`, `shortage_facilities`, `disease_weekly`) loaded either from pre-staged GCS snapshots (fast-path for pre-staged counties) or live federal APIs (CDC PLACES, CDC EPHT PM2.5, HRSA ArcGIS, CDC NSSP).
2. **Supplemental Tables**: 10 vetted supplemental tables (`places_supplement_tracts`, `svi_supplement_tracts`, `tract_neighbors`, `shortage_areas_all_disciplines`, `shortage_mua_tracts`, `exposure_supplement_tracts`, `climate_heat_risk_tracts`, `noaa_seasonal_heat`, `tract_access_enhanced`, `planner_tract_features`) plus the restricted equity audit dataset (`a4i_health_audit.equity_audit_tracts`, `v_equity_baseline`).
3. **Data Cleaning & Views**: Materializes production clean views (`v_clean_tracts`, `v_clean_care_sites`, `v_clean_county_context`, and backward-compatible Bronx aliases `v_clean_bronx_tracts`, `v_clean_borough_context`) and exports local offline parquet caches (`data/cache/tracts_<fips>.parquet`).
4. **Validation**: Verifies row counts, column integrity, and enforces strict zero-leakage isolation of racial/ethnic attributes from the planner dataset.

### Usage

```bash
# List all pre-configured counties and pre-staged snapshot FIPS
python scripts/load_county_data.py --list-counties

# Run end-to-end load for Bronx County, NY pilot (default FIPS: 36005)
python scripts/load_county_data.py

# Run for another county using pre-staged snapshot (e.g. Fulton GA: 13121, Cook IL: 17031)
python scripts/load_county_data.py --county-fips 13121

# Run for any other US county using live federal APIs
python scripts/load_county_data.py --county-fips 24510 --county-name "Baltimore City" --state-abbr MD

# Run only specific stages
python scripts/load_county_data.py --stage base
python scripts/load_county_data.py --stage supplement
python scripts/load_county_data.py --stage clean
python scripts/load_county_data.py --stage validate
```

### CLI Options

| Option | Flag | Description | Default |
|---|---|---|---|
| `--county-fips` | `-c` | 5-digit county FIPS code | `36005` (Bronx pilot) |
| `--county-name` | `-n` | County name (optional override) | Resolved from registry |
| `--state-abbr` | `-s` | 2-letter state abbreviation | Resolved from state FIPS |
| `--project` | `-p` | Google Cloud project ID | `GOOGLE_CLOUD_PROJECT` |
| `--dataset` | `-d` | Siting/Planner BigQuery dataset | `a4i_health` |
| `--audit-dataset` | `-a` | Restricted Equity Audit dataset | `a4i_health_audit` |
| `--stage` | | Stage: `all`, `base`, `supplement`, `clean`, `validate` | `all` |
| `--base-source` | | Base load mode: `auto`, `gcs`, `live` | `auto` |
| `--skip-weather` | | Skip NOAA GSOD historical heat extremes | `False` |
| `--no-cache` | | Skip local parquet cache export | `False` |
| `--list-counties` | | Print pre-configured counties table | - |

---

## 2. Shell Loader (`scripts/load.sh`)

Headless bash script loading the 8 core base tables into BigQuery. Updated to default to Bronx County, NY (`36005`):

```bash
bash scripts/load.sh              # loads Bronx County, NY (36005) pilot
bash scripts/load.sh 13121        # Fulton County, GA
bash scripts/load.sh 17031        # Cook County, IL
bash scripts/load.sh --list       # show every pre-staged county snapshot
bash scripts/load.sh --help       # usage
```

---

## 3. Supplemental Loader (`scripts/load_supplement_bronx.py`)

Specialized entrypoint to load the 10 supplemental tables and restricted `a4i_health_audit` dataset. Defaults to Bronx (`36005`), but accepts `--county-fips`:

```bash
# Load Bronx pilot supplemental tables (default)
python scripts/load_supplement_bronx.py

# Load supplemental tables for another county
python scripts/load_supplement_bronx.py --county-fips 17031
```

---

## 4. Cleaner & Parquet Cache Exporter (`scripts/clean_bronx_data.py`)

Materializes clean views (`v_clean_tracts`, `v_clean_county_context`, `v_clean_bronx_tracts`, `v_clean_borough_context`) and saves local offline parquet caches (`data/cache/tracts_<fips>.parquet` and `data/cache/care_sites_<fips>.parquet`).

```bash
# Clean Bronx pilot data and export cache (default)
python scripts/clean_bronx_data.py

# Clean another county
python scripts/clean_bronx_data.py --county-fips 13121
```

---

## County-Agnostic Design Features

1. **Explicit Schemas for Empty Shortage Tables**: Counties without active HPSAs or MUAs (e.g. Fulton GA `13121`, Santa Clara CA `06085`, Harris TX `48201`, Travis TX `48453`) upload typed BigQuery schemas (`bigquery.SchemaField`) to prevent schema drift and `NotFound` query crashes.
2. **Adaptive Distance Weighting**: In dense urban areas like Bronx NY (median distance 0.39 km, 94% of tracts have 0 km distance gap), physical distance is weighted 0.00. In counties with real transit/distance disparities, the cleaner dynamically weights `pr_distance_gap` (15%).
3. **Dynamic Weather Stations**: Automatically queries the 3 nearest NOAA GSOD weather stations within 75 km for any county, while preserving LaGuardia (`725030`) and Central Park (`725053`) for Bronx County.
4. **Curated Landmarks & Corridors**: Provides rich local context via [`agent.data.landmarks_catalog`](../agent/data/landmarks_catalog.py) with 85+ tracts and 13 transit corridors for the Bronx pilot, plus major corridors for Fulton, Cook, Santa Clara, Harris, and Travis.
5. **Strict Governance Isolation**: Zero racial/ethnic columns in `a4i_health`; demographic attributes are strictly confined to `a4i_health_audit` for post-hoc auditing.
