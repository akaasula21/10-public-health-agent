"""County-Agnostic Dataset Cleaner for the Public Health Mobile Care Broker.

Configured with Bronx County, NY (FIPS 36005) as the default pilot county (`PILOT_COUNTY_FIPS = "36005"`),
while supporting any US county loaded into BigQuery.

Cleans raw & supplemental BigQuery tables in `GCP_PROJECT_ID`, materializes clean BigQuery views
(`v_clean_tracts` / `v_clean_bronx_tracts`, `v_clean_care_sites`, `v_clean_county_context` /
`v_clean_borough_context`, `a4i_health_audit.v_clean_equity_audit`), and exports local
Parquet/GeoJSON/JSON caches in `data/cache/` for sub-50ms agent & map access.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pandas as pd

from agent.config import (
    BQ_AUDIT_DATASET,
    BQ_DATASET,
    CLEAN_BOROUGH_CONTEXT_VIEW,
    CLEAN_CARE_SITES_VIEW,
    CLEAN_COUNTY_CONTEXT_VIEW,
    CLEAN_EQUITY_AUDIT_VIEW,
    CLEAN_TRACTS_GENERIC_VIEW,
    CLEAN_TRACTS_VIEW,
    COUNTY_FIPS,
    GCP_PROJECT_ID,
    MAX_GROUP_QUARTERS_PCT,
    MIN_RESIDENTIAL_POPULATION,
    PILOT_COUNTY_FIPS,
    get_cache_paths,
    get_county_config,
    normalize_county_fips,
)
from agent.data.bq_client import get_bq_client, run_query_df
from agent.data.landmarks_catalog import lookup_tract_landmark_context

logger = logging.getLogger(__name__)


def build_clean_tracts_sql(
    project_id: str = GCP_PROJECT_ID,
    county_fips: str = COUNTY_FIPS,
    view_name: str | None = None,
) -> str:
    """Return the BigQuery DDL to create the clean tracts view (`v_clean_tracts` / `v_clean_bronx_tracts`).

    Cleaning & Feature Engineering Rules (County-Agnostic with Bronx 36005 Pilot Specializations):
    1. Enforces populated 2020 census tracts in `county_fips` (11-char `geo_id` STRING).
    2. Strips residual `< 0` (`-999`) CDC SVI sentinels across all socioeconomic/barrier columns.
    3. Imputes missing SVI/barrier metrics with the county residential median (flagged by `has_imputed_svi`).
    4. Maps every tract to its highest-severity HPSA zone (`HPSA_NM`, `HPSA_SCORE`), retaining the
       7 Bronx Medicaid Exception (`ME`) HPSA zones when `county_fips == '36005'`.
    5. Classifies Trap 2 Institutional & Low-Population Outliers (`pct_group_quarters > 25%` or `total_pop < 500`)
       with human-readable `outlier_category` and `outlier_rejection_reason` (including named Bronx pilot
       facilities such as Rikers Island, Hunts Point Barge, Bronx Psychiatric, and SUNY Maritime/Fordham dorms).
    6. Computes the Race-Blind Composite Siting Need Score (`composite_need_score`, 0–100):
       - For the Bronx pilot (`36005`) and dense urban counties where median `extra_km_if_uninsured <= 0.05`,
         enforces 0% physical distance weight (Trap 1 guardrail):
         25% HPSA Severity + 25% Clinic Hours Bottleneck + 20% Uninsured Rate + 20% Chronic Burden + 10% Transit/Language.
       - For counties with a physical safety-net distance gap (`median extra_km_if_uninsured > 0.05`) or
         zero designated HPSAs, dynamically incorporates `pr_distance_gap` (15%) and rebalances HPSA weight
         so 100% of the score remains active and discriminative.
    """
    fips = normalize_county_fips(county_fips)
    cfg = get_county_config(fips)
    target_view = view_name or f"{project_id}.{BQ_DATASET}.v_clean_bronx_tracts"
    short_label = cfg.short_name.replace("'", "\\'")

    return f"""
CREATE OR REPLACE VIEW `{target_view}` AS
WITH hpsa_dedup AS (
    SELECT
        CAST(GEO_ID AS STRING) AS geo_id,
        SUBSTR(CAST(GEO_ID AS STRING), 1, 9) AS tract_stem_9,
        HPSA_NM AS hpsa_name,
        CAST(HPSA_SCORE AS INT64) AS hpsa_score,
        HPSA_TYP_DESC AS hpsa_type_desc,
        HPSA_POVERTY AS hpsa_poverty_pct,
        ROW_NUMBER() OVER (
            PARTITION BY CAST(GEO_ID AS STRING)
            ORDER BY HPSA_SCORE DESC, HPSA_NM ASC
        ) AS rn
    FROM `{project_id}.{BQ_DATASET}.shortage_areas`
    WHERE HPSA_STATUS_DESC = 'Designated'
      AND LENGTH(CAST(GEO_ID AS STRING)) = 11
),
hpsa_stem_dedup AS (
    SELECT
        tract_stem_9,
        hpsa_name,
        hpsa_score,
        ROW_NUMBER() OVER (
            PARTITION BY tract_stem_9
            ORDER BY hpsa_score DESC, hpsa_name ASC
        ) AS rn_stem
    FROM hpsa_dedup
),
raw_sanitized AS (
    SELECT
        CAST(p.geo_id AS STRING) AS geo_id,
        CAST(p.total_pop AS INT64) AS total_pop,
        ROUND(CAST(p.latitude AS FLOAT64), 6) AS lat,
        ROUND(CAST(p.longitude AS FLOAT64), 6) AS lon,

        -- Clinical burden & uninsured metrics (strip any negative sentinels)
        IF(p.pct_uninsured < 0, NULL, p.pct_uninsured) AS pct_uninsured,
        IF(p.pct_asthma < 0, NULL, p.pct_asthma) AS pct_asthma,
        IF(p.pct_diabetes < 0, NULL, p.pct_diabetes) AS pct_diabetes,
        IF(p.pct_high_bp < 0, NULL, p.pct_high_bp) AS pct_high_bp,
        IF(p.pct_copd < 0, NULL, p.pct_copd) AS pct_copd,
        IF(p.pct_checkup < 0, NULL, p.pct_checkup) AS pct_checkup,
        IF(p.pct_depression < 0, NULL, p.pct_depression) AS pct_depression,
        IF(p.pct_obesity < 0, NULL, p.pct_obesity) AS pct_obesity,

        -- Confidence intervals from PLACES supplement
        p.pct_uninsured_ci_low,
        p.pct_uninsured_ci_high,
        p.pct_asthma_ci_low,
        p.pct_asthma_ci_high,
        p.pct_diabetes_ci_low,
        p.pct_diabetes_ci_high,

        -- SVI & Social/Transit Barriers (strip -999 sentinels)
        IF(p.pct_no_vehicle < 0, NULL, p.pct_no_vehicle) AS pct_no_vehicle_raw,
        IF(p.pct_lack_transport < 0, NULL, p.pct_lack_transport) AS pct_lack_transport_raw,
        IF(p.pct_limited_english < 0, NULL, p.pct_limited_english) AS pct_limited_english_raw,
        IF(p.pct_mobility_difficulty < 0, NULL, p.pct_mobility_difficulty) AS pct_mobility_difficulty_raw,
        IF(p.pct_any_disability < 0, NULL, p.pct_any_disability) AS pct_any_disability_raw,
        IF(p.pct_no_internet < 0, NULL, p.pct_no_internet) AS pct_no_internet_raw,
        IF(p.svi_socioeconomic < 0, NULL, p.svi_socioeconomic) AS svi_socioeconomic_raw,
        IF(p.svi_household < 0, NULL, p.svi_household) AS svi_household_raw,
        IF(p.svi_housing_transport < 0, NULL, p.svi_housing_transport) AS svi_housing_transport_raw,

        -- Group quarters & demographics allowed in race-blind siting (age only, ZERO race columns)
        COALESCE(IF(p.pct_group_quarters < 0, 0.0, p.pct_group_quarters), 0.0) AS pct_group_quarters,
        COALESCE(IF(p.pct_age_65_plus < 0, 0.0, p.pct_age_65_plus), 0.0) AS pct_age_65_plus,
        COALESCE(IF(p.pct_age_17_under < 0, 0.0, p.pct_age_17_under), 0.0) AS pct_age_17_under,
        COALESCE(p.daytime_pop, CAST(p.total_pop AS FLOAT64)) AS daytime_pop,
        COALESCE(p.pop_density_per_sq_km, 0.0) AS pop_density_per_sq_km,

        -- HPSA Zone Join (7 Bronx ME HPSA Zones for 36005 pilot; dynamic HPSA mapping for other counties)
        COALESCE(
            h.hpsa_name,
            hs.hpsa_name,
            CASE
                WHEN '{fips}' = '{PILOT_COUNTY_FIPS}' THEN
                    CASE p.primary_care_hpsa_score
                        WHEN 19 THEN 'ME - Pelham'
                        WHEN 18 THEN 'ME - High Bridge'
                        WHEN 17 THEN 'ME - Crotona'
                        WHEN 16 THEN 'ME - Hunts Point'
                        ELSE 'ME - Bronx Buffer Zone'
                    END
                WHEN p.primary_care_hpsa_score IS NOT NULL AND p.primary_care_hpsa_score > 0 THEN
                    CONCAT('{short_label} Designated HPSA (Score ', CAST(p.primary_care_hpsa_score AS STRING), ')')
                ELSE '{short_label} Non-Designated Area'
            END
        ) AS hpsa_name,
        COALESCE(
            h.hpsa_score,
            hs.hpsa_score,
            p.primary_care_hpsa_score,
            IF('{fips}' = '{PILOT_COUNTY_FIPS}', 16, 0)
        ) AS hpsa_score,
        COALESCE(h.hpsa_score IS NOT NULL OR hs.hpsa_score IS NOT NULL OR p.primary_care_hpsa_score IS NOT NULL, FALSE) AS in_me_hpsa_zone,
        COALESCE(p.dental_hpsa_score, 0) AS dental_hpsa_score,
        COALESCE(p.mental_health_hpsa_score, 0) AS mental_health_hpsa_score,
        COALESCE(p.in_designated_mua, FALSE) AS in_designated_mua,

        -- Clinic Distance & Operating-Hour Bottleneck Metrics
        COALESCE(p.km_to_any_care_statewide, 0.39) AS km_to_any_care,
        COALESCE(p.km_to_safety_net_statewide, 0.45) AS km_to_safety_net,
        COALESCE(p.extra_km_if_uninsured_statewide, 0.0) AS extra_km_if_uninsured,
        COALESCE(p.km_to_fulltime_safety_net, 0.85) AS km_to_fulltime_safety_net,
        COALESCE(p.community_safety_net_sites_within_1km_clean, p.safety_net_sites_within_1km, 0) AS safety_net_sites_1km,
        COALESCE(p.community_safety_net_hours_within_1km_clean, p.safety_net_weekly_hours_within_1km, 0.0) AS safety_net_weekly_hours_1km,
        COALESCE(p.est_uninsured_per_clean_clinic_hr_1km, p.est_uninsured_adults_per_weekly_clinic_hr_1km, 50.0) AS uninsured_adults_per_weekly_clinic_hr_1km,

        -- Environmental context (preserved for seasonal kit logic, NOT used in tract ranking per Trap 3)
        p.mean_pm,
        p.max_pm,
        p.heatwave_risk_score,
        p.heatwave_risk_rating,
        p.bordering_tract_ids
    FROM `{project_id}.{BQ_DATASET}.planner_tract_features` p
    LEFT JOIN hpsa_dedup h
      ON CAST(p.geo_id AS STRING) = h.geo_id AND h.rn = 1
    LEFT JOIN hpsa_stem_dedup hs
      ON SUBSTR(CAST(p.geo_id AS STRING), 1, 9) = hs.tract_stem_9 AND hs.rn_stem = 1
    WHERE STARTS_WITH(CAST(p.geo_id AS STRING), '{fips}')
      AND p.total_pop > 0
),
residential_medians AS (
    SELECT
        PERCENTILE_CONT(pct_no_vehicle_raw, 0.5) OVER () AS med_no_vehicle,
        PERCENTILE_CONT(pct_lack_transport_raw, 0.5) OVER () AS med_lack_transport,
        PERCENTILE_CONT(pct_limited_english_raw, 0.5) OVER () AS med_limited_english,
        PERCENTILE_CONT(svi_socioeconomic_raw, 0.5) OVER () AS med_svi_socio,
        PERCENTILE_CONT(svi_housing_transport_raw, 0.5) OVER () AS med_svi_housing
    FROM raw_sanitized
    WHERE pct_group_quarters <= {MAX_GROUP_QUARTERS_PCT}
      AND total_pop >= {MIN_RESIDENTIAL_POPULATION}
    LIMIT 1
),
cleaned_features AS (
    SELECT
        r.*,
        (r.svi_socioeconomic_raw IS NULL OR r.pct_no_vehicle_raw IS NULL) AS has_imputed_svi,
        ROUND(COALESCE(r.pct_no_vehicle_raw, m.med_no_vehicle, 15.0), 2) AS pct_no_vehicle,
        ROUND(COALESCE(r.pct_lack_transport_raw, m.med_lack_transport, 10.0), 2) AS pct_lack_transport,
        ROUND(COALESCE(r.pct_limited_english_raw, m.med_limited_english, 10.0), 2) AS pct_limited_english,
        ROUND(COALESCE(r.svi_socioeconomic_raw, m.med_svi_socio, 0.50), 4) AS svi_socioeconomic,
        ROUND(COALESCE(r.svi_housing_transport_raw, m.med_svi_housing, 0.50), 4) AS svi_housing_transport,

        -- Trap 2: Explicit Institutional & Low-Population Outlier Classification
        (r.pct_group_quarters > {MAX_GROUP_QUARTERS_PCT} OR r.total_pop < {MIN_RESIDENTIAL_POPULATION}) AS is_institutional_outlier,
        CASE
            WHEN r.geo_id = '36005000100' THEN 'CORRECTIONAL_FACILITY'
            WHEN r.geo_id = '36005009302' THEN 'CORRECTIONAL_BARGE_FACILITY'
            WHEN r.geo_id = '36005028400' THEN 'PSYCHIATRIC_INPATIENT_CAMPUS'
            WHEN r.geo_id IN ('36005031900', '36005039700') THEN 'UNIVERSITY_DORMITORY_CAMPUS'
            WHEN r.pct_group_quarters > {MAX_GROUP_QUARTERS_PCT} THEN 'INSTITUTIONAL_GROUP_QUARTERS'
            WHEN r.total_pop < {MIN_RESIDENTIAL_POPULATION} THEN 'LOW_POPULATION_NON_RESIDENTIAL'
            ELSE 'RESIDENTIAL_ELIGIBLE'
        END AS outlier_category,
        CASE
            WHEN r.geo_id = '36005000100' THEN 'Trap 2 Rejection: Rikers Island Correctional Complex (100% group quarters, pop 3,772) — restricted DOC island, ineligible for public street van.'
            WHEN r.geo_id = '36005009302' THEN 'Trap 2 Rejection: Hunts Point Maritime Detention Facility Tract (100% group quarters, pop 512) — locked correctional facility.'
            WHEN r.geo_id = '36005028400' THEN 'Trap 2 Rejection: Bronx Psychiatric Center Inpatient Campus (100% group quarters, pop 297) — institutional facility with SVI -999 sentinels.'
            WHEN r.geo_id IN ('36005031900', '36005039700') THEN CONCAT('Trap 2 Rejection: University Dormitory Tract (', CAST(ROUND(r.pct_group_quarters, 1) AS STRING), '% group quarters) — student housing skews uninsured/income metrics.')
            WHEN r.pct_group_quarters > {MAX_GROUP_QUARTERS_PCT} THEN CONCAT('Trap 2 Rejection: High Group Quarters Tract (', CAST(ROUND(r.pct_group_quarters, 1) AS STRING), '% > 25% threshold) — institutional nursing/congregate facility.')
            WHEN r.total_pop < {MIN_RESIDENTIAL_POPULATION} THEN CONCAT('Trap 2 Rejection: Low Residential Population Tract (pop ', CAST(r.total_pop AS STRING), ' < 500 threshold) — park/industrial zone.')
            ELSE 'Eligible residential community tract.'
        END AS outlier_rejection_reason
    FROM raw_sanitized r
    LEFT JOIN residential_medians m ON TRUE
),
percentile_ranks AS (
    SELECT
        c.*,
        -- Rank across all populated tracts in the county
        PERCENT_RANK() OVER (ORDER BY c.hpsa_score ASC) AS pr_hpsa,
        PERCENT_RANK() OVER (
            ORDER BY c.uninsured_adults_per_weekly_clinic_hr_1km ASC,
                     c.safety_net_weekly_hours_1km DESC
        ) AS pr_hours_bottleneck,
        PERCENT_RANK() OVER (ORDER BY c.pct_uninsured ASC) AS pr_uninsured,
        PERCENT_RANK() OVER (
            ORDER BY (0.40 * c.pct_asthma + 0.35 * c.pct_diabetes + 0.25 * c.pct_high_bp) ASC
        ) AS pr_chronic_burden,
        PERCENT_RANK() OVER (
            ORDER BY (0.40 * c.pct_no_vehicle + 0.35 * c.pct_limited_english + 0.25 * c.pct_lack_transport) ASC
        ) AS pr_transit_language,
        PERCENT_RANK() OVER (
            ORDER BY c.extra_km_if_uninsured ASC, c.km_to_safety_net ASC
        ) AS pr_distance_gap,
        (MAX(c.hpsa_score) OVER () > MIN(c.hpsa_score) OVER ()) AS county_has_hpsa_variance,
        PERCENTILE_CONT(c.extra_km_if_uninsured, 0.5) OVER () AS county_median_extra_km
    FROM cleaned_features c
)
SELECT
    p.* EXCEPT (county_has_hpsa_variance, county_median_extra_km, pr_distance_gap),
    ROUND(100.0 * p.pr_hpsa, 1) AS score_hpsa_severity,
    ROUND(100.0 * p.pr_hours_bottleneck, 1) AS score_clinic_hours_bottleneck,
    ROUND(100.0 * p.pr_uninsured, 1) AS score_uninsured_rate,
    ROUND(100.0 * p.pr_chronic_burden, 1) AS score_chronic_burden,
    ROUND(100.0 * p.pr_transit_language, 1) AS score_transit_language,
    CASE
        WHEN '{fips}' = '{PILOT_COUNTY_FIPS}' OR COALESCE(p.county_median_extra_km, 0.0) <= 0.05 THEN 0.0
        ELSE 15.0
    END AS score_distance_weight_pct,
    ROUND(
        100.0 * (
            CASE
                -- Pilot County (Bronx 36005) or dense urban county with active HPSA designations:
                -- Strictly 0% distance weight per Trap 1 guardrail
                WHEN ('{fips}' = '{PILOT_COUNTY_FIPS}' OR COALESCE(p.county_median_extra_km, 0.0) <= 0.05)
                     AND p.county_has_hpsa_variance THEN
                    0.25 * p.pr_hpsa +
                    0.25 * p.pr_hours_bottleneck +
                    0.20 * p.pr_uninsured +
                    0.20 * p.pr_chronic_burden +
                    0.10 * p.pr_transit_language
                -- Dense urban county without HPSA designations: 0% distance weight, rebalanced across 4 active dimensions
                WHEN ('{fips}' = '{PILOT_COUNTY_FIPS}' OR COALESCE(p.county_median_extra_km, 0.0) <= 0.05)
                     AND NOT p.county_has_hpsa_variance THEN
                    0.35 * p.pr_hours_bottleneck +
                    0.25 * p.pr_uninsured +
                    0.25 * p.pr_chronic_burden +
                    0.15 * p.pr_transit_language
                -- County with both HPSA variance and physical safety-net distance gaps
                WHEN p.county_has_hpsa_variance THEN
                    0.10 * p.pr_hpsa +
                    0.20 * p.pr_hours_bottleneck +
                    0.20 * p.pr_uninsured +
                    0.20 * p.pr_chronic_burden +
                    0.15 * p.pr_transit_language +
                    0.15 * p.pr_distance_gap
                -- County with physical safety-net distance gaps and 0 designated HPSAs (e.g., Fulton, Harris, Travis)
                ELSE
                    0.25 * p.pr_hours_bottleneck +
                    0.225 * p.pr_uninsured +
                    0.225 * p.pr_chronic_burden +
                    0.15 * p.pr_transit_language +
                    0.15 * p.pr_distance_gap
            END
        ),
        2
    ) AS composite_need_score
FROM percentile_ranks p
"""


def build_clean_bronx_tracts_sql(project_id: str = GCP_PROJECT_ID) -> str:
    """Backward-compatible wrapper returning the DDL for `v_clean_bronx_tracts`."""
    return build_clean_tracts_sql(
        project_id=project_id,
        county_fips=COUNTY_FIPS,
        view_name=f"{project_id}.{BQ_DATASET}.v_clean_bronx_tracts",
    )


def build_clean_care_sites_sql(
    project_id: str = GCP_PROJECT_ID,
    county_fips: str = COUNTY_FIPS,
) -> str:
    """Return the BigQuery DDL to create `a4i_health.v_clean_care_sites`."""
    cfg = get_county_config(county_fips)
    default_addr = f"{cfg.short_name}, {cfg.state_abbr}".replace("'", "\\'")
    return f"""
CREATE OR REPLACE VIEW `{project_id}.{BQ_DATASET}.v_clean_care_sites` AS
SELECT
    CONCAT(
        COALESCE(CAST(CMS_PROVIDER_NUM AS STRING), 'HRSA'),
        '_',
        CAST(ROW_NUMBER() OVER (ORDER BY FACILITY_NM, latitude, longitude) AS STRING)
    ) AS site_id,
    TRIM(FACILITY_NM) AS site_name,
    TRIM(COALESCE(CMS_PROVIDER_ADDRESS, '{default_addr}')) AS address,
    TRIM(COALESCE(CMS_PROVIDER_ZIP_CD, '')) AS zip_code,
    ROUND(CAST(latitude AS FLOAT64), 6) AS lat,
    ROUND(CAST(longitude AS FLOAT64), 6) AS lon,
    COALESCE(site_kind, 'Care Site') AS site_kind,
    COALESCE(HCC_TYP_DESC, CMS_PROVIDER_CAT_DESC, 'Clinic') AS facility_type,
    COALESCE(HCC_LOC_SETTING_DESC, 'All Other Clinic Types') AS setting_desc,
    (COALESCE(SBHC_SUB_PROG_IND, 'N') = 'Y' OR UPPER(COALESCE(HCC_LOC_SETTING_DESC, '')) LIKE '%SCHOOL%') AS is_school_based,
    ROUND(
        CASE
            WHEN TOT_OPER_HR_PER_WEEK IS NULL OR TOT_OPER_HR_PER_WEEK < 0 THEN 0.0
            ELSE CAST(TOT_OPER_HR_PER_WEEK AS FLOAT64)
        END,
        1
    ) AS weekly_hours,
    CASE
        WHEN TOT_OPER_HR_PER_WEEK IS NULL OR TOT_OPER_HR_PER_WEEK <= 0 THEN '0_HRS_UNREPORTED_OR_SCHOOL'
        WHEN TOT_OPER_HR_PER_WEEK < 20 THEN 'PART_TIME_UNDER_20_HRS'
        WHEN TOT_OPER_HR_PER_WEEK < 35 THEN 'MODERATE_20_TO_34_HRS'
        ELSE 'FULL_TIME_35_PLUS_HRS'
    END AS hours_tier,
    CASE
        WHEN TOT_OPER_HR_PER_WEEK IS NULL OR TOT_OPER_HR_PER_WEEK <= 0 THEN '#64748b'
        WHEN TOT_OPER_HR_PER_WEEK < 20 THEN '#f97316'
        WHEN TOT_OPER_HR_PER_WEEK < 35 THEN '#eab308'
        ELSE '#22c55e'
    END AS marker_color_hex
FROM `{project_id}.{BQ_DATASET}.care_sites`
WHERE latitude IS NOT NULL AND longitude IS NOT NULL
"""


def build_clean_county_context_sql(
    project_id: str = GCP_PROJECT_ID,
    county_fips: str = COUNTY_FIPS,
    view_name: str | None = None,
) -> str:
    """Return the BigQuery DDL to create `v_clean_county_context` / `v_clean_borough_context`."""
    fips = normalize_county_fips(county_fips)
    fips_int_str = str(int(fips))
    cfg = get_county_config(fips)
    escaped_name = cfg.county_name.replace("'", "\\'")
    target_view = view_name or f"{project_id}.{BQ_DATASET}.v_clean_borough_context"
    tracts_view = f"{project_id}.{BQ_DATASET}.v_clean_bronx_tracts"

    return f"""
CREATE OR REPLACE VIEW `{target_view}` AS
WITH tract_stats AS (
    SELECT
        COUNT(*) AS total_populated_tracts,
        SUM(total_pop) AS total_borough_population,
        SUM(total_pop) AS total_county_population,
        COUNTIF(NOT is_institutional_outlier) AS eligible_residential_tracts,
        COUNTIF(is_institutional_outlier) AS institutional_outlier_tracts,
        ROUND(APPROX_QUANTILES(km_to_any_care, 100)[OFFSET(50)], 2) AS median_km_to_any_care,
        ROUND(100.0 * COUNTIF(extra_km_if_uninsured <= 0.05) / GREATEST(COUNT(*), 1), 1) AS pct_tracts_zero_uninsured_distance_penalty
    FROM `{tracts_view}`
),
pm_stats AS (
    SELECT
        COUNT(*) AS exposure_2010_tract_rows,
        ROUND(MIN(mean_pm), 2) AS pm25_annual_min_ug_m3,
        ROUND(AVG(mean_pm), 2) AS pm25_annual_mean_ug_m3,
        ROUND(MAX(mean_pm), 2) AS pm25_annual_max_ug_m3,
        ROUND(MAX(max_pm), 1) AS pm25_peak_daily_spike_ug_m3,
        MAX(days_over_35) AS max_days_over_35_ug_m3
    FROM `{project_id}.{BQ_DATASET}.exposure_tracts`
    WHERE STARTS_WITH(LPAD(CAST(geo_id AS STRING), 11, '0'), '{fips}')
),
ed_stats AS (
    SELECT
        COUNT(*) AS nssp_total_weeks,
        COUNT(percent_visits_covid) AS nssp_non_null_covid_weeks,
        COUNT(percent_visits_influenza) AS nssp_non_null_flu_weeks,
        COUNT(percent_visits_rsv) AS nssp_non_null_rsv_weeks
    FROM `{project_id}.{BQ_DATASET}.disease_weekly`
    WHERE CAST(fips AS STRING) IN ('{fips}', '{fips_int_str}')
)
SELECT
    '{fips}' AS county_fips,
    '{escaped_name}' AS county_name,
    '{cfg.state_abbr}' AS state_abbr,
    ('{fips}' = '{PILOT_COUNTY_FIPS}') AS is_pilot_county,
    t.*,
    p.*,
    12.0 AS pm25_cmaq_grid_resolution_km,
    FALSE AS pm25_allowed_in_tract_ranking,
    e.*,
    (e.nssp_non_null_covid_weeks = 0) AS nssp_covid_blind_spot,
    (e.nssp_non_null_covid_weeks = 0 AND e.nssp_non_null_flu_weeks = 0 AND e.nssp_non_null_rsv_weeks = 0) AS nssp_surveillance_blind_spot,
    'Point-of-Care Rapid Molecular Flu A/B, COVID-19 & RSV Testing Kit' AS mandatory_blind_spot_kit
FROM tract_stats t
CROSS JOIN pm_stats p
CROSS JOIN ed_stats e
"""


def build_clean_borough_context_sql(project_id: str = GCP_PROJECT_ID) -> str:
    """Backward-compatible wrapper returning the DDL for `v_clean_borough_context`."""
    return build_clean_county_context_sql(
        project_id=project_id,
        county_fips=COUNTY_FIPS,
        view_name=f"{project_id}.{BQ_DATASET}.v_clean_borough_context",
    )


def build_clean_equity_audit_sql(
    project_id: str = GCP_PROJECT_ID,
    county_fips: str = COUNTY_FIPS,
) -> str:
    """Return the BigQuery DDL to create `a4i_health_audit.v_clean_equity_audit` (Trap 5 Isolated Audit View)."""
    fips = normalize_county_fips(county_fips)
    return f"""
CREATE OR REPLACE VIEW `{project_id}.{BQ_AUDIT_DATASET}.v_clean_equity_audit` AS
WITH clean_tracts AS (
    SELECT
        CAST(b.geo_id AS STRING) AS geo_id,
        CAST(b.total_pop AS INT64) AS total_pop,
        (b.pct_group_quarters > {MAX_GROUP_QUARTERS_PCT} OR b.total_pop < {MIN_RESIDENTIAL_POPULATION}) AS is_institutional_outlier,
        ROUND(IF(e.pct_hispanic < 0, NULL, e.pct_hispanic), 2) AS pct_hispanic,
        ROUND(IF(e.pct_black_nonhisp < 0, NULL, e.pct_black_nonhisp), 2) AS pct_black,
        ROUND(IF(e.pct_black_nonhisp < 0, NULL, e.pct_black_nonhisp), 2) AS pct_black_nonhisp,
        ROUND(
            COALESCE(IF(e.pct_hispanic < 0, 0.0, e.pct_hispanic), 0.0) +
            COALESCE(IF(e.pct_black_nonhisp < 0, 0.0, e.pct_black_nonhisp), 0.0),
            2
        ) AS pct_black_or_hispanic,
        ROUND(IF(e.pct_asian_nonhisp < 0, NULL, e.pct_asian_nonhisp), 2) AS pct_asian,
        ROUND(IF(e.pct_white_nonhisp_est < 0, NULL, e.pct_white_nonhisp_est), 2) AS pct_white,
        ROUND(IF(e.pct_minority < 0, NULL, e.pct_minority), 2) AS pct_minority,
        ROUND(IF(e.pct_below_150pct_poverty < 0, NULL, e.pct_below_150pct_poverty), 2) AS pct_below_150pct_poverty,
        ROUND(IF(e.acs_pct_below_100pct_poverty < 0, NULL, e.acs_pct_below_100pct_poverty), 2) AS pct_poverty,
        ROUND(IF(e.acs_median_hh_income < 0, NULL, e.acs_median_hh_income), 0) AS acs_median_hh_income
    FROM `{project_id}.{BQ_DATASET}.burden_tracts` b
    INNER JOIN `{project_id}.{BQ_AUDIT_DATASET}.equity_audit_tracts` e
      ON CAST(b.geo_id AS STRING) = CAST(e.geo_id AS STRING)
    WHERE STARTS_WITH(CAST(b.geo_id AS STRING), '{fips}')
      AND b.total_pop > 0
),
borough_baseline AS (
    SELECT
        ROUND(SAFE_DIVIDE(SUM(total_pop * pct_hispanic), SUM(total_pop)), 2) AS county_baseline_pct_hispanic,
        ROUND(SAFE_DIVIDE(SUM(total_pop * pct_black), SUM(total_pop)), 2) AS county_baseline_pct_black,
        ROUND(SAFE_DIVIDE(SUM(total_pop * pct_black_or_hispanic), SUM(total_pop)), 2) AS county_baseline_pct_black_or_hispanic,
        ROUND(SAFE_DIVIDE(SUM(total_pop * pct_poverty), SUM(total_pop)), 2) AS county_baseline_pct_poverty,
        ROUND(SAFE_DIVIDE(SUM(total_pop * pct_below_150pct_poverty), SUM(total_pop)), 2) AS county_baseline_pct_below_150pct_poverty
    FROM clean_tracts
)
SELECT
    c.*,
    base.county_baseline_pct_hispanic,
    base.county_baseline_pct_black,
    base.county_baseline_pct_black_or_hispanic,
    base.county_baseline_pct_poverty,
    base.county_baseline_pct_below_150pct_poverty
FROM clean_tracts c
CROSS JOIN borough_baseline base
"""


def enrich_tracts_with_landmarks(
    df: pd.DataFrame,
    county_fips: str = COUNTY_FIPS,
) -> pd.DataFrame:
    """Attach neighborhood, landmark, intersection, and transit lines to each tract."""
    fips = normalize_county_fips(county_fips)
    df = df.copy()
    neighborhoods, landmarks, intersections, subways, buses, corridors = [], [], [], [], [], []
    for _, row in df.iterrows():
        ctx = lookup_tract_landmark_context(
            str(row["geo_id"]),
            float(row["lat"]) if pd.notna(row.get("lat")) else None,
            float(row["lon"]) if pd.notna(row.get("lon")) else None,
            county_fips=fips,
        )
        neighborhoods.append(ctx["neighborhood"])
        landmarks.append(ctx["landmark_name"])
        intersections.append(ctx["street_intersection"])
        subways.append(json.dumps(ctx["subway_lines"]))
        buses.append(json.dumps(ctx["bus_lines"]))
        corridors.append(ctx["sub_corridor"])

    df["neighborhood"] = neighborhoods
    df["landmark_name"] = landmarks
    df["street_intersection"] = intersections
    df["subway_lines_json"] = subways
    df["bus_lines_json"] = buses
    df["sub_corridor"] = corridors
    return df


def export_tracts_geojson(
    tracts_df: pd.DataFrame,
    project_id: str = GCP_PROJECT_ID,
    county_fips: str = COUNTY_FIPS,
) -> dict[str, Any]:
    """Query 2020 polygon geometries from `svi_supplement_tracts` (with US Census boundary fallback) and write GeoJSON cache."""
    fips = normalize_county_fips(county_fips)
    paths = get_cache_paths(fips)
    sql = f"""
    SELECT
        CAST(geo_id AS STRING) AS geo_id,
        ST_AsGeoJSON(ST_Simplify(tract_geom, 15.0)) AS geometry_json
    FROM `{project_id}.{BQ_DATASET}.svi_supplement_tracts`
    WHERE STARTS_WITH(CAST(geo_id AS STRING), '{fips}')
      AND tract_geom IS NOT NULL
    """
    try:
        geom_df = run_query_df(sql)
    except Exception:
        geom_df = pd.DataFrame()

    if geom_df.empty:
        fallback_sql = f"""
        SELECT
            CAST(geo_id AS STRING) AS geo_id,
            ST_AsGeoJSON(ST_Simplify(tract_geom, 15.0)) AS geometry_json
        FROM `bigquery-public-data.geo_us_boundaries.census_tracts`
        WHERE state_fips_code = '{fips[:2]}'
          AND county_fips_code = '{fips[2:]}'
          AND tract_geom IS NOT NULL
        """
        geom_df = run_query_df(fallback_sql)

    geom_map = {str(r["geo_id"]): json.loads(r["geometry_json"]) for _, r in geom_df.iterrows()}

    features: list[dict[str, Any]] = []
    for _, row in tracts_df.iterrows():
        gid = str(row["geo_id"])
        geom = geom_map.get(gid)
        if not geom:
            continue
        props = {
            "geo_id": gid,
            "neighborhood": str(row.get("neighborhood", "")),
            "sub_corridor": str(row.get("sub_corridor", "")),
            "hpsa_name": str(row.get("hpsa_name", "")),
            "hpsa_score": int(row.get("hpsa_score", 0) or 0),
            "total_pop": int(row.get("total_pop", 0) or 0),
            "composite_need_score": float(row.get("composite_need_score", 0.0) or 0.0),
            "pct_uninsured": float(row.get("pct_uninsured", 0.0) or 0.0),
            "pct_asthma": float(row.get("pct_asthma", 0.0) or 0.0),
            "pct_diabetes": float(row.get("pct_diabetes", 0.0) or 0.0),
            "pct_high_bp": float(row.get("pct_high_bp", 0.0) or 0.0),
            "pct_group_quarters": float(row.get("pct_group_quarters", 0.0) or 0.0),
            "safety_net_weekly_hours_1km": float(row.get("safety_net_weekly_hours_1km", 0.0) or 0.0),
            "is_institutional_outlier": bool(row.get("is_institutional_outlier", False)),
            "outlier_category": str(row.get("outlier_category", "RESIDENTIAL_ELIGIBLE")),
            "outlier_rejection_reason": str(row.get("outlier_rejection_reason", "")),
        }
        features.append({"type": "Feature", "id": gid, "properties": props, "geometry": geom})

    fc = {"type": "FeatureCollection", "features": features}
    paths["tracts_geojson"].parent.mkdir(parents=True, exist_ok=True)
    geojson_text = json.dumps(fc)
    paths["tracts_geojson"].write_text(geojson_text, encoding="utf-8")
    if paths["tracts_county_geojson"] != paths["tracts_geojson"]:
        paths["tracts_county_geojson"].write_text(geojson_text, encoding="utf-8")
    return fc


def export_bronx_tracts_geojson(tracts_df: pd.DataFrame, project_id: str = GCP_PROJECT_ID) -> dict[str, Any]:
    """Backward-compatible alias for `export_tracts_geojson`."""
    return export_tracts_geojson(tracts_df=tracts_df, project_id=project_id, county_fips=COUNTY_FIPS)


def run_dataset_cleaner(
    project_id: str = GCP_PROJECT_ID,
    county_fips: str = COUNTY_FIPS,
    export_cache: bool = True,
) -> dict[str, Any]:
    """Execute the Dataset Cleaner pipeline in BigQuery for `county_fips` and export local caches."""
    fips = normalize_county_fips(county_fips)
    cfg = get_county_config(fips)
    paths = get_cache_paths(fips)
    client = get_bq_client(project_id)

    tracts_view_bronx = f"{project_id}.{BQ_DATASET}.v_clean_bronx_tracts"
    tracts_alias_bronx_2020 = f"{project_id}.{BQ_DATASET}.bronx_tracts_2020"
    tracts_view_generic = f"{project_id}.{BQ_DATASET}.v_clean_tracts"
    care_sites_view = f"{project_id}.{BQ_DATASET}.v_clean_care_sites"
    context_view_borough = f"{project_id}.{BQ_DATASET}.v_clean_borough_context"
    context_view_generic = f"{project_id}.{BQ_DATASET}.v_clean_county_context"
    equity_audit_view = f"{project_id}.{BQ_AUDIT_DATASET}.v_clean_equity_audit"

    # 1. Materialize both county-agnostic and backward-compatible BigQuery views
    views_ddl = {
        tracts_view_bronx: build_clean_tracts_sql(project_id, fips, view_name=tracts_view_bronx),
        tracts_alias_bronx_2020: f"CREATE OR REPLACE VIEW `{tracts_alias_bronx_2020}` AS SELECT * FROM `{tracts_view_bronx}`",
        tracts_view_generic: build_clean_tracts_sql(project_id, fips, view_name=tracts_view_generic),
        care_sites_view: build_clean_care_sites_sql(project_id, fips),
        context_view_borough: build_clean_county_context_sql(project_id, fips, view_name=context_view_borough),
        context_view_generic: build_clean_county_context_sql(project_id, fips, view_name=context_view_generic),
        equity_audit_view: build_clean_equity_audit_sql(project_id, fips),
    }
    for view_name, ddl in views_ddl.items():
        logger.info("Materializing BigQuery view: %s (county=%s)", view_name, fips)
        client.query(ddl).result()

    # 2. Fetch and enrich cleaned DataFrames and export local Parquet/JSON/GeoJSON caches
    tracts_df = run_query_df(f"SELECT * FROM `{tracts_view_generic}` ORDER BY composite_need_score DESC")
    tracts_df = enrich_tracts_with_landmarks(tracts_df, county_fips=fips)
    care_sites_df = run_query_df(f"SELECT * FROM `{care_sites_view}` ORDER BY site_id")
    equity_df = run_query_df(f"SELECT * FROM `{equity_audit_view}` ORDER BY geo_id")
    context_df = run_query_df(f"SELECT * FROM `{context_view_generic}` LIMIT 1")
    context_dict = context_df.iloc[0].to_dict() if not context_df.empty else {}

    geojson_fc: dict[str, Any] = {"type": "FeatureCollection", "features": []}
    if export_cache:
        paths["tracts_parquet"].parent.mkdir(parents=True, exist_ok=True)
        tracts_df.to_parquet(paths["tracts_parquet"], index=False)
        if paths["tracts_county_parquet"] != paths["tracts_parquet"]:
            tracts_df.to_parquet(paths["tracts_county_parquet"], index=False)

        care_sites_df.to_parquet(paths["care_sites_parquet"], index=False)
        if paths["care_sites_county_parquet"] != paths["care_sites_parquet"]:
            care_sites_df.to_parquet(paths["care_sites_county_parquet"], index=False)

        equity_df.to_parquet(paths["equity_audit_parquet"], index=False)
        if paths["equity_audit_county_parquet"] != paths["equity_audit_parquet"]:
            equity_df.to_parquet(paths["equity_audit_county_parquet"], index=False)

        context_json_str = json.dumps(context_dict, indent=2, default=str)
        paths["context_json"].write_text(context_json_str, encoding="utf-8")
        if paths["context_county_json"] != paths["context_json"]:
            paths["context_county_json"].write_text(context_json_str, encoding="utf-8")

        geojson_fc = export_tracts_geojson(tracts_df, project_id=project_id, county_fips=fips)

    eligible_df = tracts_df[~tracts_df["is_institutional_outlier"]]
    outliers_df = tracts_df[tracts_df["is_institutional_outlier"]]

    return {
        "status": "SUCCESS",
        "county_fips": fips,
        "county_name": cfg.county_name,
        "is_pilot_county": cfg.is_pilot,
        "views_materialized": list(views_ddl.keys()),
        "total_populated_tracts": len(tracts_df),
        "eligible_residential_tracts": len(eligible_df),
        "institutional_outlier_tracts": len(outliers_df),
        "imputed_svi_tracts": int(tracts_df["has_imputed_svi"].sum()) if "has_imputed_svi" in tracts_df else 0,
        "care_sites_cleaned": len(care_sites_df),
        "equity_audit_tracts_cleaned": len(equity_df),
        "geojson_polygons_exported": len(geojson_fc["features"]),
        "county_context": context_dict,
        "borough_context": context_dict,
    }
