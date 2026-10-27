# Design Document Handoff: Supplemental Datasets & Equity Audit Governance (The Bronx Pilot)

> **Instructions for Gemini (Google Docs):** Use this handoff specification to update the **Data Architecture**, **Feature Engineering**, **Agent Governance / Equity Audit**, and **Methodological Limitations & Safeguards** sections of the Public Health Challenge 5 Design Document. Preserve existing system architecture prose where applicable and integrate the table schemas, rationale, and governance controls below.

---

## 1. Executive Summary & Architectural Shifts

- **Pilot Jurisdiction:** Bronx County, New York (`COUNTY_FIPS = "36005"`, `STATE_ABBR = "NY"`, `STATE_FIPS = "36"`, 361 populated 2020-vintage census tracts).
- **Core Problem with the Baseline Starter Pipeline (`c5_01_load_explore.ipynb`):**
  1. **Missing Equity Audit Data:** The starter pipeline deliberately excluded CDC Social Vulnerability Index (SVI) Theme 3 (Racial & Ethnic Minority Status) and overall composite SVI (`RPL_THEMES`) so that siting models would not use race as an input. However, Challenge 5 requires an **equity audit** of proposed interventions—which was impossible without loading those variables into a governed, auditor-only environment.
  2. **Point-Estimate Blindness:** The starter pipeline loaded only crude point estimates from CDC PLACES (`*_crudeprev`) and daily mean PM2.5 (`ds_pm_pred`), discarding the published 95% confidence intervals (`*_crude95ci`) and downscaler standard errors (`ds_pm_stdd`) needed to distinguish true high-burden tracts from small-sample noise.
  3. **Single-Discipline & County-Clipped Supply:** The starter pipeline pulled only Primary Care HPSAs (ignoring Dental and Mental Health shortages and Medically Underserved Areas), treated a 10-hour/week clinic identically to a 60-hour/week clinic, and clipped facility distance calculations at the Bronx county border—creating artificial "healthcare deserts" along the Upper Manhattan and Yonkers borders.
  4. **Missing Daytime Demand, Contiguity, Ozone, and Heat Risk:** The starter pipeline lacked daytime population shifts (`E_DAYPOP`), 2020-vintage tract adjacency (`tract_neighbors`), warm-season ozone (`hf2a-3ebq`), and urban heat island / extreme temperature risk (FEMA NRI + NOAA GSOD)—all critical drivers of respiratory and cardiovascular emergencies in the Bronx.

### Two-Dataset BigQuery Governance Architecture

To satisfy the challenge requirement that **race and ethnicity must never drive siting optimization, yet must be audited post-hoc to verify equitable impact**, our loader (`scripts/load_supplement_bronx.py` / `notebooks/c5_02_load_supplement_bronx.ipynb`) splits BigQuery storage into two IAM-isolated datasets:

- **`<PROJECT>.a4i_health` (Planner / Siting Agent Scope):** Contains all clinical, non-racial SVI, multi-discipline shortage, air quality, heat risk, and spatial access tables. Verified via automated `INFORMATION_SCHEMA.COLUMNS` checks to contain zero racial/ethnic columns.
- **`<PROJECT>.a4i_health_audit` (Restricted Equity Auditor Scope):** Strips broad project readers (`allUsers`, `allAuthenticatedUsers`, `projectReaders`, `projectViewers`) and `PLANNER_PRINCIPAL`, granting `roles/bigquery.dataViewer` exclusively to `AUDITOR_PRINCIPAL`.

---

## 2. Dataset-by-Dataset Rationale ("Why We Added Each Dataset")

### 2.1 Restricted Equity Audit Dataset: `a4i_health_audit.equity_audit_tracts` & `v_bronx_equity_baseline`
- **Data Sources & License:**
  - **CDC/ATSDR Social Vulnerability Index (SVI) 2022** (`MapServer/2`) — US Federal Government Public Domain.
  - **US Census Bureau ACS 5-Year Estimates (`bigquery-public-data.census_bureau_acs.censustract_2020_5yr`)** — Public Domain (CC0).
- **Why We Added It (Design Rationale):**
  - The starter notebook omitted SVI Theme 3 (`RPL_THEME3`, `EP_MINRTY`) and overall composite SVI (`RPL_THEMES`) to prevent racial variables from leaking into siting scores. However, without these variables—and without granular income distribution metrics—the system cannot prove whether a proposed mobile clinic route or facility siting plan equitably serves historically marginalized communities or inadvertently reinforces structural disparities.
  - Adding `equity_audit_tracts` in a **separate, ACL-restricted dataset (`a4i_health_audit`)** enables a rigorous **two-agent separation of duties**:
    1. **Planner / Siting Agent (`PLANNER_PRINCIPAL`)** queries only `<PROJECT>.a4i_health` to select candidate tracts based purely on clinical disease burden, uninsured rates, environmental exposure, and care access gaps.
    2. **Equity Auditor Agent (`AUDITOR_PRINCIPAL`)** queries `<PROJECT>.a4i_health_audit.equity_audit_tracts` and `v_bronx_equity_baseline` *after* candidate tracts are proposed to compute distributional equity metrics against the population-weighted Bronx baseline.
- **Key Variables Added:**
  - *SVI Theme 3 & Disaggregated Demographics:* `svi_minority_status` (`RPL_THEME3`), `pct_minority` (`EP_MINRTY`), `pctile_minority` (`EPL_MINRTY`), `pct_black_afam` (`EP_AFAM`), `pct_hispanic` (`EP_HISP`), `pct_asian` (`EP_ASIAN`), `pct_aian` (`EP_AIAN`), `pct_nhpi` (`EP_NHPI`), `pct_two_or_more_races` (`EP_TWOMORE`), `pct_other_race` (`EP_OTHERRACE`), and `svi_overall_composite` (`RPL_THEMES`).
  - *Economic & Housing Vulnerability (SVI + ACS):* `pct_below_150pct_poverty` (`EP_POV150`), `pct_housing_cost_burden` (`EP_HBURD`), `median_household_income`, `per_capita_income`, `gini_index` (within-tract income inequality), `pct_poverty_acs`, and `pct_rent_over_35pct` (severe rent burden computed from ACS `B25070`).

---

### 2.2 Clinical Uncertainty, Preventive Gaps & HRSNs: `a4i_health.places_supplement_tracts`
- **Data Source & License:** **CDC PLACES 2025 Release** (`data.cdc.gov` Socrata ID `yjkw-uj5s`, BRFSS 2022/2023 small-area estimation on 2020 Census tracts) — Public Domain.
- **Why We Added It (Design Rationale):**
  1. **Uncertainty Quantification (95% Confidence Intervals):** PLACES tract estimates are statistical small-area models (`*_crudeprev`). In dense urban tracts with varying sample sizes or institutional populations, confidence interval widths vary substantially. Parsing `*_crude95ci` into numeric `*_ci_low`, `*_ci_high`, and `*_ci_width` for all 11 core indicators allows the Planner Agent to rank tracts using **conservative lower-bound need (`_ci_low`)** or flag high-uncertainty tracts before committing capital.
  2. **Actionable Intervention Design (HRSNs & Preventive Screenings):** Knowing a tract has high diabetes or hypertension is not enough to design the *type* of intervention. By adding **Health-Related Social Needs (HRSNs)** (`pct_housing_insecurity`, `pct_utility_shutoff_threat`, `pct_lack_emotional_support`, `pct_social_isolation`), **preventive care uptake** (`pct_dental_visit`, `pct_Taking_bp_meds`, `pct_cholesterol_screen`, `pct_colorectal_screen`, `pct_mammography`), and **comorbidities / sensory-cognitive disabilities** (`pct_frequent_mental_distress`, `pct_frequent_physical_distress`, `pct_depression`, `pct_coronary_heart_disease`, `pct_stroke`, `pct_kidney_disease`, `pct_obesity`, `pct_current_smoking`, `pct_cognitive_difficulty`, `pct_hearing_difficulty`, `pct_vision_difficulty`), the Planner Agent can tailor the intervention package (e.g., pairing a mobile hypertension clinic with medication adherence support, utility-shutoff legal aid referrals, or cognitive/vision-accessible materials).

---

### 2.3 Daytime Demand, Housing Density & 2020 Tract Contiguity: `a4i_health.svi_supplement_tracts` & `tract_neighbors`
- **Data Source & License:** **CDC/ATSDR SVI 2022 Tract Layer** (`MapServer/2`, queried with `returnGeometry=true`, `outSR=4326`) — Public Domain.
- **Why We Added It (Design Rationale):**
  1. **Daytime Population vs. Nighttime Resident Population (`E_DAYPOP`):** Standard census population (`E_TOTPOP`) measures where people sleep, not where they are during clinic operating hours (9 AM – 5 PM). In the Bronx, commercial/medical hubs (e.g., The Hub / Melrose, Fordham Plaza, Pelham Parkway hospital corridor) experience massive daytime influxes, whereas commuter bedrooms empty out. Adding `daytime_pop` and `daytime_to_resident_ratio` prevents siting daytime mobile vans in tracts that are empty at noon.
  2. **Built-Environment Respiratory & Infectious Amplifiers:** Household crowding (`pct_crowded_housing` / `EP_CROWD`) and dense multi-unit buildings (`pct_multi_unit_housing` / `EP_MUNIT`) are primary indoor triggers for asthma exacerbations (mold, pests, indoor PM2.5) and respiratory transmission, directly complementing outdoor air quality data.
  3. **2020-Vintage Polygon Geometries & Spatial Contiguity (`tract_neighbors`):**
     - *Critical Technical Safeguard:* As documented in the starter notebook, `bigquery-public-data.geo_census_tracts` uses **2010 Census boundaries**, which fail to join cleanly against **2020-vintage** PLACES 2025 and SVI 2022 tracts wherever tracts split or merged in 2020.
     - Instead of using outdated 2010 polygons, we extract **2020-vintage tract polygon rings** directly from the CDC SVI 2022 ArcGIS service, convert them to BigQuery `GEOGRAPHY` (`tract_geom`), and compute `tract_neighbors` (`ST_INTERSECTS`). This enables **multi-tract catchment optimization** (e.g., siting a clinic on the boundary of three contiguous high-burden tracts and quantifying spillover coverage).

---

### 2.4 Multi-Discipline Shortage Scores & Medically Underserved Areas: `a4i_health.shortage_areas_all_disciplines` & `shortage_mua_tracts`
- **Data Source & License:**
  - **HRSA Health Professional Shortage Areas (HPSA)** (`HealthProfessionalShortageAreas_FS/MapServer`, Layers `11` Primary Care, `3` Dental Health, `7` Mental Health) — Public Domain.
  - **HRSA Medically Underserved Areas / Populations (MUA/P)** (`HealthCareShortage/MapServer`, Layers `14` MUP and `15` MUA) — Public Domain.
- **Why We Added It (Design Rationale):**
  1. **Mental Health & Dental Shortages alongside Primary Care:** The starter pipeline loaded only Layer 11 (Primary Care HPSA). However, Behavioral/Mental Health (`Layer 7`, 346 Bronx rows) and Dental Health (`Layer 3`, 360 Bronx rows) have completely separate federal shortage scores (`HPSA_SCORE` 0–25) that embed provider-to-population ratios and travel time to the nearest discipline-specific care site. Combining all three disciplines into `shortage_areas_all_disciplines` allows our system to recommend whether a proposed site needs a primary care NP, a behavioral health counselor, or a mobile dental chair.
  2. **Index of Medical Underservice (`IMU_SCORE`) via Spatial Join:** HRSA's MUA/P designations (`IMU_SCORE` 0–100, where <= 62.0 designates severe structural underservice—e.g., South East Bronx Service Area at `49.9`) capture long-term structural primary care scarcity that complements HPSA scores. Because MUA/P service areas are published as polygons without a county FIPS column, we spatially join active New York designations (`CMN_STATE_FIPS_CD='36' AND STATUS_CODE='D'`) directly onto Bronx tract polygons/centroids via `ST_INTERSECTS` in BigQuery.

---

### 2.5 Air Quality Model Uncertainty & Warm-Season Ozone: `a4i_health.exposure_supplement_tracts`
- **Data Sources & License:**
  - **CDC NEPHT / EPA Downscaler Daily Tract PM2.5 (`vpk8-vfhm`, 2021)** — Public Domain.
  - **CDC NEPHT / EPA Downscaler Daily Tract 8-Hour Max Ozone (`hf2a-3ebq`, 2016–2020)** — Public Domain.
- **Why We Added It (Design Rationale):**
  1. **Addressing the Starter Notebook's PM2.5 Critique (`ds_pm_stdd`):** Section 2 and Section 6 of `c5_01_load_explore.ipynb` proved that county-wide mean PM2.5 in the Bronx is nearly uniform across tracts (`8.37 µg/m³`, 1.07x spread), and warned that ranking tracts by tail exceedance days (`days_over_20`) without checking the downscaler's prediction standard error (`ds_pm_stdd`) risks ranking tracts by model residual rather than air quality. We aggregate `mean_pm_stdd` and `max_pm_stdd` per tract so the Planner Agent can discount noisy threshold rankings.
  2. **Adding Warm-Season Ozone (`hf2a-3ebq`):** While PM2.5 captures winter inversions and wildfire smoke plumes, **ground-level ozone (O3)** is the primary warm-season photochemical trigger for pediatric and adult asthma emergency department visits in the Bronx. Adding `mean_o3_ppb`, `max_o3_ppb`, `mean_o3_stdd`, `o3_days_over_50ppb`, and `o3_days_over_70ppb` (NAAQS 70 ppb standard) gives the respiratory outreach model full year-round pollutant coverage.
  3. **Data Engineering Safeguards:**
     - `hf2a-3ebq` stores `ctfips` as a **numeric integer** (not text like `vpk8-vfhm`), so our loader queries `ctfips between 36005000000 and 36005999999` via server-side `$group` aggregation (avoiding a multi-million-row download).
     - Unlike `vpk8-vfhm` (which duplicates every tract-day twice), `hf2a-3ebq` has a verified `1.0x` daily grain (1,827 days across 2016–2020) and uses 2010-vintage tract IDs, so it is `LEFT JOIN`ed onto the 2020 `burden_tracts` spine with explicit `ozone_tract_matched` coverage flags.

---

### 2.6 Urban Heat Risk, Community Resilience & Seasonal Weather: `a4i_health.climate_heat_risk_tracts` & `noaa_seasonal_heat`
- **Data Sources & License:**
  - **FEMA National Risk Index (NRI) Census Tracts (`FeatureServer/0`)** — Public Domain.
  - **NOAA Global Surface Summary of the Day (`bigquery-public-data.noaa_gsod.gsod2020`–`gsod2024`)** — Public Domain.
- **Why We Added It (Design Rationale):**
  1. **Tract-Level Heat Wave & Cold Wave Vulnerability (FEMA NRI):** In the Bronx, extreme heat interacts synergistically with ozone, high hypertension prevalence, psychiatric medications, and utility-shutoff threats (`pct_utility_shutoff_threat`, lack of A/C) to drive preventable hospitalizations. FEMA NRI provides census-tract-level **Heat Wave Risk Scores (`HWAV_RISKS`)**, **Expected Annual Loss Scores (`HWAV_EALS`)**, **Annualized Frequency (`HWAV_AFREQ`)**, **Cold Wave Risk (`CWAV_RISKS`)**, and **Community Resilience (`RESL_SCORE`)** for all 361 Bronx tracts.
  2. **Operational Scheduling by Month (`noaa_seasonal_heat`):** By aggregating 5 years (2020–2024) of daily station observations around the Bronx (LaGuardia Airport `725030` and Central Park `725053`), `noaa_seasonal_heat` quantifies the exact monthly distribution of >= 90°F heat days, >= 85°F warm days, and <= 32°F freeze days—enabling the Planner Agent to schedule seasonal mobile cooling/respiratory clinics in July–August and hypertension/flu outreach in winter.

---

### 2.7 Cross-Border Supply Correction & Operating-Hours Capacity: `a4i_health.tract_access_bronx_enhanced` & `planner_tract_features`
- **Data Source & License:** Derived in BigQuery from HRSA CMS-Approved Facilities & HRSA Health Center Sites (`care_sites_state`, `care_sites`) + 2020 Tract Geometries — Public Domain.
- **Why We Added It (Design Rationale):**
  1. **Eliminating County-Border Edge Distortion (`border_edge_effect_m`):** The starter notebook's `tract_access` table computed distance to the nearest care site using only `care_sites` *inside* Bronx County. For tracts in Marble Hill, Riverdale, Kingsbridge, Wakefield, and Woodlawn, major hospitals and FQHCs sit just across the Harlem River in Upper Manhattan (New York County) or across the northern border in Yonkers (Westchester County). Recomputing distances against statewide `care_sites_state` (`dist_nearest_any_WithBorder_m`, `dist_nearest_fqhc_WithBorder_m`) and measuring `border_edge_effect_m` prevents the Siting Agent from wasting mobile clinics on tracts that already have a major hospital 400 meters away across a county line.
  2. **Weighting Supply by Weekly Operating Hours (`TOT_OPER_HR_PER_WEEK`):** The starter notebook counted a clinic open 8 hours/week identically to one open 60 hours/week. We aggregate `weekly_clinic_hours_within_1km` and `weekly_clinic_hours_within_2km` so the Planner Agent can distinguish **true capacity deserts** from tracts that have a nominal clinic pin with part-time hours.
  3. **Unified Race-Free Feature Store (`planner_tract_features`):** Joins all non-racial burden, confidence-interval, daytime-population, multi-discipline HPSA/MUA, PM2.5/Ozone, FEMA heat-risk, and cross-border access features into a single wide table for the Planner Agent.

---

## 3. Why Candidate Datasets Were Deliberately Excluded (Scope Discipline)

To keep the Bronx pilot architecture lean, reproducible, and aligned with domain realities, three candidate dataset families were evaluated and **deliberately excluded**:

| Excluded Dataset Family | Specific Sources | Architectural Reason for Exclusion in the Bronx Pilot |
|---|---|---|
| **Transit Datasets** | EPA Smart Location Database (SLD), MTA GTFS stops/headways, ACS `B08301` transit commute share | Unlike sprawling car-dependent counties (e.g., Harris County, TX or Travis County, TX), the Bronx has universal MTA bus/subway coverage and high transit mode share across nearly all tracts. Moreover, CDC PLACES (`pct_lack_transport`) and CDC SVI (`pct_no_vehicle`) already capture household transportation barriers directly in `burden_tracts`. |
| **USDA Food Access Research Atlas** | USDA ERS low-income / low-access ("food desert") tract flags | USDA's standard distance thresholds (0.5 miles and 1.0 mile to a large supermarket) are calibrated for suburban/rural car travel and poorly reflect dense NYC bodega/grocer retail geography; clinical nutrition outcomes (`pct_diabetes`, `pct_obesity`, `pct_high_bp`) are already measured directly per tract in PLACES. |
| **White House CEQ CEJST** | Climate & Economic Justice Screening Tool (1.0 / 2.0) | CEJST relies on 2010-vintage census tract boundaries (creating cross-walk friction against 2020-vintage PLACES/SVI tracts) and its underlying environmental/socioeconomic indicators are now superseded in our pipeline by 2020-vintage FEMA NRI, CDC SVI 2022, ACS 5-Year, and EPA Downscaler PM2.5/Ozone. |

---

## 4. Governance & Security Controls Summary (For the Design Doc Security Section)

1. **Dataset-Level ACL Enforcement (`enforce_equity_audit_acl`):**
   - On `<PROJECT>.a4i_health_audit`, the loader programmatically removes broad reader groups (`allUsers`, `allAuthenticatedUsers`, `projectReaders`, `projectViewers`) and any `PLANNER_PRINCIPAL` from `dataset.access_entries`, granting `roles/bigquery.dataViewer` exclusively to `AUDITOR_PRINCIPAL`.
2. **Automated Zero-Leakage Verification (`INFORMATION_SCHEMA.COLUMNS`):**
   - Step 11 executes a mandatory BigQuery metadata audit across every table in `<PROJECT>.a4i_health` checking against a forbidden column list (`RPL_THEME3`, `RPL_THEMES`, `EP_MINRTY`, `EPL_MINRTY`, `EP_AFAM`, `EP_HISP`, `EP_ASIAN`, `EP_AIAN`, `EP_NHPI`, `EP_TWOMORE`, `EP_OTHERRACE`, `pct_minority`, `pct_black_afam`, `pct_hispanic`, etc.). Any match raises a fatal `RuntimeError`.
3. **Strict PII Allow-Listing on Facility Ingestion:**
   - The HRSA Primary Health Care Facilities layer (`MapServer/0`) contains named individual contact columns (`FQHC_ADMIN_CONTACT_NM`, `FQHC_ADMIN_CONTACT_EMAIL`, `FQHC_ADMIN_CONTACT_PHONE_NUM`). Both the base and supplemental loaders enforce an explicit `outFields` allow-list and verify at runtime that zero `CONTACT` columns enter BigQuery.
