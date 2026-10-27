#!/usr/bin/env python3
"""
BigQuery Dataset Cleaning & Quantitative Analysis Suite — Bronx County, NY (36005)
Project: qwiklabs-gcp-03-c81d344a3430
Datasets:
  - a4i_health        (Planner / Siting Scope — strictly race-free)
  - a4i_health_audit  (Restricted Equity Auditor Scope)

Executes 6 critical data cleaning fixes in BigQuery and runs the quantitative
signal-to-noise, care-site capacity, multi-objective siting, and equity baseline analyses.
"""

import os
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
from google.cloud import bigquery

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "qwiklabs-gcp-03-c81d344a3430")
DATASET = os.environ.get("BQ_DATASET", "a4i_health")
AUDIT_DATASET = os.environ.get("BQ_AUDIT_DATASET", "a4i_health_audit")
LOCATION = os.environ.get("BQ_LOCATION", "US")

bq = bigquery.Client(project=PROJECT, location=LOCATION)


def run_sql(sql: str) -> pd.DataFrame:
    return pd.DataFrame([dict(r) for r in bq.query(sql).result()])


print("=" * 80)
print(f"STEP 1: CLEAN ACS -666666666.0 SENTINELS & BACKFILL INCOME IN `{AUDIT_DATASET}`")
print("=" * 80)

# Clean -666666666.0 sentinels in equity_audit_tracts and backfill acs_median_hh_income
# from censustract_2018_5yr (exact match or 9-digit 2010 parent tract stem)
clean_audit_sql = f"""
CREATE OR REPLACE TABLE `{PROJECT}.{AUDIT_DATASET}.equity_audit_tracts` AS
WITH acs20 AS (
  SELECT
    geo_id,
    IF(median_income > 0, median_income, NULL) AS median_income_2020,
    IF(income_per_capita > 0, income_per_capita, NULL) AS income_per_capita_2020,
    IF(gini_index > 0, ROUND(gini_index, 4), NULL) AS gini_index_2020,
    IF(median_rent > 0, median_rent, NULL) AS median_rent_2020,
    IF(percent_income_spent_on_rent > 0, ROUND(percent_income_spent_on_rent, 1), NULL) AS rent_pct_2020,
    ROUND(SAFE_DIVIDE(IF(poverty >= 0, poverty, NULL), NULLIF(pop_determined_poverty_status, 0)) * 100, 1) AS poverty_pct_2020
  FROM `bigquery-public-data.census_bureau_acs.censustract_2020_5yr`
  WHERE STARTS_WITH(geo_id, '36005')
),
acs18_exact AS (
  SELECT
    geo_id,
    IF(median_income > 0, median_income, NULL) AS median_income_2018
  FROM `bigquery-public-data.census_bureau_acs.censustract_2018_5yr`
  WHERE STARTS_WITH(geo_id, '36005')
),
acs18_stem AS (
  SELECT
    SUBSTR(geo_id, 1, 9) AS stem9,
    ROUND(AVG(IF(median_income > 0, median_income, NULL)), 0) AS stem_median_income_2018
  FROM `bigquery-public-data.census_bureau_acs.censustract_2018_5yr`
  WHERE STARTS_WITH(geo_id, '36005')
  GROUP BY 1
)
SELECT
  s.* EXCEPT(
    acs_median_hh_income,
    acs_income_per_capita,
    acs_gini_index,
    acs_median_rent,
    acs_pct_income_spent_on_rent,
    acs_pct_below_100pct_poverty
  ),
  COALESCE(a20.median_income_2020, a18.median_income_2018, s18.stem_median_income_2018) AS acs_median_hh_income,
  a20.income_per_capita_2020 AS acs_income_per_capita,
  a20.gini_index_2020 AS acs_gini_index,
  a20.median_rent_2020 AS acs_median_rent,
  a20.rent_pct_2020 AS acs_pct_income_spent_on_rent,
  a20.poverty_pct_2020 AS acs_pct_below_100pct_poverty
FROM `{PROJECT}.{AUDIT_DATASET}.equity_audit_tracts` s
LEFT JOIN acs20 a20 USING (geo_id)
LEFT JOIN acs18_exact a18 USING (geo_id)
LEFT JOIN acs18_stem s18 ON SUBSTR(s.geo_id, 1, 9) = s18.stem9
"""
bq.query(clean_audit_sql).result()

clean_baseline_view_sql = f"""
CREATE OR REPLACE VIEW `{PROJECT}.{AUDIT_DATASET}.v_bronx_equity_baseline` AS
WITH county_avg AS (
  SELECT
    SUM(audit_total_pop) AS county_total_pop,
    ROUND(SAFE_DIVIDE(SUM(pct_minority * audit_total_pop), SUM(audit_total_pop)), 1) AS county_pct_minority,
    ROUND(SAFE_DIVIDE(SUM(pct_black_nonhisp * audit_total_pop), SUM(audit_total_pop)), 1) AS county_pct_black_nonhisp,
    ROUND(SAFE_DIVIDE(SUM(pct_hispanic * audit_total_pop), SUM(audit_total_pop)), 1) AS county_pct_hispanic,
    ROUND(SAFE_DIVIDE(SUM(pct_asian_nonhisp * audit_total_pop), SUM(audit_total_pop)), 1) AS county_pct_asian_nonhisp,
    ROUND(SAFE_DIVIDE(SUM(pct_white_nonhisp_est * audit_total_pop), SUM(audit_total_pop)), 1) AS county_pct_white_nonhisp,
    ROUND(SAFE_DIVIDE(SUM(pct_below_150pct_poverty * audit_total_pop), SUM(audit_total_pop)), 1) AS county_pct_below_150pct_poverty,
    ROUND(SAFE_DIVIDE(SUM(pct_housing_cost_burdened * audit_total_pop), SUM(audit_total_pop)), 1) AS county_pct_housing_cost_burdened,
    ROUND(SAFE_DIVIDE(SUM(IF(acs_median_hh_income > 0, acs_median_hh_income * audit_total_pop, NULL)), SUM(IF(acs_median_hh_income > 0, audit_total_pop, NULL))), 0) AS county_weighted_median_income,
    ROUND(SAFE_DIVIDE(SUM(IF(acs_income_per_capita > 0, acs_income_per_capita * audit_total_pop, NULL)), SUM(IF(acs_income_per_capita > 0, audit_total_pop, NULL))), 0) AS county_weighted_per_capita_income
  FROM `{PROJECT}.{AUDIT_DATASET}.equity_audit_tracts`
  WHERE audit_total_pop > 0
)
SELECT
  t.*,
  c.county_total_pop,
  c.county_pct_minority,
  c.county_pct_black_nonhisp,
  c.county_pct_hispanic,
  c.county_pct_asian_nonhisp,
  c.county_pct_white_nonhisp,
  c.county_pct_below_150pct_poverty,
  c.county_pct_housing_cost_burdened,
  c.county_weighted_median_income,
  c.county_weighted_per_capita_income,
  ROUND(t.pct_minority - c.county_pct_minority, 1) AS diff_vs_county_pct_minority,
  ROUND(t.pct_black_nonhisp - c.county_pct_black_nonhisp, 1) AS diff_vs_county_pct_black,
  ROUND(t.pct_hispanic - c.county_pct_hispanic, 1) AS diff_vs_county_pct_hispanic,
  ROUND(t.pct_below_150pct_poverty - c.county_pct_below_150pct_poverty, 1) AS diff_vs_county_pct_poverty
FROM `{PROJECT}.{AUDIT_DATASET}.equity_audit_tracts` t
CROSS JOIN county_avg c
"""
bq.query(clean_baseline_view_sql).result()

audit_check = run_sql(f"""
SELECT
  COUNT(*) AS total_rows,
  COUNTIF(acs_median_hh_income IS NOT NULL) AS valid_median_hh_income,
  COUNTIF(acs_income_per_capita < 0 OR acs_gini_index < 0 OR acs_median_rent < 0 OR acs_pct_income_spent_on_rent < 0) AS negative_sentinels_remaining,
  ANY_VALUE(county_weighted_median_income) AS county_weighted_median_income,
  ANY_VALUE(county_weighted_per_capita_income) AS county_weighted_per_capita_income
FROM `{PROJECT}.{AUDIT_DATASET}.v_bronx_equity_baseline`
""")
print(audit_check.to_string(index=False))


print("\n" + "=" * 80)
print(f"STEP 2: CLEAN IEEE NaN FLOATS & 2010->2020 SPLIT TRACTS IN `exposure_supplement_tracts`")
print("=" * 80)

clean_exp_sup_sql = f"""
CREATE OR REPLACE TABLE `{PROJECT}.{DATASET}.exposure_supplement_tracts` AS
WITH valid_2020_tracts AS (
  SELECT geo_id FROM `{PROJECT}.{DATASET}.svi_supplement_tracts`
),
raw_clean AS (
  SELECT
    geo_id,
    IF(IS_NAN(mean_pm_stdd), NULL, mean_pm_stdd) AS mean_pm_stdd,
    IF(IS_NAN(max_pm_stdd), NULL, max_pm_stdd) AS max_pm_stdd,
    IF(IS_NAN(mean_o3_ppb), NULL, mean_o3_ppb) AS mean_o3_ppb,
    IF(IS_NAN(max_o3_ppb), NULL, max_o3_ppb) AS max_o3_ppb,
    IF(IS_NAN(mean_o3_stdd), NULL, mean_o3_stdd) AS mean_o3_stdd,
    IF(IS_NAN(o3_days_per_yr_over_50ppb), NULL, o3_days_per_yr_over_50ppb) AS o3_days_per_yr_over_50ppb,
    IF(IS_NAN(o3_days_per_yr_over_70ppb), NULL, o3_days_per_yr_over_70ppb) AS o3_days_per_yr_over_70ppb
  FROM `{PROJECT}.{DATASET}.exposure_supplement_tracts`
),
stem_o3_fallback AS (
  SELECT
    SUBSTR(geo_id, 1, 9) AS stem9,
    ROUND(AVG(mean_o3_ppb), 4) AS stem_mean_o3_ppb,
    ROUND(MAX(max_o3_ppb), 4) AS stem_max_o3_ppb,
    ROUND(AVG(mean_o3_stdd), 4) AS stem_mean_o3_stdd,
    ROUND(AVG(o3_days_per_yr_over_50ppb), 1) AS stem_o3_days_50,
    ROUND(AVG(o3_days_per_yr_over_70ppb), 1) AS stem_o3_days_70
  FROM raw_clean
  WHERE mean_o3_ppb IS NOT NULL
  GROUP BY 1
)
SELECT
  v.geo_id,
  r.mean_pm_stdd,
  r.max_pm_stdd,
  COALESCE(r.mean_o3_ppb, sf.stem_mean_o3_ppb) AS mean_o3_ppb,
  COALESCE(r.max_o3_ppb, sf.stem_max_o3_ppb) AS max_o3_ppb,
  COALESCE(r.mean_o3_stdd, sf.stem_mean_o3_stdd) AS mean_o3_stdd,
  COALESCE(r.o3_days_per_yr_over_50ppb, sf.stem_o3_days_50) AS o3_days_per_yr_over_50ppb,
  COALESCE(r.o3_days_per_yr_over_70ppb, sf.stem_o3_days_70) AS o3_days_per_yr_over_70ppb,
  r.mean_o3_ppb IS NULL AND sf.stem_mean_o3_ppb IS NOT NULL AS ozone_backfilled_from_2010_parent
FROM valid_2020_tracts v
LEFT JOIN raw_clean r USING (geo_id)
LEFT JOIN stem_o3_fallback sf ON SUBSTR(v.geo_id, 1, 9) = sf.stem9
"""
bq.query(clean_exp_sup_sql).result()
exp_check = run_sql(f"""
SELECT
  COUNT(*) AS total_rows,
  COUNTIF(mean_o3_ppb IS NULL OR IS_NAN(mean_o3_ppb)) AS null_or_nan_o3,
  COUNTIF(ozone_backfilled_from_2010_parent) AS backfilled_2020_split_tracts
FROM `{PROJECT}.{DATASET}.exposure_supplement_tracts`
""")
print(exp_check.to_string(index=False))


print("\n" + "=" * 80)
print(f"STEP 3: FIX CITY ISLAND BRIDGE ADJACENCY IN `tract_neighbors`")
print("=" * 80)

fix_neighbors_sql = f"""
CREATE OR REPLACE TABLE `{PROJECT}.{DATASET}.tract_neighbors` AS
WITH base_edges AS (
  SELECT
    a.geo_id AS tract_geo_id,
    b.geo_id AS neighbor_geo_id,
    ROUND(ST_DISTANCE(ST_CENTROID(a.tract_geom), ST_CENTROID(b.tract_geom)) / 1000.0, 3) AS centroid_distance_km
  FROM `{PROJECT}.{DATASET}.svi_supplement_tracts` a
  JOIN `{PROJECT}.{DATASET}.svi_supplement_tracts` b
    ON a.geo_id != b.geo_id
   AND ST_INTERSECTS(a.tract_geom, b.tract_geom)
  WHERE a.tract_geom IS NOT NULL AND b.tract_geom IS NOT NULL
),
bridge_edges AS (
  -- City Island (36005051601) connects via the City Island Bridge to Pelham Bay Park (36005051602)
  -- and nearest residential mainland tract (36005026602)
  SELECT
    a.geo_id AS tract_geo_id,
    b.geo_id AS neighbor_geo_id,
    ROUND(ST_DISTANCE(ST_CENTROID(a.tract_geom), ST_CENTROID(b.tract_geom)) / 1000.0, 3) AS centroid_distance_km
  FROM `{PROJECT}.{DATASET}.svi_supplement_tracts` a
  JOIN `{PROJECT}.{DATASET}.svi_supplement_tracts` b
    ON (a.geo_id = '36005051601' AND b.geo_id IN ('36005051602', '36005026602'))
    OR (b.geo_id = '36005051601' AND a.geo_id IN ('36005051602', '36005026602'))
)
SELECT DISTINCT tract_geo_id, neighbor_geo_id, centroid_distance_km
FROM (
  SELECT * FROM base_edges
  UNION ALL
  SELECT * FROM bridge_edges
)
"""
bq.query(fix_neighbors_sql).result()
nb_check = run_sql(f"""
SELECT COUNT(DISTINCT tract_geo_id) AS tracts_with_neighbors,
       COUNTIF(tract_geo_id = '36005051601') AS city_island_neighbors
FROM `{PROJECT}.{DATASET}.tract_neighbors`
""")
print(nb_check.to_string(index=False))


print("\n" + "=" * 80)
print(f"STEP 4: DEDUPLICATE & FILTER SCHOOL/SHELTER/MOBILE CARE SITES & REBUILD ACCESS")
print("=" * 80)

# Build cleaned, deduplicated community safety-net view/metrics in tract_access_bronx_enhanced
enhanced_access_clean_sql = f"""
CREATE OR REPLACE TABLE `{PROJECT}.{DATASET}.tract_access_bronx_enhanced` AS
WITH t AS (
  SELECT
    geo_id,
    total_pop,
    pct_uninsured,
    ST_GEOGPOINT(longitude, latitude) AS pt
  FROM `{PROJECT}.{DATASET}.burden_tracts`
  WHERE longitude IS NOT NULL AND latitude IS NOT NULL
),
state_sites AS (
  SELECT
    site_kind,
    FACILITY_NM,
    CMS_PROVIDER_ADDRESS,
    HCC_LOC_SETTING_DESC,
    SBHC_SUB_PROG_IND,
    HCH_SUB_PROG_IND,
    SAFE_CAST(TOT_OPER_HR_PER_WEEK AS FLOAT64) AS hours_per_week,
    latitude,
    longitude,
    ST_GEOGPOINT(longitude, latitude) AS pt
  FROM `{PROJECT}.{DATASET}.care_sites_state`
  WHERE longitude IS NOT NULL AND latitude IS NOT NULL
),
-- Deduplicated, general community-accessible safety-net sites (excluding School-Based SBHC,
-- Homeless-Shelter-only HCH, and Mobile Vans parked at HQ; deduplicated by ~11m lat/lon grid)
clean_community_state_sites AS (
  SELECT
    ROUND(latitude, 4) AS lat4,
    ROUND(longitude, 4) AS lon4,
    ANY_VALUE(FACILITY_NM) AS facility_name,
    MAX(COALESCE(hours_per_week, 40.0)) AS max_weekly_hours,
    ST_GEOGPOINT(AVG(longitude), AVG(latitude)) AS pt
  FROM state_sites
  WHERE site_kind IN ('FQHC', 'Health Center site')
    AND COALESCE(HCC_LOC_SETTING_DESC, '') != 'School'
    AND COALESCE(SBHC_SUB_PROG_IND, 'N') != 'Y'
    AND COALESCE(HCH_SUB_PROG_IND, 'N') != 'Y'
    AND NOT REGEXP_CONTAINS(LOWER(COALESCE(FACILITY_NM, '')), r'mobile|school|i\\.s\\.|p\\.s\\.|m\\.s\\.|h\\.s\\.|high school|campus|academy|elementary')
  GROUP BY 1, 2
),
county_sites AS (
  SELECT
    site_kind,
    SAFE_CAST(TOT_OPER_HR_PER_WEEK AS FLOAT64) AS hours_per_week,
    ST_GEOGPOINT(longitude, latitude) AS pt
  FROM `{PROJECT}.{DATASET}.care_sites`
  WHERE longitude IS NOT NULL AND latitude IS NOT NULL
),
state_metrics AS (
  SELECT
    t.geo_id,
    ROUND(MIN(ST_DISTANCE(t.pt, s.pt)) / 1000.0, 3) AS km_to_any_care_statewide,
    ROUND(MIN(IF(s.site_kind IN ('FQHC', 'Health Center site'), ST_DISTANCE(t.pt, s.pt), NULL)) / 1000.0, 3) AS km_to_safety_net_statewide,
    ROUND(MIN(IF(s.site_kind IN ('FQHC', 'Health Center site') AND COALESCE(s.hours_per_week, 0) >= 35, ST_DISTANCE(t.pt, s.pt), NULL)) / 1000.0, 3) AS km_to_fulltime_safety_net,
    COUNTIF(s.site_kind IN ('FQHC', 'Health Center site') AND ST_DWITHIN(t.pt, s.pt, 1000)) AS safety_net_sites_within_1km,
    ROUND(SUM(IF(s.site_kind IN ('FQHC', 'Health Center site') AND ST_DWITHIN(t.pt, s.pt, 1000), COALESCE(s.hours_per_week, 0), 0)), 1) AS safety_net_weekly_hours_within_1km,
    COUNTIF(s.site_kind IN ('FQHC', 'Health Center site') AND ST_DWITHIN(t.pt, s.pt, 2000)) AS safety_net_sites_within_2km,
    ROUND(SUM(IF(s.site_kind IN ('FQHC', 'Health Center site') AND ST_DWITHIN(t.pt, s.pt, 2000), COALESCE(s.hours_per_week, 0), 0)), 1) AS safety_net_weekly_hours_within_2km
  FROM t
  CROSS JOIN state_sites s
  GROUP BY t.geo_id
),
clean_community_metrics AS (
  SELECT
    t.geo_id,
    ROUND(MIN(ST_DISTANCE(t.pt, cs.pt)) / 1000.0, 3) AS km_to_community_safety_net_clean,
    COUNTIF(ST_DWITHIN(t.pt, cs.pt, 1000)) AS community_safety_net_sites_within_1km_clean,
    ROUND(SUM(IF(ST_DWITHIN(t.pt, cs.pt, 1000), cs.max_weekly_hours, 0)), 1) AS community_safety_net_hours_within_1km_clean
  FROM t
  CROSS JOIN clean_community_state_sites cs
  GROUP BY t.geo_id
),
county_metrics AS (
  SELECT
    t.geo_id,
    ROUND(MIN(ST_DISTANCE(t.pt, c.pt)) / 1000.0, 3) AS km_to_any_care_county_only,
    ROUND(MIN(IF(c.site_kind IN ('FQHC', 'Health Center site'), ST_DISTANCE(t.pt, c.pt), NULL)) / 1000.0, 3) AS km_to_safety_net_county_only
  FROM t
  CROSS JOIN county_sites c
  GROUP BY t.geo_id
)
SELECT
  t.geo_id,
  cm.km_to_any_care_county_only,
  cm.km_to_safety_net_county_only,
  sm.km_to_any_care_statewide,
  sm.km_to_safety_net_statewide,
  ROUND(sm.km_to_safety_net_statewide - sm.km_to_any_care_statewide, 3) AS extra_km_if_uninsured_statewide,
  ROUND(cm.km_to_safety_net_county_only - sm.km_to_safety_net_statewide, 3) AS border_clip_km_error,
  sm.km_to_fulltime_safety_net,
  ROUND(sm.km_to_fulltime_safety_net - sm.km_to_safety_net_statewide, 3) AS extra_km_for_fulltime_hours,
  sm.safety_net_sites_within_1km,
  sm.safety_net_weekly_hours_within_1km,
  sm.safety_net_sites_within_2km,
  sm.safety_net_weekly_hours_within_2km,
  ROUND(
    SAFE_DIVIDE(t.total_pop * (t.pct_uninsured / 100.0), NULLIF(sm.safety_net_weekly_hours_within_1km, 0)),
    1
  ) AS est_uninsured_adults_per_weekly_clinic_hr_1km,
  ccm.km_to_community_safety_net_clean,
  ccm.community_safety_net_sites_within_1km_clean,
  ccm.community_safety_net_hours_within_1km_clean,
  ROUND(
    SAFE_DIVIDE(t.total_pop * (t.pct_uninsured / 100.0), NULLIF(ccm.community_safety_net_hours_within_1km_clean, 0)),
    1
  ) AS est_uninsured_per_clean_clinic_hr_1km
FROM t
LEFT JOIN county_metrics cm USING (geo_id)
LEFT JOIN state_metrics sm USING (geo_id)
LEFT JOIN clean_community_metrics ccm USING (geo_id)
"""
bq.query(enhanced_access_clean_sql).result()
print("  rebuilt tract_access_bronx_enhanced with deduplicated, non-school community clinic metrics.")


print("\n" + "=" * 80)
print(f"STEP 5: REBUILD `planner_tract_features` WITH 2010->2020 HPSA BACKFILL & GUARDRAIL FLAGS")
print("=" * 80)

planner_features_clean_sql = f"""
CREATE OR REPLACE TABLE `{PROJECT}.{DATASET}.planner_tract_features` AS
WITH hpsa_exact AS (
  SELECT
    GEO_ID AS geo_id,
    MAX(IF(discipline = 'Primary Care', HPSA_SCORE, NULL)) AS primary_care_hpsa_score,
    MAX(IF(discipline = 'Dental Health', HPSA_SCORE, NULL)) AS dental_hpsa_score,
    MAX(IF(discipline = 'Mental Health', HPSA_SCORE, NULL)) AS mental_health_hpsa_score
  FROM `{PROJECT}.{DATASET}.shortage_areas_all_disciplines`
  WHERE geo_id_len = 11
  GROUP BY GEO_ID
),
hpsa_stem9 AS (
  SELECT
    SUBSTR(GEO_ID, 1, 9) AS stem9,
    MAX(IF(discipline = 'Primary Care', HPSA_SCORE, NULL)) AS stem_pc_hpsa_score,
    MAX(IF(discipline = 'Dental Health', HPSA_SCORE, NULL)) AS stem_dental_hpsa_score,
    MAX(IF(discipline = 'Mental Health', HPSA_SCORE, NULL)) AS stem_mh_hpsa_score
  FROM `{PROJECT}.{DATASET}.shortage_areas_all_disciplines`
  WHERE geo_id_len = 11
  GROUP BY 1
),
neighbor_summary AS (
  SELECT
    n.tract_geo_id AS geo_id,
    COUNT(DISTINCT n.neighbor_geo_id) AS bordering_tract_count,
    STRING_AGG(n.neighbor_geo_id, ', ' ORDER BY n.neighbor_geo_id) AS bordering_tract_ids
  FROM `{PROJECT}.{DATASET}.tract_neighbors` n
  GROUP BY n.tract_geo_id
)
SELECT
  b.*,
  -- Guardrail flags for institutional / group quarters & micro-tracts
  (b.total_pop >= 500 AND COALESCE(b.pct_group_quarters, 0) < 25.0) AS is_community_residential_tract,
  (COALESCE(b.pct_group_quarters, 0) >= 25.0) AS is_institutional_group_quarters,
  -- Confidence intervals & supplemental HRSNs / screenings from PLACES
  p.pct_uninsured_ci_low, p.pct_uninsured_ci_high,
  p.pct_asthma_ci_low, p.pct_asthma_ci_high,
  p.pct_copd_ci_low, p.pct_copd_ci_high,
  p.pct_diabetes_ci_low, p.pct_diabetes_ci_high,
  p.pct_high_bp_ci_low, p.pct_high_bp_ci_high,
  p.pct_checkup_ci_low, p.pct_checkup_ci_high,
  p.pct_housing_insecurity, p.pct_utility_shutoff_threat,
  p.pct_lack_emotional_support, p.pct_social_isolation,
  p.pct_mammogram_screen, p.pct_colorectal_screen, p.pct_cholesterol_screen,
  p.pct_dental_visit, p.pct_taking_bp_meds, p.pct_depression, p.pct_obesity,
  ROUND((b.pct_checkup + p.pct_mammogram_screen + p.pct_colorectal_screen + p.pct_cholesterol_screen + p.pct_dental_visit) / 5.0, 2) AS preventive_screening_composite,
  -- Daytime pop, density & non-racial percentiles from SVI
  s.daytime_pop, s.daytime_pop_ratio, s.area_sq_km, s.pop_density_per_sq_km,
  s.pct_crowded_housing, s.pct_multi_unit_housing,
  s.pctile_age_65_plus, s.pctile_disability, s.pctile_limited_english,
  -- Cross-border & capacity-weighted access (both raw and cleaned community-accessible)
  a.km_to_any_care_statewide, a.km_to_safety_net_statewide,
  a.extra_km_if_uninsured_statewide, a.border_clip_km_error,
  a.km_to_fulltime_safety_net, a.extra_km_for_fulltime_hours,
  a.safety_net_sites_within_1km, a.safety_net_weekly_hours_within_1km,
  a.est_uninsured_adults_per_weekly_clinic_hr_1km,
  a.km_to_community_safety_net_clean,
  a.community_safety_net_sites_within_1km_clean,
  a.community_safety_net_hours_within_1km_clean,
  a.est_uninsured_per_clean_clinic_hr_1km,
  -- HRSA HPSA scores (with 2010->2020 parent stem fallback) & MUA/P status
  COALESCE(h.primary_care_hpsa_score, hs.stem_pc_hpsa_score) AS primary_care_hpsa_score,
  COALESCE(h.dental_hpsa_score, hs.stem_dental_hpsa_score) AS dental_hpsa_score,
  COALESCE(h.mental_health_hpsa_score, hs.stem_mh_hpsa_score) AS mental_health_hpsa_score,
  m.in_designated_mua, m.min_imu_score, m.mua_service_areas,
  -- Air quality (12 km grid) & standard errors + cleaned Ozone
  x.mean_pm, x.max_pm, x.days_over_12, x.days_over_20, x.days_over_25,
  xs.mean_pm_stdd, xs.mean_o3_ppb, xs.max_o3_ppb, xs.mean_o3_stdd,
  xs.o3_days_per_yr_over_50ppb, xs.o3_days_per_yr_over_70ppb,
  -- FEMA Heat/Cold Wave risk
  c.heatwave_risk_score, c.heatwave_risk_rating, c.heatwave_events_per_yr,
  c.coldwave_risk_score, c.fema_community_resilience_score,
  -- Neighboring tract IDs
  nb.bordering_tract_count, nb.bordering_tract_ids
FROM `{PROJECT}.{DATASET}.burden_tracts` b
LEFT JOIN `{PROJECT}.{DATASET}.places_supplement_tracts` p USING (geo_id)
LEFT JOIN `{PROJECT}.{DATASET}.svi_supplement_tracts` s USING (geo_id)
LEFT JOIN `{PROJECT}.{DATASET}.tract_access_bronx_enhanced` a USING (geo_id)
LEFT JOIN hpsa_exact h USING (geo_id)
LEFT JOIN hpsa_stem9 hs ON SUBSTR(b.geo_id, 1, 9) = hs.stem9
LEFT JOIN `{PROJECT}.{DATASET}.shortage_mua_tracts` m USING (geo_id)
LEFT JOIN `{PROJECT}.{DATASET}.exposure_tracts` x USING (geo_id)
LEFT JOIN `{PROJECT}.{DATASET}.exposure_supplement_tracts` xs USING (geo_id)
LEFT JOIN `{PROJECT}.{DATASET}.climate_heat_risk_tracts` c USING (geo_id)
LEFT JOIN neighbor_summary nb USING (geo_id)
"""
bq.query(planner_features_clean_sql).result()

pf_check = run_sql(f"""
SELECT
  COUNT(*) AS total_tracts,
  COUNTIF(is_community_residential_tract) AS community_residential_tracts,
  COUNTIF(is_institutional_group_quarters) AS institutional_tracts,
  COUNTIF(primary_care_hpsa_score IS NOT NULL) AS tracts_with_pc_hpsa,
  COUNTIF(dental_hpsa_score IS NOT NULL) AS tracts_with_dental_hpsa,
  COUNTIF(mental_health_hpsa_score IS NOT NULL) AS tracts_with_mh_hpsa,
  COUNTIF(mean_o3_ppb IS NULL OR IS_NAN(mean_o3_ppb)) AS missing_or_nan_o3,
  COUNTIF(bordering_tract_count IS NULL) AS missing_neighbors
FROM `{PROJECT}.{DATASET}.planner_tract_features`
""")
print(pf_check.to_string(index=False))
