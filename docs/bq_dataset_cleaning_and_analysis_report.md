# BigQuery Dataset Cleaning & Quantitative Analysis Report — Bronx County, NY (`36005`)

> **GCP Project:** `qwiklabs-gcp-03-c81d344a3430`
> **Datasets Audited & Cleaned:**
> - `a4i_health` — **18 tables** (Planner / Siting Agent scope; verified `0` racial/ethnic Theme 3 columns)
> - `a4i_health_audit` — **1 table + 1 view** (`equity_audit_tracts`, `v_bronx_equity_baseline`; restricted Equity Auditor scope)
> - **Executable Cleaning & Analysis Script:** [`scripts/clean_and_analyze_bq.py`](../scripts/clean_and_analyze_bq.py)

---

## 1. Executive Summary of Dataset Inventory

| Dataset | Table / View | Rows | Spatial / Temporal Grain | Role in Architecture |
| :--- | :--- | ---: | :--- | :--- |
| `a4i_health` | `burden_tracts` | 347 | 2020 Census Tract (`geo_id`) | Core CDC PLACES chronic/preventive prevalence + SVI Themes 1, 2, 4 (race-free). |
| `a4i_health` | `places_supplement_tracts` | 347 | 2020 Census Tract (`geo_id`) | Numeric 95% CIs (`_ci_low`, `_ci_high`, `_ci_width`), non-food HRSNs, and 5 preventive screenings. |
| `a4i_health` | `svi_supplement_tracts` | 361 | 2020 Census Tract (`geo_id`) | Daytime population (`daytime_pop`), crowding, multi-unit housing, `EPL_*` percentiles, 2020 polygons (`tract_geom`). |
| `a4i_health` | `tract_neighbors` | 2,230 | Tract-to-Tract Edge (`tract_geo_id`, `neighbor_geo_id`) | 2020-vintage polygon adjacency graph + City Island Bridge edges (`347/347` tracts covered). |
| `a4i_health` | `care_sites` / `care_sites_state` | 252 / 1,752 | Point Facility (`latitude`, `longitude`) | CMS FQHCs, HRSA Health Center sites (with `TOT_OPER_HR_PER_WEEK` & setting flags), and Hospitals. |
| `a4i_health` | `tract_access` / `tract_access_bronx_enhanced` | 347 / 347 | 2020 Census Tract (`geo_id`) | Cross-border distance & weekly clinic hour density (both raw and cleaned community-accessible). |
| `a4i_health` | `shortage_areas` / `shortage_areas_all_disciplines` | 338 / 1,044 | Tract-Discipline (`GEO_ID`) | HRSA HPSA scores across Primary Care (`338`), Dental (`360`), and Mental Health (`346`). |
| `a4i_health` | `shortage_mua_tracts` | 361 | 2020 Census Tract (`geo_id`) | Spatially joined HRSA Medically Underserved Areas/Populations (`in_designated_mua`, `min_imu_score`). |
| `a4i_health` | `shortage_facilities` | 8 | Point Facility (`HPSA_ID`) | 8 major FQHC networks in the Bronx (used to identify existing care hubs; never unioned with `shortage_areas`). |
| `a4i_health` | `exposure_tracts` / `exposure_supplement_tracts` | 361 / 361 | 2020 Census Tract (`geo_id`) | EPA/CDC Downscaler $\text{PM}_{2.5}$ (`mean_pm`, `max_pm`, `mean_pm_stdd`) and Warm-Season Ozone (`mean_o3_ppb`, `mean_o3_stdd`). |
| `a4i_health` | `climate_heat_risk_tracts` / `noaa_seasonal_heat` | 361 / 12 | 2020 Tract / Monthly Station | FEMA NRI Heat/Cold Wave risk scores (`heatwave_risk_score`) + 5-yr NOAA GSOD monthly heat/freeze days. |
| `a4i_health` | `disease_weekly` | 212 | County-Week (`fips = 36005`) | CDC NSSP ED visits for COVID/Flu/RSV (`100% NULL` for Bronx HSA — flagged as active surveillance blind spot). |
| `a4i_health` | `planner_tract_features` | 347 | 2020 Census Tract (`geo_id`) | Unified, cleaned, race-free feature store for the Siting/Planner Agent. |
| `a4i_health_audit` | `equity_audit_tracts` & `v_bronx_equity_baseline` | 361 | 2020 Census Tract (`geo_id`) | Restricted post-hoc Equity Auditor table & baseline view (SVI Theme 3 racial/ethnic shares + cleaned ACS income/rent/Gini). |

---

## 2. Six Dataset Cleaning Issues Discovered & Fixed in BigQuery

### Cleaning 1: Raw `-666666666.0` Census ACS Sentinels & 100% `NULL` `acs_median_hh_income` (`a4i_health_audit`)
* **Issue Discovered:**
  1. In `bigquery-public-data.census_bureau_acs.censustract_2020_5yr`, `median_income` is **100% `NULL` (`361/361` rows)** for Bronx County (`36005`), causing `county_weighted_median_income` in `v_bronx_equity_baseline` to evaluate to `NULL`.
  2. Four ACS economic columns contained raw Census Bureau missing-value sentinels of **`-666666666.0`**:
     * `acs_income_per_capita` (`14` rows with `-666666666.0`)
     * `acs_gini_index` (`19` rows with `-666666666.0`)
     * `acs_median_rent` (`21` rows with `-666666666.0`, including 5 residential tracts with `audit_total_pop >= 500`, which corrupted the raw mean rent across residential tracts from **\$1,170/mo** to **-\$9,717,020/mo**)
     * `acs_pct_income_spent_on_rent` (`19` rows with `-666666666.0`)
* **Cleaning Applied (`scripts/clean_and_analyze_bq.py` Step 1):**
  * Replaced all negative (`< 0`) sentinel values with `NULL` across all ACS columns in `equity_audit_tracts`.
  * Backfilled `acs_median_hh_income` from `bigquery-public-data.census_bureau_acs.censustract_2018_5yr` (matching exact `geo_id` or 9-digit 2010 parent tract stem `SUBSTR(geo_id, 1, 9)`), and added `county_weighted_per_capita_income` (`\$22,690`) alongside `county_weighted_median_income` in `v_bronx_equity_baseline`.

---

### Cleaning 2: Carceral / Institutional (`100%` Group Quarters) & Park Micro-Tract Guardrails (`planner_tract_features`)
* **Issue Discovered:**
  * Out of `347` tracts in `burden_tracts` / `planner_tract_features`, **4 tracts have `pct_group_quarters = 100.0%`** and `NULL` SVI socioeconomic/vehicle metrics:
    * `36005000100`: **Rikers Island jail complex** (`total_pop = 3,772`, `pct_uninsured = 23.8%`, `km_to_safety_net_statewide = 2.416 km`). Without an institutional filter, a naive ranking on `pct_uninsured * distance` recommends sending the Saturday community mobile health van to Rikers Island.
    * `36005009302`: **Vernon C. Bain Center (jail barge) / Hunts Point industrial zone** (`total_pop = 512`, `pct_group_quarters = 100%`, `pct_uninsured = 33.4%`).
    * `36005028400`: **Bronx Psychiatric Center** (`total_pop = 297`, `daytime_pop = 9,812`, `pct_group_quarters = 100%`, `pct_diabetes = 34.2%`).
    * `36005031900`: **SUNY Maritime / university dormitory tract** (`total_pop = 454`, `pct_group_quarters = 100%`).
  * **3 park/commercial micro-tracts** have `total_pop < 500`: `36005033400` (`total_pop = 69`, `daytime_pop_ratio = 59.7x`, Bronx Park/NYBG), `36005043503` (`total_pop = 122`, `daytime_pop_ratio = 49.9x`), and `36005003700` (`total_pop = 340`).
* **Cleaning Applied (`scripts/clean_and_analyze_bq.py` Step 5):**
  * Added `is_community_residential_tract` (`total_pop >= 500 AND COALESCE(pct_group_quarters, 0) < 25.0`) and `is_institutional_group_quarters` (`COALESCE(pct_group_quarters, 0) >= 25.0`) directly to `planner_tract_features`.

---

### Cleaning 3: Care-Site Deduplication & Exclusion of School-Only (`SBHC`), Shelter-Only (`HCH`), and Mobile-Van Records (`tract_access_bronx_enhanced`)
* **Issue Discovered:**
  * `care_sites` (`252` rows in Bronx: `92` CMS FQHCs, `151` HRSA Health Center sites, `9` Hospitals) double-counts physical facilities that appear in both CMS (`FQHC`) and HRSA (`Health Center site`), as well as multiple sub-registrations at the exact same address (e.g., `260 E 188th St` has 5 rows summing to `109.5` weekly hours; `853 Longwood Ave` has 4 rows including `Mobile Medical Clinic 1` and `Mobile Medical Clinic 3` summing to `160.0` weekly hours).
  * Furthermore, **46 of the 151 HRSA Health Center sites (`30.5%`) are School-Based Health Centers (`HCC_LOC_SETTING_DESC = 'School'` / `SBHC_SUB_PROG_IND = 'Y'`)** inside public K–12 schools (restricted to enrolled students Mon–Fri), and **18 sites are Homeless-Shelter-Only clinics (`HCH_SUB_PROG_IND = 'Y'`)**.
* **Cleaning Applied (`scripts/clean_and_analyze_bq.py` Step 4):**
  * Deduplicated physical safety-net locations (`ROUND(latitude, 4), ROUND(longitude, 4)`) and excluded School-Based (`SBHC`), Homeless-Shelter (`HCH`), and Mobile-Van records to compute:
    * `km_to_community_safety_net_clean`
    * `community_safety_net_sites_within_1km_clean`
    * `community_safety_net_hours_within_1km_clean`
    * `est_uninsured_per_clean_clinic_hr_1km`
  * **Impact:** Reduces Bronx safety-net rows from `243` raw records to **`117` unique community-accessible clinics**, reduces average weekly clinic hours within 1 km from `321.1` hrs/wk to **`247.4` hrs/wk**, and **newly exposes `22` high-need residential tracts as `1 km` community clinic deserts** (`0` community clinics within 1 km, rising from `43` raw tracts to `65` cleaned tracts).

---

### Cleaning 4: 2010 vs. 2020 Census Tract Vintage Mismatch & IEEE `NaN` Floats (`exposure_supplement_tracts` & `planner_tract_features`)
* **Issue Discovered:**
  1. CDC Ozone (`hf2a-3ebq`) and HRSA HPSA (`shortage_areas_all_disciplines`) use **2010 Census tract FIPS codes**, whereas PLACES 2025, SVI 2022, and FEMA NRI use **2020 Census tract FIPS codes**.
  2. In `exposure_supplement_tracts`, merging 361 2020 tracts (PM2.5) with 339 2010 tracts (Ozone) left `16` retired 2010 tracts (`377` total rows) and stored **25 split 2020 tracts as IEEE `NaN` (`IS_NAN(mean_o3_ppb) = TRUE`)** rather than SQL `NULL` (breaking `AVG()` in SQL).
  3. In `planner_tract_features`, exact `USING (geo_id)` joins against `shortage_areas_all_disciplines` left **32 out of 347 tracts (`9.2%`) with `NULL` HPSA scores**.
* **Cleaning Applied (`scripts/clean_and_analyze_bq.py` Steps 2 & 5):**
  * Converted all IEEE `NaN` floats to SQL `NULL`, pruned the 16 retired 2010 orphan rows from `exposure_supplement_tracts` (`361` clean 2020 rows), and backfilled split 2020 tracts from their 9-digit 2010 parent tract stem (`SUBSTR(geo_id, 1, 9)`).
  * Result: **0 missing/NaN Ozone tracts (`347/347` complete)** and **31 of 32 missing HPSA tracts recovered (`346/347` complete)** in `planner_tract_features`.

---

### Cleaning 5: Removal of 100% Empty `primary_care_pop_provider_ratio` & Explicit Handling of `disease_weekly`
* `primary_care_pop_provider_ratio` (`HPSA_FORMAL_RATIO`) was `100% NULL` (`0/347` rows) in HRSA's Bronx feed and was removed from `planner_tract_features` in favor of `est_uninsured_per_clean_clinic_hr_1km`.
* `disease_weekly` (`212` rows, `100% NULL` for Bronx NSSP ED visits) is retained as required by the starter schema and explicitly handled as an active surveillance blind spot (triggering rapid Flu/COVID/RSV point-of-care swab kits on the mobile van + seasonal scheduling via `noaa_seasonal_heat`).

---

### Cleaning 6: City Island Bridge Adjacency Fix (`tract_neighbors`)
* **Issue Discovered:** `36005051601` (**City Island**, `total_pop = 4,445`, `km_to_safety_net_statewide = 4.658 km`) had `bordering_tract_count = NULL` in `planner_tract_features` because `ST_INTERSECTS` across water polygons did not connect City Island to Pelham Bay Park (`36005051602`).
* **Cleaning Applied (`scripts/clean_and_analyze_bq.py` Step 3):** Added bidirectional bridge adjacency edges connecting `36005051601` to `36005051602` and `36005026602` (`0` NULLs remaining in `bordering_tract_count`).

---

## 3. Extracted Quantitative Analyses for Bronx Siting & Equity Auditing

### 3.1 Signal-to-Noise & Feature Spread Analysis (`339` Community Residential Tracts)
| Metric | Column | `p10` | `Median (p50)` | `p90` | Spread / Uncertainty | Siting Guidance |
| :--- | :--- | ---: | ---: | ---: | :--- | :--- |
| **Uninsured Adults (`18–64`)** | `pct_uninsured` | `7.4%` | `16.9%` | `22.9%` | **`3.09x` (`p90/p10`)** | Primary access-barrier driver. |
| **Cleaned Community Clinic Hours (`<=1 km`)** | `community_safety_net_hours_within_1km_clean` | `0.0 hrs` | `125.0 hrs` | `640.0 hrs` | `65` tracts have **`0 hrs`** | Identifies true community clinic deserts (especially where raw data only had a school clinic). |
| **Raw Distance to Safety Net** | `km_to_safety_net_statewide` | `0.12 km` | `0.39 km` | `1.06 km` | Median `390 m` (`Max 4.75 km`) | Urban distance trap for inner Bronx; only differentiates extreme outer-ring tracts (`>1.2 km`). |
| **Diabetes Prevalence** | `pct_diabetes` | `10.8%` | `15.2%` | `19.3%` | **`1.79x`** (CI width `~2.4 pp`) | High signal-to-noise chronic indicator. |
| **Asthma Prevalence** | `pct_asthma` | `10.4%` | `12.0%` | `13.4%` | `3.0 pp` spread (`Max 15.7%`) | High in South Bronx (Mott Haven/Hunts Point) & Northeast Bronx. |
| **Preventive Screening Composite** | `preventive_screening_composite` | `66.5%` | `70.8%` | `79.4%` | `12.9 pp` deficit | Directly actionable by a mobile van. |
| **Housing Insecurity (HRSN)** | `pct_housing_insecurity` | `16.8%` | `32.2%` | `42.4%` | **`2.52x`** | Strong race-free social vulnerability indicator. |
| **No-Vehicle Households** | `pct_no_vehicle` | `25.1%` | `63.5%` | `79.0%` | **`3.15x`** | Captures transit/walk-in dependency. |
| **FEMA Heat Wave Risk** | `heatwave_risk_score` | `69.3` | `89.2` | `95.0` | **`25.7 pt` spread** | Replaces flat $\text{PM}_{2.5}$ for environmental health differentiation. |
| **Annual Mean $\text{PM}_{2.5}$ (`12 km` grid)** | `mean_pm` vs `mean_pm_stdd` | `8.071` | `8.116` | `8.156` | Spread `0.085` vs **`±2.52` error** | **Do not rank tracts on `mean_pm`** (error is `30x` larger than county spread). |
| **Warm-Season Ozone (`12 km` grid)** | `mean_o3_ppb` vs `mean_o3_stdd` | `34.18` | `34.68` | `35.19` | Spread `1.01` vs **`±3.52` error** | **Do not rank tracts on `mean_o3_ppb`** (error is `3.5x` larger than county spread). |

### 3.2 Tracts Newly Exposed as 1 km Safety-Net Deserts After Removing School-Only & Shelter-Only Clinics
| Tract (`geo_id`) | Pop | Uninsured | Diabetes | SVI Socioeconomic | Raw Sites (`<=1 km`) | Raw Hours (`<=1 km`) | **Cleaned Community Sites (`<=1 km`)** | **Cleaned Dist (`km`)** |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `36005045800` | 5,662 | 20.6% | 19.8% | 0.955 | 1 (School) | 40.0 | **0** | **1.005 km** |
| `36005009000` | 3,911 | 21.8% | 18.8% | 0.922 | 2 (School) | 80.5 | **0** | **1.031 km** |
| `36005046203` | 6,599 | 11.0% | 19.6% | 0.806 | 1 (School) | 40.0 | **0** | **2.825 km** |
| `36005000400` | 6,272 | 11.3% | 10.9% | 0.617 | 1 (School) | 40.0 | **0** | **1.405 km** |
| `36005041100` | 3,215 | 19.2% | 14.2% | 0.970 | 1 (School) | 40.5 | **0** | **1.082 km** |
| `36005039400` | 4,647 | 12.4% | 15.8% | 0.965 | 1 (School) | 40.0 | **0** | **1.056 km** |

### 3.3 Post-Cleaning Bronx Equity Audit Baseline (`a4i_health_audit.v_bronx_equity_baseline`)
* **County Total Audited Population:** `1,443,229` (`343` residential tracts with `audit_total_pop >= 500`)
* **County Population-Weighted Minority Share (`county_pct_minority`):** **`91.4%`** (`56.4%` Hispanic/Latino, `28.3%` Black Non-Hispanic, `4.1%` Asian Non-Hispanic, `8.6%` White Non-Hispanic)
* **County Population-Weighted Below 150% Poverty (`county_pct_below_150pct_poverty`):** **`36.8%`**
* **County Population-Weighted Per-Capita Income (`county_weighted_per_capita_income`):** **`\$22,690`**
* **County Population-Weighted Median Household Income (`county_weighted_median_income`, backfilled):** **`\$41,432`**
