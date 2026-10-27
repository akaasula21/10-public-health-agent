import re
from pathlib import Path

# 1. Update agent/prompts.py
prompts_path = Path("agent/prompts.py")
content = prompts_path.read_text(encoding="utf-8")

target = """- You cite exact data tables, schemas, GEOIDs, and statistical percentiles from `qwiklabs-gcp-03-c81d344a3430.a4i_health`.
- You never overstate precision. When data is missing or coarse, you state it plainly and explain the operational mitigation."""

replacement = """- You cite exact data tables, schemas, GEOIDs, and statistical percentiles from `qwiklabs-gcp-03-c81d344a3430.a4i_health`.
- You never overstate precision. When data is missing or coarse, you state it plainly and explain the operational mitigation.

BIGQUERY DATA SCHEMAS AVAILABLE IN `qwiklabs-gcp-03-c81d344a3430.a4i_health`:
When issuing read-only queries with `run_director_bigquery_sql`, query these exact views/tables:
- `v_clean_bronx_tracts` (also aliased as `bronx_tracts_2020`): Contains all 347 Bronx census tracts. Key columns: `geo_id`, `total_pop`, `composite_need_score`, `pct_uninsured`, `pct_asthma`, `pct_diabetes`, `pct_high_bp`, `pct_copd`, `hpsa_name`, `hpsa_score`, `safety_net_weekly_hours_1km`, `uninsured_adults_per_weekly_clinic_hr_1km`, `pct_group_quarters`, `is_institutional_outlier`, `neighborhood`, `sub_corridor`.
- `v_clean_care_sites`: 159 care sites with `site_id`, `site_name`, `address`, `facility_type`, `weekly_hours`, `hours_tier`, `lat`, `lon`.
- `v_clean_county_context` (and `v_clean_borough_context`): 1 row containing borough metadata, 12 km grid caveat for PM2.5, and NSSP ED respiratory surveillance blind spot documentation.
- `exposure_tracts`: Annual satellite PM2.5 metrics across 12 km grid.
- `disease_weekly`: NSSP weekly respiratory surveillance data (100% missing for Bronx County)."""

content_norm = content.replace("\r\n", "\n")
target_norm = target.replace("\r\n", "\n")
replacement_norm = replacement.replace("\r\n", "\n")
if target_norm in content_norm:
    content_norm = content_norm.replace(target_norm, replacement_norm)
    prompts_path.write_text(content_norm, encoding="utf-8")
    print("agent/prompts.py updated successfully.")
else:
    print("WARNING: target not found in agent/prompts.py")

# 2. Update agent/data/cleaner.py to include bronx_tracts_2020 view
cleaner_path = Path("agent/data/cleaner.py")
cleaner_content = cleaner_path.read_text(encoding="utf-8").replace("\r\n", "\n")

cleaner_target = """    tracts_view_bronx = f"{project_id}.{BQ_DATASET}.v_clean_bronx_tracts"
    tracts_view_generic = f"{project_id}.{BQ_DATASET}.v_clean_tracts"
    care_sites_view = f"{project_id}.{BQ_DATASET}.v_clean_care_sites"
    context_view_borough = f"{project_id}.{BQ_DATASET}.v_clean_borough_context"
    context_view_generic = f"{project_id}.{BQ_DATASET}.v_clean_county_context"
    equity_audit_view = f"{project_id}.{BQ_AUDIT_DATASET}.v_clean_equity_audit"

    # 1. Materialize both county-agnostic and backward-compatible BigQuery views
    views_ddl = {
        tracts_view_bronx: build_clean_tracts_sql(project_id, fips, view_name=tracts_view_bronx),
        tracts_view_generic: build_clean_tracts_sql(project_id, fips, view_name=tracts_view_generic),
        care_sites_view: build_clean_care_sites_sql(project_id, fips),
        context_view_borough: build_clean_county_context_sql(project_id, fips, view_name=context_view_borough),
        context_view_generic: build_clean_county_context_sql(project_id, fips, view_name=context_view_generic),
        equity_audit_view: build_clean_equity_audit_sql(project_id, fips),
    }"""

cleaner_replacement = """    tracts_view_bronx = f"{project_id}.{BQ_DATASET}.v_clean_bronx_tracts"
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
    }"""

if cleaner_target in cleaner_content:
    cleaner_content = cleaner_content.replace(cleaner_target, cleaner_replacement)
    cleaner_path.write_text(cleaner_content, encoding="utf-8")
    print("agent/data/cleaner.py updated successfully.")
else:
    print("WARNING: cleaner_target not found in agent/data/cleaner.py")

# 3. Update agent/tools/bq_scoring.py
bq_scoring_path = Path("agent/tools/bq_scoring.py")
scoring_content = bq_scoring_path.read_text(encoding="utf-8").replace("\r\n", "\n")

scoring_target = """    # Fallback to local query engine if available
    try:
        df = run_query_df(cleaned)
        records = df.head(50).to_dict(orient="records")
        return {"row_count": len(df), "rows": json.loads(json.dumps(records, default=str))}
    except Exception as exc:
        return {"error": str(exc)}"""

scoring_replacement = """    # Fallback to local query engine if available
    try:
        fallback_query = re.sub(r"\\bbronx_tracts_2020\\b", "v_clean_bronx_tracts", cleaned, flags=re.IGNORECASE)
        df = run_query_df(fallback_query)
        records = df.head(50).to_dict(orient="records")
        return {"row_count": len(df), "rows": json.loads(json.dumps(records, default=str))}
    except Exception as exc:
        return {"error": str(exc)}"""

if scoring_target in scoring_content:
    scoring_content = scoring_content.replace(scoring_target, scoring_replacement)
    bq_scoring_path.write_text(scoring_content, encoding="utf-8")
    print("agent/tools/bq_scoring.py updated successfully.")
else:
    print("WARNING: scoring_target not found in agent/tools/bq_scoring.py")
