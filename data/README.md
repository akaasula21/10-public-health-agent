# data/

Everything this challenge uses is pulled live from its original publishers or pre-staged Cloud Storage snapshots and loaded straight into BigQuery in **your** project.

For offline development and fast agent responses, local Parquet caches can be stored under `data/cache/`:
- `data/cache/tracts_<county_fips>.parquet` (e.g. `data/cache/tracts_36005.parquet` for Bronx pilot)
- `data/cache/care_sites_<county_fips>.parquet` (e.g. `data/cache/care_sites_36005.parquet`)
- `data/cache/borough_context_<county_fips>.parquet` / `data/cache/county_context_<county_fips>.parquet`

These caches are automatically populated by [`scripts/load_county_data.py`](../scripts/load_county_data.py) or [`scripts/clean_bronx_data.py`](../scripts/clean_bronx_data.py) when running the cleaning stage.

## Where the data lives in BigQuery

In `<your-project>.a4i_health` (Planner dataset — strictly race-free):

| Table / View | Grain | What it holds |
|---|---|---|
| `burden_tracts` | one row per census tract | uninsured, routine checkup, asthma, COPD, diabetes, blood pressure, disability measures, lack of transport, no-vehicle households, over-65/under-17, SVI theme scores, centroid |
| `exposure_tracts` | one row per census tract | mean and maximum PM2.5, and days over 12, 20, 25 and 35 µg/m³ |
| `tract_access` | one row per census tract | distance to nearest care site of any kind, nearest safety-net site, and safety-net gap |
| `care_sites` | one row per facility | every federally recognized care site inside the county, coordinates, address, and `site_kind` |
| `care_sites_state` | one row per facility | care sites statewide (useful for border tracts where nearest clinic is in an adjacent county) |
| `shortage_areas` | one row per HRSA designation | where the federal government says a **neighborhood** is underserved (HPSA score) |
| `shortage_facilities` | one row per HRSA designation | where a **clinic** serves an underserved population (care site, not shortage geography) |
| `disease_weekly` | one row per week | emergency-department visit percentages for COVID, flu, RSV (Health Service Area level) |
| `places_supplement_tracts` | one row per tract | CDC PLACES 2025 95% CIs parsed to numeric low/high bounds, screening measures, HRSNs |
| `svi_supplement_tracts` | one row per tract | CDC SVI 2022 daytime population, percentile ranks, crowding, multi-unit housing |
| `tract_neighbors` | one row per tract neighbor pair | 2020-vintage topological adjacency graph (`ST_TOUCHES`/`ST_INTERSECTS`) |
| `shortage_areas_all_disciplines` | one row per tract | HRSA Primary Care, Dental, and Mental Health HPSA scores |
| `shortage_mua_tracts` | one row per tract | HRSA Medically Underserved Area (MUA) Index of Medical Underservice (IMU) scores |
| `exposure_supplement_tracts` | one row per tract | EPA/CDC PM2.5 prediction standard error and Daily Tract-Level Ozone |
| `climate_heat_risk_tracts` | one row per tract | FEMA National Risk Index Heat Wave and Cold Wave risk scores |
| `noaa_seasonal_heat` | one row per station/month | BigQuery Public Data NOAA GSOD monthly heat extremes for nearest stations |
| `tract_access_enhanced` | one row per tract | Clinic operating-hours capacity within 1 km and 2 km |
| `planner_tract_features` | one row per tract | Unified, race-free feature table for Siting / Planner Agent |
| `v_clean_tracts` | view per tract | Certified production clean tract view (Bronx alias: `v_clean_bronx_tracts`) |
| `v_clean_county_context` | view per tract | Aggregate county baseline & z-scores (Bronx alias: `v_clean_borough_context`) |

In `<your-project>.a4i_health_audit` (Restricted Equity Audit dataset):

| Table / View | Grain | What it holds |
|---|---|---|
| `equity_audit_tracts` | one row per tract | CDC SVI Theme 3 racial/ethnic minority percentiles + ACS income, poverty, rent burden |
| `v_equity_baseline` | view per tract | Baseline comparison vs county demographic weighted averages (Bronx alias: `v_bronx_equity_baseline`) |

## Multi-County Loading

To load any US county into your project:
```bash
python scripts/load_county_data.py --county-fips <FIPS>
```
Pre-staged snapshot counties include:
- `36005`: Bronx County, NY (Pilot County)
- `13121`: Fulton County, GA
- `17031`: Cook County, IL
- `06085`: Santa Clara County, CA
- `48201`: Harris County, TX
- `48453`: Travis County, TX
