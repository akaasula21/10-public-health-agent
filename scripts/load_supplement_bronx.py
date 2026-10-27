#!/usr/bin/env python3
"""
Colab Enterprise Data Loader: Bronx (36005) Pilot + Supplemental Datasets
Agents for Impact 2026 — Challenge 5: Dynamic Public Health Equity & Mobile Care Broker

What this script does:
1. Authenticates in Colab Enterprise (via google.auth.default() with pydata_google_auth fallback)
   and ensures the 8 core tables in `<PROJECT>.a4i_health` are populated for Bronx County, NY (36005).
2. Loads all vetted, license-clean (17 U.S.C. § 105 Public Domain / CC0) supplemental tables
   for the Bronx pilot (excluding transit, food access, and CEJST per project scope):
     - `a4i_health.places_supplement_tracts`      (CDC PLACES 2025 95% CIs parsed to numeric
                                                   low/high bounds, non-food HRSNs, screenings)
     - `a4i_health.svi_supplement_tracts`         (CDC SVI 2022 non-racial E_DAYPOP daytime pop,
                                                   EPL_* percentiles, crowding/multi-unit, and
                                                   2020-vintage tract polygon geometries)
     - `a4i_health.tract_neighbors`               (Exact bordering neighbor tracts via 2020 polygon
                                                   ST_TOUCHES/ST_INTERSECTS + centroid distance)
     - `a4i_health.shortage_areas_all_disciplines`(HRSA Primary Care, Dental, and Mental Health
                                                   designated HPSA component scores per tract)
     - `a4i_health.shortage_mua_tracts`           (HRSA Medically Underserved Areas/Populations
                                                   IMU score spatially joined to Bronx tracts)
     - `a4i_health.exposure_supplement_tracts`    (EPA/CDC PM2.5 prediction standard error
                                                   ds_pm_stdd + Daily Tract-Level Ozone hf2a-3ebq)
     - `a4i_health.climate_heat_risk_tracts`      (FEMA National Risk Index Heat Wave & Cold Wave
                                                   tract-level risk scores & resilience)
     - `a4i_health.noaa_seasonal_heat`            (BigQuery Public Data NOAA GSOD monthly heat
                                                   extremes for NYC/Bronx weather stations)
     - `a4i_health.tract_access_bronx_enhanced`   (Cross-county-border distances via care_sites_state
                                                   + clinic operating-hours capacity within 1km/2km)
     - `a4i_health.planner_tract_features`        (Unified, race-free siting table for Planner Agent)
3. Creates a SEPARATE, ACCESS-RESTRICTED BigQuery dataset (`<PROJECT>.a4i_health_audit`) for the
   post-hoc Equity Auditor Agent:
     - `a4i_health_audit.equity_audit_tracts`     (CDC SVI 2022 Theme 3 racial/ethnic minority columns
                                                   + overall RPL_THEMES + poverty/housing burden +
                                                   US Census ACS 5-yr median income, rent & Gini)
     - `a4i_health_audit.v_bronx_equity_baseline` (Authorized view comparing any tract to Bronx
                                                   population-weighted demographic averages)
   And enforces BigQuery dataset-level and table-level access restrictions so the Siting/Planner
   Agent cannot access racial/ethnic attributes.
"""

import contextlib
import json
import math
import os
import random
import re
import sys
import time
import pandas as pd
import requests
import google.auth
from google.cloud import bigquery

# ==============================================================================
# 1. CONFIGURATION (Bronx County, NY Pilot)
# ==============================================================================
COUNTY_FIPS = "36005"          # Bronx County, New York
COUNTY_NAME = "Bronx"
STATE_ABBR  = "NY"
STATE_FIPS  = COUNTY_FIPS[:2]  # "36"
COUNTY_ONLY = COUNTY_FIPS[2:]  # "005"

DATASET       = "a4i_health"         # Planner / Siting dataset (RACE-FREE)
AUDIT_DATASET = "a4i_health_audit"   # Restricted Equity Audit dataset (AUDITOR ONLY)
LOCATION      = "US"

# Optional: set separate service account emails if deploying distinct IAM principals
# for the Planner Agent vs. the Equity Auditor Agent.
# Example: "serviceAccount:siting-planner@<project>.iam.gserviceaccount.com"
PLANNER_PRINCIPAL = os.environ.get("A4I_PLANNER_PRINCIPAL", "")
AUDITOR_PRINCIPAL = os.environ.get("A4I_AUDITOR_PRINCIPAL", "")

SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


def get_bq_client():
    """Authenticate cleanly in Colab Enterprise, Vertex AI Workbench, or local environments."""
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "qwiklabs-gcp-03-c81d344a3430")
    creds = None
    try:
        creds, default_proj = google.auth.default(scopes=SCOPES)
        if default_proj and not os.environ.get("GOOGLE_CLOUD_PROJECT"):
            project = default_proj
    except Exception:
        pass

    if creds is None:
        import pydata_google_auth
        creds = pydata_google_auth.get_user_credentials(SCOPES, use_local_webserver=True)

    return bigquery.Client(project=project, location=LOCATION, credentials=creds), project


bq, PROJECT = get_bq_client()

print(f"project       : {PROJECT}")
print(f"pilot county  : {COUNTY_NAME} ({COUNTY_FIPS}), state FIPS {STATE_FIPS} ({STATE_ABBR})")
print(f"siting dataset: {PROJECT}.{DATASET} (race-free)")
print(f"audit dataset : {PROJECT}.{AUDIT_DATASET} (restricted access)")


# ==============================================================================
# 2. TIMING, VALIDATION HARNESS & HTTP/ARCGIS/SOCRATA HELPERS
# ==============================================================================
STEPS, CHECKS = {}, []
UA = {"User-Agent": "A4I2026-challenge5-bronx-supplement"}


@contextlib.contextmanager
def step(name):
    t0 = time.time()
    print(f"\n[{name}] ...")
    try:
        yield
    finally:
        dt = time.time() - t0
        STEPS[name] = round(dt, 1)
        print(f"[{name}] {dt:.1f}s")


def _record(name, verdict, detail):
    for c in CHECKS:
        if c["check"] == name:
            c["verdict"], c["detail"] = verdict, detail
            return
    CHECKS.append({"check": name, "verdict": verdict, "detail": detail})


def check(name, ok, detail=""):
    _record(name, "PASS" if ok else "FAIL", detail)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f": {detail}" if detail else ""))
    return bool(ok)


def note(name, bad, total, detail="", limit=0.01):
    frac = (bad / total) if total else 0.0
    verdict = "PASS" if bad == 0 else ("FAIL" if (total and frac > limit) else "WARN")
    _record(name, verdict, detail or (f"{bad:,} of {total:,}" if total else f"{bad:,}"))
    print(f"  {verdict}  {name}" + (f": {detail}" if detail else ""))
    return verdict


def safe_str(s, width=None):
    out = s.astype("string")
    if width:
        out = out.str.strip().str.zfill(width)
    return out.where(out.notna(), None)


def get_json(url, params=None, tries=4, timeout=180):
    delay = 2.0
    for attempt in range(tries):
        try:
            r = requests.get(url, params=params, timeout=timeout, headers=UA)
        except Exception as e:
            if attempt == tries - 1:
                raise RuntimeError(f"{url}—{type(e).__name__}: {e}")
            time.sleep(delay)
            delay *= 2
            continue
        if r.status_code == 429 or 500 <= r.status_code < 600:
            if attempt == tries - 1:
                raise RuntimeError(f"{url}—HTTP {r.status_code} after {tries} tries")
            time.sleep(delay)
            delay *= 2
            continue
        if r.status_code != 200:
            raise RuntimeError(f"{url}—HTTP {r.status_code}: {r.text[:300]}")
        ctype = r.headers.get("content-type", "")
        if "json" not in ctype.lower():
            raise RuntimeError(f"{url}—expected JSON, got {ctype!r}: {r.text[:200]!r}")
        return r.json()
    raise RuntimeError(f"{url}—exhausted retries")


def _select_columns(select):
    parts, depth, cur = [], 0, ""
    for ch in select:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    names = []
    for p in parts:
        p = p.strip()
        low = p.lower()
        if " as " in low:
            p = p[low.rindex(" as ") + 4:].strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", p):
            names.append(p)
    return names


def soda(dataset_id, params, page=50000):
    url = f"https://data.cdc.gov/resource/{dataset_id}.json"
    out, offset = [], 0
    while True:
        p = dict(params)
        p["$limit"] = page
        p["$offset"] = offset
        chunk = get_json(url, p)
        out.extend(chunk)
        if len(chunk) < page:
            break
        offset += page

    df = pd.DataFrame(out)
    missing = [c for c in _select_columns(params.get("$select", "")) if c not in df.columns]
    if missing and len(df):
        print(f"    (county has NO value for: {', '.join(missing)} — filled as NULL)")
        for c in missing:
            df[c] = None
    return df


DETERMINISTIC_ARCGIS = (
    "cannot find field", "invalid field", "parsing", "invalid expression",
    "invalid where", "does not support", "not supported"
)


class ArcGISTransient(RuntimeError):
    pass


def arcgis_query(layer_url, params, tries=5, label="query", passthrough=()):
    delay = 3.0
    last = None
    for attempt in range(tries):
        d = get_json(layer_url + "/query", params)
        err = d.get("error")
        if not err:
            return d
        last = err
        low = str(err).lower()
        if any(k in low for k in passthrough):
            return d
        if any(k in low for k in DETERMINISTIC_ARCGIS):
            raise RuntimeError(f"{layer_url} {label} failed deterministically: {err}")
        if attempt < tries - 1:
            time.sleep(delay + random.uniform(0, delay / 2))
            delay *= 2
    raise ArcGISTransient(f"{layer_url} {label}—{last} after {tries} tries")


def arcgis_all(layer_url, where, out_fields, order=None, page=1000, return_geometry=False, out_sr="4326"):
    rows, offset = [], 0
    while True:
        p = {
            "where": where,
            "outFields": out_fields,
            "returnGeometry": "true" if return_geometry else "false",
            "f": "json",
            "resultOffset": offset,
            "resultRecordCount": page,
        }
        if return_geometry and out_sr:
            p["outSR"] = out_sr
        if order:
            p["orderByFields"] = order
        d = arcgis_query(layer_url, p, label=f"rows at offset {offset}")
        feats = d.get("features", [])
        for f in feats:
            rec = dict(f.get("attributes") or {})
            if return_geometry:
                rec["_geometry"] = f.get("geometry")
            rows.append(rec)
        if len(feats) < page:
            break
        offset += page
    return pd.DataFrame(rows)


def arcgis_points(layer_url, where, out_fields, page=1000, id_chunk=450, url_budget=3000):
    meta = get_json(layer_url, {"f": "json"})
    can_page = bool((meta.get("advancedQueryCapabilities") or {}).get("supportsPagination"))
    base = {"where": where, "outFields": out_fields, "returnGeometry": "true", "f": "json"}

    def _rows(d):
        out = []
        for f in d.get("features", []):
            a = dict(f["attributes"])
            g = f.get("geometry") or {}
            a["longitude"], a["latitude"] = g.get("x"), g.get("y")
            out.append(a)
        return out

    if can_page:
        rows, offset = [], 0
        while True:
            d = arcgis_query(
                layer_url,
                {**base, "resultOffset": offset, "resultRecordCount": page},
                label=f"page at offset {offset}",
                passthrough=("pagination",),
            )
            if d.get("error"):
                can_page = False
                break
            feats = d.get("features", [])
            rows.extend(_rows(d))
            if len(feats) < page:
                return pd.DataFrame(rows)
            offset += page

    d = arcgis_query(layer_url, {"where": where, "returnIdsOnly": "true", "f": "json"}, label="id list")
    oid_field = d.get("objectIdFieldName", "OBJECTID")
    oids = d.get("objectIds") or []
    rows, i, chunk = [], 0, min(id_chunk, page)
    while i < len(oids):
        while chunk > 25 and len(",".join(str(o) for o in oids[i:i + chunk])) > url_budget:
            chunk = max(25, int(chunk * 0.8))
        idlist = ",".join(str(o) for o in oids[i:i + chunk])
        c = arcgis_query(layer_url, {**base, "where": f"{oid_field} IN ({idlist})"}, label=f"ids {i}-{i + chunk}")
        rows.extend(_rows(c))
        i += chunk
    return pd.DataFrame(rows)


def esri_rings_to_geojson(geom):
    """Convert Esri polygon rings (in WGS84 lon/lat) to a GeoJSON Polygon/MultiPolygon string
    that BigQuery `ST_GEOGFROMGEOJSON(..., make_valid => TRUE)` can ingest directly."""
    if not geom or not geom.get("rings"):
        return None
    rings = geom["rings"]
    if len(rings) == 1:
        return json.dumps({"type": "Polygon", "coordinates": rings})
    # Represent multiple rings as MultiPolygon of single-ring polygons so BigQuery
    # make_valid => TRUE resolves islands and interior holes cleanly.
    return json.dumps({"type": "MultiPolygon", "coordinates": [[r] for r in rings]})


def parse_ci_pair(series):
    """Parse CDC PLACES confidence interval strings like '(11.4, 13.1)' into (low, high) floats."""
    lows, highs = [], []
    pat = re.compile(r"[-+]?\d*\.?\d+")
    for val in series:
        if pd.isna(val):
            lows.append(None)
            highs.append(None)
            continue
        nums = pat.findall(str(val))
        if len(nums) >= 2:
            lows.append(float(nums[0]))
            highs.append(float(nums[1]))
        else:
            lows.append(None)
            highs.append(None)
    return pd.Series(lows, dtype="float64"), pd.Series(highs, dtype="float64")


def load_df(df, table, dataset=DATASET, schema=None, description=None, labels=None):
    ref = f"{PROJECT}.{dataset}.{table}"
    df = df.copy()
    for c in df.columns:
        if df[c].isna().all() and df[c].dtype == "object":
            df[c] = df[c].astype("string")

    cfg = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
    if schema:
        cfg.schema = schema
    bq.load_table_from_dataframe(df, ref, job_config=cfg).result()

    tbl = bq.get_table(ref)
    if description or labels:
        if description:
            tbl.description = description
        if labels:
            tbl.labels = labels
        bq.update_table(tbl, ["description", "labels"])
    print(f"  loaded {ref}: {tbl.num_rows:,} rows ({len(df.columns)} cols)")
    return tbl.num_rows


# ==============================================================================
# 3. ENSURE DATASETS EXIST & CONFIGURE RESTRICTED EQUITY AUDIT ACCESS
# ==============================================================================
with step("create datasets and enforce equity audit access restrictions"):
    # 1. Verify county FIPS against BigQuery public boundaries
    _c = bq.query(f"""
        SELECT county_name
        FROM `bigquery-public-data.geo_us_boundaries.counties`
        WHERE geo_id = '{COUNTY_FIPS}'
    """).to_dataframe()
    if len(_c) != 1 or _c.county_name[0].lower() != COUNTY_NAME.lower():
        raise RuntimeError(f"County verification failed for {COUNTY_FIPS} ({COUNTY_NAME})")

    # 2. Ensure main siting dataset (`a4i_health`) exists
    ds_main = bigquery.Dataset(f"{PROJECT}.{DATASET}")
    ds_main.location = LOCATION
    ds_main.description = (
        "A4I 2026 Challenge 5 — Siting / Planner dataset for Bronx (36005). "
        "Strictly excludes racial and ethnic demographic variables."
    )
    bq.create_dataset(ds_main, exists_ok=True)
    print(f"  dataset {PROJECT}.{DATASET} ready")

    # 3. Ensure restricted Equity Audit dataset (`a4i_health_audit`) exists
    ds_audit = bigquery.Dataset(f"{PROJECT}.{AUDIT_DATASET}")
    ds_audit.location = LOCATION
    ds_audit.description = (
        "RESTRICTED: Post-Hoc Equity Audit dataset for Bronx (36005). "
        "Accessible ONLY to the Accountability / Equity Auditor Agent. "
        "Prohibited as an input to the Siting / Planner Agent."
    )
    ds_audit = bq.create_dataset(ds_audit, exists_ok=True)

    # 4. Restrict access on `a4i_health_audit`:
    #    - Strip broad project-wide reader groups (`projectReaders`, `allAuthenticatedUsers`,
    #      and any `PLANNER_PRINCIPAL`) from `a4i_health_audit` access entries while preserving
    #      dataset owners (`projectOwners` / current user) and adding `AUDITOR_PRINCIPAL` if set.
    ds_audit = bq.get_dataset(f"{PROJECT}.{AUDIT_DATASET}")
    restricted_entries = []
    removed_entries = []
    for entry in ds_audit.access_entries:
        if entry.entity_id in ("allAuthenticatedUsers", "allUsers", "projectReaders", "projectViewers"):
            removed_entries.append(f"{entry.role}:{entry.entity_id}")
            continue
        if PLANNER_PRINCIPAL and entry.entity_id == PLANNER_PRINCIPAL.split(":")[-1]:
            removed_entries.append(f"{entry.role}:{entry.entity_id}")
            continue
        restricted_entries.append(entry)

    if AUDITOR_PRINCIPAL:
        entity_type = "userByEmail" if not AUDITOR_PRINCIPAL.startswith("group:") else "groupByEmail"
        principal_email = AUDITOR_PRINCIPAL.split(":")[-1]
        restricted_entries.append(
            bigquery.AccessEntry(
                role="READER",
                entity_type=entity_type,
                entity_id=principal_email,
            )
        )

    if restricted_entries:
        ds_audit.access_entries = restricted_entries
        ds_audit.labels = {
            "access_tier": "restricted_equity_audit",
            "planner_access": "denied",
            "auditor_access": "allowed",
        }
        bq.update_dataset(ds_audit, ["access_entries", "labels", "description"])
        print(f"  restricted ACL applied to {PROJECT}.{AUDIT_DATASET} "
              f"(removed broad readers: {removed_entries or 'already clean'})")


# ==============================================================================
# 4. CHECK (AND IF NEEDED, BOOTSTRAP) BASE TABLES FOR BRONX (36005)
# ==============================================================================
with step("verify (or bootstrap) base a4i_health tables for Bronx (36005)"):
    existing_tables = {t.table_id for t in bq.list_tables(f"{PROJECT}.{DATASET}")}
    required_base = {
        "burden_tracts", "exposure_tracts", "care_sites", "care_sites_state",
        "shortage_areas", "shortage_facilities", "disease_weekly", "tract_access"
    }
    missing_base = sorted(required_base - existing_tables)
    need_base_reload = bool(missing_base)
    if not need_base_reload:
        n_bronx = list(bq.query(
            f"SELECT COUNTIF(STARTS_WITH(geo_id, '{COUNTY_FIPS}')) FROM `{PROJECT}.{DATASET}.burden_tracts`"
        ).result())[0][0]
        if n_bronx == 0:
            need_base_reload = True
        else:
            print(f"  all 8 base tables already present for Bronx ({COUNTY_FIPS}: {n_bronx:,} tracts)—reusing")

    if need_base_reload:
        print(f"  bootstrapping base tables for {COUNTY_NAME} ({COUNTY_FIPS}) (missing: {missing_base or 'county mismatch'})...")
        # 4a. Base `burden_tracts` (PLACES + SVI Themes 1, 2, 4 — strictly excluding Theme 3)
        b_raw = soda("yjkw-uj5s", {
            "$select": (
                "tractfips, totalpopulation, geolocation, "
                "access2_crudeprev, casthma_crudeprev, copd_crudeprev, "
                "diabetes_crudeprev, bphigh_crudeprev, checkup_crudeprev, "
                "mobility_crudeprev_, selfcare_crudeprev, indeplive_crudeprev, "
                "disability_crudeprev, lacktrpt_crudeprev"
            ),
            "$where": f"countyfips='{COUNTY_FIPS}'",
        }, page=5000)
        b_df = b_raw.rename(columns={
            "tractfips": "geo_id", "totalpopulation": "total_pop",
            "access2_crudeprev": "pct_uninsured", "casthma_crudeprev": "pct_asthma",
            "copd_crudeprev": "pct_copd", "diabetes_crudeprev": "pct_diabetes",
            "bphigh_crudeprev": "pct_high_bp", "checkup_crudeprev": "pct_checkup",
            "mobility_crudeprev_": "pct_mobility_difficulty",
            "selfcare_crudeprev": "pct_selfcare_difficulty",
            "indeplive_crudeprev": "pct_indep_living_difficulty",
            "disability_crudeprev": "pct_any_disability",
            "lacktrpt_crudeprev": "pct_lack_transport",
        }).copy()
        b_df["longitude"] = b_df["geolocation"].apply(lambda g: g["coordinates"][0] if isinstance(g, dict) and g.get("coordinates") else None)
        b_df["latitude"]  = b_df["geolocation"].apply(lambda g: g["coordinates"][1] if isinstance(g, dict) and g.get("coordinates") else None)
        b_df = b_df.drop(columns=["geolocation"])
        b_df["geo_id"] = safe_str(b_df["geo_id"], width=11)
        for c in b_df.columns:
            if c.startswith("pct_") or c in ("total_pop", "longitude", "latitude"):
                b_df[c] = pd.to_numeric(b_df[c], errors="coerce")

        svi_base_url = (
            "https://onemap.cdc.gov/onemapservices/rest/services/SVI/"
            "CDC_ATSDR_Social_Vulnerability_Index_2022_USA/MapServer/2"
        )
        svi_base_cols = [
            "FIPS", "E_TOTPOP", "EP_NOVEH", "EPL_NOVEH", "EP_DISABL", "EP_AGE65",
            "EP_AGE17", "EP_UNINSUR", "EPL_UNINSUR", "EP_LIMENG", "EP_MOBILE",
            "EP_GROUPQ", "EP_NOINT", "RPL_THEME1", "RPL_THEME2", "RPL_THEME4"
        ]
        svi_b = arcgis_all(svi_base_url, f"FIPS LIKE '{COUNTY_FIPS}%'", ",".join(svi_base_cols), order="FIPS")
        for c in svi_base_cols:
            if c != "FIPS":
                svi_b[c] = pd.to_numeric(svi_b[c], errors="coerce")
                svi_b.loc[svi_b[c] == -999, c] = None
        svi_b["FIPS"] = safe_str(svi_b["FIPS"], width=11)
        svi_b = svi_b.rename(columns={
            "FIPS": "geo_id", "E_TOTPOP": "svi_total_pop",
            "EP_NOVEH": "pct_no_vehicle", "EPL_NOVEH": "pctile_no_vehicle",
            "EP_DISABL": "pct_disability_svi", "EP_AGE65": "pct_age_65_plus",
            "EP_AGE17": "pct_age_17_under", "EP_UNINSUR": "pct_uninsured_all_ages",
            "EPL_UNINSUR": "pctile_uninsured", "EP_LIMENG": "pct_limited_english",
            "EP_MOBILE": "pct_mobile_homes", "EP_GROUPQ": "pct_group_quarters",
            "EP_NOINT": "pct_no_internet", "RPL_THEME1": "svi_socioeconomic",
            "RPL_THEME2": "svi_household", "RPL_THEME4": "svi_housing_transport",
        })
        v_base = b_df.merge(svi_b, on="geo_id", how="left")
        v_base["uninsured_gap"] = v_base["pct_uninsured"] - v_base["pct_uninsured_all_ages"]
        load_df(v_base, "burden_tracts", dataset=DATASET)

        # 4b. Base `exposure_tracts`
        if "exposure_tracts" in missing_base or need_base_reload:
            pm_base = soda("vpk8-vfhm", {
                "$select": "ctfips, avg(ds_pm_pred) as mean_pm, max(ds_pm_pred) as max_pm",
                "$where": f"ctfips like '{COUNTY_FIPS}%'",
                "$group": "ctfips",
            }, page=5000)
            for c in ("mean_pm", "max_pm"):
                pm_base[c] = pd.to_numeric(pm_base[c], errors="coerce")
            for thr in (12, 20, 25, 35):
                col = f"days_over_{thr}"
                d_t = soda("vpk8-vfhm", {
                    "$select": "ctfips, count(*) as rows_over",
                    "$where": f"ctfips like '{COUNTY_FIPS}%' AND ds_pm_pred > {thr}",
                    "$group": "ctfips",
                }, page=5000)
                if len(d_t):
                    d_t[col] = (pd.to_numeric(d_t["rows_over"], errors="coerce") / 2.0).round().astype(int)
                    pm_base = pm_base.merge(d_t[["ctfips", col]], on="ctfips", how="left")
                else:
                    pm_base[col] = 0
                pm_base[col] = pm_base[col].fillna(0).astype(int)
            pm_base["geo_id"] = safe_str(pm_base["ctfips"], width=11)
            load_df(pm_base.drop(columns=["ctfips"]), "exposure_tracts", dataset=DATASET)

        # 4c. Base `care_sites_state` and `care_sites` (needed for cross-border access & clinic hours)
        if "care_sites_state" in missing_base or "care_sites" in missing_base or need_base_reload:
            hrsa_base = "https://gisportal.hrsa.gov/server/rest/services"
            cmsf_url  = f"{hrsa_base}/HealthCareFacilities/CMSApprovedFacilities_FS/MapServer"
            hcs_url   = f"{hrsa_base}/HealthCareFacilities/PrimaryHealthCareFacilities_FS/MapServer/0"
            cms_fields = (
                "CMS_PROVIDER_NUM,FACILITY_NM,CMS_PROVIDER_ADDRESS,CMS_PROVIDER_CITY,"
                "CMS_PROVIDER_STATE_ABBR,CMS_PROVIDER_ZIP_CD,CMS_PROVIDER_CAT_DESC,"
                "CMS_PROVIDER_CAT_SUB_TYP_DESC"
            )
            cms_layers = {0: "Hospital", 1: "Critical Access Hospital", 2: "FQHC", 3: "Rural Health Clinic"}
            site_frames = []
            for lid, label in cms_layers.items():
                df_l = arcgis_points(f"{cmsf_url}/{lid}", f"CMS_PROVIDER_STATE_ABBR='{STATE_ABBR}'", cms_fields)
                if len(df_l):
                    df_l["site_kind"] = label
                    site_frames.append(df_l)
            # Explicit allow-list on Health Center layer — never request FQHC_ADMIN_CONTACT_* personal columns
            hc_fields = (
                "SITE_NM,SITE_ADDRESS,SITE_CITY,SITE_STATE_ABBR,SITE_ZIP_CD,"
                "HCC_TYP_DESC,HCC_STATUS_DESC,HCC_LOC_SETTING_DESC,"
                "TOT_OPER_HR_PER_WEEK,SITE_POP_TYP_DESC,RURAL_IND,"
                "MHC_SUB_PROG_IND,SBHC_SUB_PROG_IND,PHPC_SUB_PROG_IND,HCH_SUB_PROG_IND"
            )
            hc_df = arcgis_points(hcs_url, f"SITE_STATE_ABBR='{STATE_ABBR}'", hc_fields)
            if len(hc_df):
                hc_df["site_kind"] = "Health Center site"
                hc_df = hc_df.rename(columns={
                    "SITE_NM": "FACILITY_NM",
                    "SITE_ADDRESS": "CMS_PROVIDER_ADDRESS",
                    "SITE_CITY": "CMS_PROVIDER_CITY",
                    "SITE_STATE_ABBR": "CMS_PROVIDER_STATE_ABBR",
                    "SITE_ZIP_CD": "CMS_PROVIDER_ZIP_CD",
                })
                site_frames.append(hc_df)
            sites_all = pd.concat(site_frames, ignore_index=True, sort=False)
            sites_all = sites_all[sites_all["latitude"].notna() & sites_all["longitude"].notna()].copy()
            load_df(sites_all, "care_sites_state", dataset=DATASET)

            bq.query(f"""
            CREATE OR REPLACE TABLE `{PROJECT}.{DATASET}.care_sites` AS
            SELECT s.*, c.geo_id AS county_geo_id, c.county_name
            FROM `{PROJECT}.{DATASET}.care_sites_state` s
            JOIN `bigquery-public-data.geo_us_boundaries.counties` c
              ON ST_CONTAINS(c.county_geom, ST_GEOGPOINT(s.longitude, s.latitude))
            WHERE c.geo_id = '{COUNTY_FIPS}'
            """).result()



# ==============================================================================
# 5. SUPPLEMENT 1: RESTRICTED EQUITY AUDIT TABLE (`a4i_health_audit.equity_audit_tracts`)
# ==============================================================================
SVI_URL = (
    "https://onemap.cdc.gov/onemapservices/rest/services/SVI/"
    "CDC_ATSDR_Social_Vulnerability_Index_2022_USA/MapServer/2"
)

with step("load restricted equity audit table (SVI Theme 3 + ACS Income/Rent/Gini)"):
    # Pull SVI Theme 3 (Racial & Ethnic Minority Status), overall composite RPL_THEMES,
    # and detailed socioeconomic audit metrics that were withheld from `burden_tracts`.
    AUDIT_SVI_FIELDS = [
        "FIPS", "E_TOTPOP", "E_HH", "E_HU",
        # Theme 3: Racial & Ethnic Minority Status (FORBIDDEN in Planner, REQUIRED in Audit)
        "RPL_THEME3", "SPL_THEME3", "F_THEME3",
        "EP_MINRTY", "EPL_MINRTY", "F_MINRTY",
        "EP_AFAM", "EP_HISP", "EP_ASIAN", "EP_AIAN", "EP_NHPI", "EP_TWOMORE", "EP_OTHERRACE",
        # Overall SVI composite (contains Theme 3, so restricted to Audit)
        "RPL_THEMES", "SPL_THEMES", "F_TOTAL",
        # Socioeconomic & Household Audit Context
        "EP_POV150", "EPL_POV150", "F_POV150",
        "EP_HBURD", "EPL_HBURD", "F_HBURD",
        "EP_UNEMP", "EPL_UNEMP", "F_UNEMP",
        "EP_NOHSDP", "EPL_NOHSDP", "F_NOHSDP",
        "EP_SNGPNT", "EPL_SNGPNT", "F_SNGPNT",
    ]
    svi_audit = arcgis_all(
        SVI_URL,
        f"FIPS LIKE '{COUNTY_FIPS}%'",
        ",".join(AUDIT_SVI_FIELDS),
        order="FIPS",
    )
    check("SVI Theme 3 audit pull returned Bronx tracts", len(svi_audit) > 300, f"{len(svi_audit):,} tracts")

    for c in AUDIT_SVI_FIELDS:
        if c == "FIPS":
            continue
        svi_audit[c] = pd.to_numeric(svi_audit[c], errors="coerce")
        svi_audit.loc[svi_audit[c] == -999, c] = None

    svi_audit["FIPS"] = safe_str(svi_audit["FIPS"], width=11)
    svi_audit = svi_audit.rename(columns={
        "FIPS": "geo_id",
        "E_TOTPOP": "audit_total_pop",
        "E_HH": "households",
        "E_HU": "housing_units",
        "RPL_THEME3": "svi_theme3_minority_pctile",
        "SPL_THEME3": "svi_theme3_minority_sum",
        "F_THEME3": "flag_theme3_top10pct",
        "EP_MINRTY": "pct_minority",
        "EPL_MINRTY": "pctile_minority",
        "F_MINRTY": "flag_minority_top10pct",
        "EP_AFAM": "pct_black_nonhisp",
        "EP_HISP": "pct_hispanic",
        "EP_ASIAN": "pct_asian_nonhisp",
        "EP_AIAN": "pct_aian_nonhisp",
        "EP_NHPI": "pct_nhpi_nonhisp",
        "EP_TWOMORE": "pct_two_or_more_races",
        "EP_OTHERRACE": "pct_other_race",
        "RPL_THEMES": "svi_overall_composite",
        "SPL_THEMES": "svi_overall_sum",
        "F_TOTAL": "svi_total_flags",
        "EP_POV150": "pct_below_150pct_poverty",
        "EPL_POV150": "pctile_below_150pct_poverty",
        "F_POV150": "flag_poverty_top10pct",
        "EP_HBURD": "pct_housing_cost_burdened",
        "EPL_HBURD": "pctile_housing_cost_burdened",
        "F_HBURD": "flag_housing_burden_top10pct",
        "EP_UNEMP": "pct_unemployed",
        "EPL_UNEMP": "pctile_unemployed",
        "F_UNEMP": "flag_unemployed_top10pct",
        "EP_NOHSDP": "pct_no_high_school_diploma",
        "EPL_NOHSDP": "pctile_no_high_school_diploma",
        "F_NOHSDP": "flag_no_hs_diploma_top10pct",
        "EP_SNGPNT": "pct_single_parent_hh",
        "EPL_SNGPNT": "pctile_single_parent_hh",
        "F_SNGPNT": "flag_single_parent_top10pct",
    })

    # Load staging frame to restricted dataset, then enrich with Census ACS 5-yr tract estimates
    # from `bigquery-public-data.census_bureau_acs.censustract_2020_5yr`
    load_df(
        svi_audit,
        "equity_audit_tracts",
        dataset=AUDIT_DATASET,
        description=(
            "RESTRICTED EQUITY AUDIT TABLE (Bronx 36005). Contains SVI Theme 3 racial/ethnic "
            "composition, overall SVI composite, poverty, housing burden, and ACS income/Gini. "
            "Must NEVER be queried by the Siting/Planner Agent."
        ),
        labels={"governance": "equity_audit_only", "contains_race_theme3": "true"},
    )

    acs_enrich_sql = f"""
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
      WHERE STARTS_WITH(geo_id, '{COUNTY_FIPS}')
    ),
    acs18_exact AS (
      SELECT
        geo_id,
        IF(median_income > 0, median_income, NULL) AS median_income_2018
      FROM `bigquery-public-data.census_bureau_acs.censustract_2018_5yr`
      WHERE STARTS_WITH(geo_id, '{COUNTY_FIPS}')
    ),
    acs18_stem AS (
      SELECT
        SUBSTR(geo_id, 1, 9) AS stem9,
        ROUND(AVG(IF(median_income > 0, median_income, NULL)), 0) AS stem_median_income_2018
      FROM `bigquery-public-data.census_bureau_acs.censustract_2018_5yr`
      WHERE STARTS_WITH(geo_id, '{COUNTY_FIPS}')
      GROUP BY 1
    )
    SELECT
      s.*,
      ROUND(100.0 - s.pct_minority, 1) AS pct_white_nonhisp_est,
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
    bq.query(acs_enrich_sql).result()

    # Create an Audit Baseline View so the Equity Auditor Agent can compare any subset of sited
    # tracts directly against population-weighted Bronx county averages in one query.
    baseline_view_sql = f"""
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
    bq.query(baseline_view_sql).result()
    print(f"  created view {PROJECT}.{AUDIT_DATASET}.v_bronx_equity_baseline")

    # Apply table-level IAM policy on `equity_audit_tracts` if AUDITOR_PRINCIPAL is specified
    if AUDITOR_PRINCIPAL:
        tbl_ref = f"{PROJECT}.{AUDIT_DATASET}.equity_audit_tracts"
        policy = bq.get_iam_policy(tbl_ref)
        policy.bindings.append({
            "role": "roles/bigquery.dataViewer",
            "members": [AUDITOR_PRINCIPAL],
        })
        bq.set_iam_policy(tbl_ref, policy)
        print(f"  bound table-level roles/bigquery.dataViewer on {tbl_ref} to {AUDITOR_PRINCIPAL}")


# ==============================================================================
# 6. SUPPLEMENT 2: CDC PLACES 95% CONFIDENCE INTERVALS, HRSNs & PREVENTIVE SCREENINGS
# ==============================================================================
PLACES_ID = "yjkw-uj5s"

with step("load CDC PLACES 2025 95% CIs, non-food HRSNs, and preventive screenings"):
    # Pull:
    #  a) 95% CIs for all 11 core measures in `burden_tracts`
    #  b) Non-food HRSNs (housing insecurity, utility shutoff threat, lack of emotional support, social isolation)
    #  c) Mobile-clinic-relevant preventive screenings & comorbidities
    CORE_CI_MAP = {
        "access2_crude95ci": "pct_uninsured",
        "casthma_crude95ci": "pct_asthma",
        "copd_crude95ci": "pct_copd",
        "diabetes_crude95ci": "pct_diabetes",
        "bphigh_crude95ci": "pct_high_bp",
        "checkup_crude95ci": "pct_checkup",
        "mobility_crude95ci": "pct_mobility_difficulty",
        "selfcare_crude95ci": "pct_selfcare_difficulty",
        "indeplive_crude95ci": "pct_indep_living_difficulty",
        "disability_crude95ci": "pct_any_disability",
        "lacktrpt_crude95ci": "pct_lack_transport",
    }

    EXTRA_MEASURES_MAP = {
        # Non-food Health-Related Social Needs (HRSNs)
        "housinsecu": "pct_housing_insecurity",
        "shututility": "pct_utility_shutoff_threat",
        "emotionspt": "pct_lack_emotional_support",
        "loneliness": "pct_social_isolation",
        # Preventive Clinical Screenings & Med Adherence (low is worse for screenings!)
        "mammouse": "pct_mammogram_screen",
        "colon_screen": "pct_colorectal_screen",
        "cholscreen": "pct_cholesterol_screen",
        "dental": "pct_dental_visit",
        "bpmed": "pct_taking_bp_meds",
        # Related Chronic Conditions & Risk Factors
        "highchol": "pct_high_cholesterol",
        "chd": "pct_coronary_heart_disease",
        "stroke": "pct_stroke",
        "depression": "pct_depression",
        "obesity": "pct_obesity",
        "csmoking": "pct_smoking",
        "lpa": "pct_physical_inactivity",
        "sleep": "pct_short_sleep",
        "ghlth": "pct_fair_poor_health",
        "mhlth": "pct_frequent_mental_distress",
        "phlth": "pct_frequent_physical_distress",
    }

    select_cols = ["tractfips"] + list(CORE_CI_MAP.keys())
    for raw_prefix in EXTRA_MEASURES_MAP:
        select_cols.append(f"{raw_prefix}_crudeprev")
        select_cols.append(f"{raw_prefix}_crude95ci")

    places_sup = soda(PLACES_ID, {
        "$select": ", ".join(select_cols),
        "$where": f"countyfips='{COUNTY_FIPS}'",
    }, page=5000)

    out_places = pd.DataFrame()
    out_places["geo_id"] = safe_str(places_sup["tractfips"], width=11)

    # Parse 95% CIs for the 11 core measures into numeric low, high, and width
    for raw_ci_col, clean_base in CORE_CI_MAP.items():
        lo, hi = parse_ci_pair(places_sup[raw_ci_col])
        out_places[f"{clean_base}_ci_low"] = lo
        out_places[f"{clean_base}_ci_high"] = hi
        out_places[f"{clean_base}_ci_width"] = (hi - lo).round(2)

    # Parse prevalence + 95% CIs for the extra HRSN and preventive screening measures
    for raw_prefix, clean_name in EXTRA_MEASURES_MAP.items():
        prev_col = f"{raw_prefix}_crudeprev"
        ci_col = f"{raw_prefix}_crude95ci"
        out_places[clean_name] = pd.to_numeric(places_sup[prev_col], errors="coerce")
        lo, hi = parse_ci_pair(places_sup[ci_col])
        out_places[f"{clean_name}_ci_low"] = lo
        out_places[f"{clean_name}_ci_high"] = hi

    load_df(
        out_places,
        "places_supplement_tracts",
        dataset=DATASET,
        description=(
            "CDC PLACES 2025 supplemental tract metrics for Bronx (36005): numeric 95% confidence "
            "interval bounds (_ci_low, _ci_high, _ci_width) for all core measures, non-food HRSNs "
            "(housing insecurity, utility threat, social isolation), and preventive screenings."
        ),
    )


# ==============================================================================
# 7. SUPPLEMENT 3: CDC SVI 2022 DAYTIME POP, PERCENTILES & 2020 TRACT POLYGONS + ADJACENCY
# ==============================================================================
with step("load SVI non-racial percentiles, daytime population, and 2020 tract polygons"):
    # Pull 2020-vintage polygon geometries (`return_geometry=True, out_sr="4326"`), land area,
    # daytime population (`E_DAYPOP`), crowding/multi-unit housing, and non-racial `EPL_*` percentiles.
    SVI_SUP_FIELDS = [
        "FIPS", "AREA_SQMI", "E_TOTPOP", "E_DAYPOP",
        "EP_CROWD", "EPL_CROWD", "EP_MUNIT", "EPL_MUNIT",
        "EPL_AGE65", "EPL_AGE17", "EPL_DISABL", "EPL_LIMENG",
        "EPL_GROUPQ", "EPL_MOBILE",
    ]
    svi_sup = arcgis_all(
        SVI_URL,
        f"FIPS LIKE '{COUNTY_FIPS}%'",
        ",".join(SVI_SUP_FIELDS),
        order="FIPS",
        return_geometry=True,
        out_sr="4326",
    )

    for c in SVI_SUP_FIELDS:
        if c == "FIPS":
            continue
        svi_sup[c] = pd.to_numeric(svi_sup[c], errors="coerce")
        svi_sup.loc[svi_sup[c] == -999, c] = None

    svi_sup["geo_id"] = safe_str(svi_sup["FIPS"], width=11)
    svi_sup["tract_geojson"] = svi_sup["_geometry"].apply(esri_rings_to_geojson)
    svi_sup["area_sq_km"] = (svi_sup["AREA_SQMI"] * 2.589988).round(4)
    svi_sup["pop_density_per_sq_km"] = (
        svi_sup["E_TOTPOP"] / svi_sup["area_sq_km"].replace(0, pd.NA)
    ).round(1)
    svi_sup["daytime_pop_ratio"] = (
        svi_sup["E_DAYPOP"] / svi_sup["E_TOTPOP"].replace(0, pd.NA)
    ).round(2)

    svi_sup_clean = svi_sup.rename(columns={
        "AREA_SQMI": "area_sq_mi",
        "E_DAYPOP": "daytime_pop",
        "EP_CROWD": "pct_crowded_housing",
        "EPL_CROWD": "pctile_crowded_housing",
        "EP_MUNIT": "pct_multi_unit_housing",
        "EPL_MUNIT": "pctile_multi_unit_housing",
        "EPL_AGE65": "pctile_age_65_plus",
        "EPL_AGE17": "pctile_age_17_under",
        "EPL_DISABL": "pctile_disability",
        "EPL_LIMENG": "pctile_limited_english",
        "EPL_GROUPQ": "pctile_group_quarters",
        "EPL_MOBILE": "pctile_mobile_homes",
    }).drop(columns=["FIPS", "E_TOTPOP", "_geometry"])

    load_df(
        svi_sup_clean,
        "svi_supplement_tracts",
        dataset=DATASET,
        description=(
            "CDC SVI 2022 non-racial supplemental metrics for Bronx (36005): daytime population "
            "(E_DAYPOP), population density, housing crowding/multi-unit share, national percentile "
            "ranks (EPL_*), and 2020-vintage census tract polygons."
        ),
    )

    # Convert `tract_geojson` into a native BigQuery GEOGRAPHY column `tract_geom` and build
    # `tract_neighbors` (every pair of physically bordering Bronx census tracts).
    bq.query(f"""
        CREATE OR REPLACE TABLE `{PROJECT}.{DATASET}.svi_supplement_tracts` AS
        SELECT
          * EXCEPT(tract_geojson),
          SAFE.ST_GEOGFROMGEOJSON(tract_geojson, make_valid => TRUE) AS tract_geom
        FROM `{PROJECT}.{DATASET}.svi_supplement_tracts`
    """).result()

    neighbors_sql = f"""
    CREATE OR REPLACE TABLE `{PROJECT}.{DATASET}.tract_neighbors` AS
    WITH polygon_edges AS (
      SELECT
        a.geo_id AS tract_geo_id,
        b.geo_id AS neighbor_geo_id,
        ROUND(
          ST_DISTANCE(ST_CENTROID(a.tract_geom), ST_CENTROID(b.tract_geom)) / 1000.0,
          3
        ) AS centroid_distance_km
      FROM `{PROJECT}.{DATASET}.svi_supplement_tracts` a
      JOIN `{PROJECT}.{DATASET}.svi_supplement_tracts` b
        ON a.geo_id != b.geo_id
       AND ST_INTERSECTS(a.tract_geom, b.tract_geom)
      WHERE a.tract_geom IS NOT NULL AND b.tract_geom IS NOT NULL
    ),
    -- Include bridge-connected island tract (City Island 36005051601 <-> Pelham Bay Park 36005051602 & 36005026602)
    bridge_edges AS (
      SELECT
        a.geo_id AS tract_geo_id,
        b.geo_id AS neighbor_geo_id,
        ROUND(
          ST_DISTANCE(ST_CENTROID(a.tract_geom), ST_CENTROID(b.tract_geom)) / 1000.0,
          3
        ) AS centroid_distance_km
      FROM `{PROJECT}.{DATASET}.svi_supplement_tracts` a
      JOIN `{PROJECT}.{DATASET}.svi_supplement_tracts` b
        ON (a.geo_id = '36005051601' AND b.geo_id IN ('36005051602', '36005026602'))
        OR (b.geo_id = '36005051601' AND a.geo_id IN ('36005051602', '36005026602'))
    )
    SELECT DISTINCT tract_geo_id, neighbor_geo_id, centroid_distance_km
    FROM (
      SELECT * FROM polygon_edges
      UNION ALL
      SELECT * FROM bridge_edges
    )
    """
    bq.query(neighbors_sql).result()
    n_edges = bq.get_table(f"{PROJECT}.{DATASET}.tract_neighbors").num_rows
    print(f"  built {PROJECT}.{DATASET}.tract_neighbors: {n_edges:,} bordering tract pairs (2020-vintage, including bridge edges)")


# ==============================================================================
# 8. SUPPLEMENT 4: HRSA ALL-DISCIPLINE HPSAs (PRIMARY CARE, DENTAL, MENTAL HEALTH) + MUA/P
# ==============================================================================
HRSA_BASE = "https://gisportal.hrsa.gov/server/rest/services"

with step("load HRSA Primary Care, Dental & Mental Health HPSAs + Medically Underserved Areas (MUA/P)"):
    # 1. Pull Designated HPSA component polygons across all 3 disciplines for Bronx (36005)
    HPSA_LAYERS = {
        "Primary Care": 11,
        "Dental Health": 3,
        "Mental Health": 7,
    }
    hpsa_frames = []
    hpsa_fields = (
        "GEO_ID,STATE_COUNTY_FIPS_CD,HPSA_NM,HPSA_SCORE,HPSA_STATUS_DESC,HPSA_TYP_DESC,"
        "DISCIPLINE_CLASS_DESC,HPSA_DESIGNATION_POP,HPSA_ESTIMATED_UNDERSERVED_POP,"
        "HPSA_ESTIMATED_SERVED_POP,HPSA_POVERTY,HPSA_FORMAL_RATIO"
    )
    for disc_label, lid in HPSA_LAYERS.items():
        url = f"{HRSA_BASE}/Shortage/HealthProfessionalShortageAreas_FS/MapServer/{lid}"
        where = f"STATE_COUNTY_FIPS_CD='{COUNTY_FIPS}' AND HPSA_STATUS_DESC='Designated'"
        df_disc = arcgis_all(url, where, hpsa_fields)
        if len(df_disc):
            df_disc["discipline"] = disc_label
            hpsa_frames.append(df_disc)
            print(f"    {disc_label:<15} (layer {lid:>2}): {len(df_disc):,} designated Bronx rows")

    hpsa_all = pd.concat(hpsa_frames, ignore_index=True) if hpsa_frames else pd.DataFrame()
    if len(hpsa_all):
        for c in ("HPSA_SCORE", "HPSA_DESIGNATION_POP", "HPSA_ESTIMATED_UNDERSERVED_POP",
                  "HPSA_ESTIMATED_SERVED_POP", "HPSA_POVERTY", "HPSA_FORMAL_RATIO"):
            hpsa_all[c] = pd.to_numeric(hpsa_all[c], errors="coerce")
        hpsa_all["GEO_ID"] = safe_str(hpsa_all["GEO_ID"])
        hpsa_all["geo_id_len"] = hpsa_all["GEO_ID"].str.len()
        load_df(
            hpsa_all,
            "shortage_areas_all_disciplines",
            dataset=DATASET,
            description=(
                "HRSA Designated HPSA component rows across Primary Care (layer 11), "
                "Dental Health (layer 3), and Mental Health (layer 7) for Bronx (36005)."
            ),
        )

    # 2. Pull Medically Underserved Areas / Populations (MUA/P) with IMU Score & polygon geometry
    mua_frames = []
    mua_fields = (
        "SOURCE_ID,SERVICE_AREA_NAME,DESIGNATION_TYPE_DESCRIPTION,STATUS_CODE,"
        "STATUS_DESCRIPTION,SCORE,DESIGNATION_POPULATION,RESIDENT_CIVILIAN_POPULATION,"
        "POVERTY_100_PCT_NUM,POPULATION_AGE_65_OVER_PCT,PROVIDER_1000_POPULATION_RATIO,"
        "INFANT_MORTALITY_RATE"
    )
    for lid in (14, 15):  # 14 = MUP, 15 = MUA
        mua_url = f"{HRSA_BASE}/HealthCareShortage/HealthCareShortage/MapServer/{lid}"
        df_m = arcgis_all(
            mua_url,
            f"CMN_STATE_FIPS_CD='{STATE_FIPS}' AND STATUS_CODE='D'",
            mua_fields,
            return_geometry=True,
            out_sr="4326",
        )
        if len(df_m):
            mua_frames.append(df_m)

    mua_ny = pd.concat(mua_frames, ignore_index=True) if mua_frames else pd.DataFrame()
    if len(mua_ny):
        for c in ("SCORE", "DESIGNATION_POPULATION", "RESIDENT_CIVILIAN_POPULATION",
                  "POVERTY_100_PCT_NUM", "POPULATION_AGE_65_OVER_PCT",
                  "PROVIDER_1000_POPULATION_RATIO", "INFANT_MORTALITY_RATE"):
            mua_ny[c] = pd.to_numeric(mua_ny[c], errors="coerce")
        mua_ny["mua_geojson"] = mua_ny["_geometry"].apply(esri_rings_to_geojson)
        mua_ny = mua_ny.drop(columns=["_geometry"]).rename(columns={"SCORE": "imu_score"})
        load_df(mua_ny, "_staging_mua_ny", dataset=DATASET)

        # Spatially join NY MUA/P polygons to Bronx 2020 census tracts in BigQuery
        bq.query(f"""
            CREATE OR REPLACE TABLE `{PROJECT}.{DATASET}.shortage_mua_tracts` AS
            WITH mua_geoms AS (
              SELECT
                SOURCE_ID AS mua_source_id,
                SERVICE_AREA_NAME AS mua_service_area_name,
                DESIGNATION_TYPE_DESCRIPTION AS mua_designation_type,
                imu_score,
                SAFE.ST_GEOGFROMGEOJSON(mua_geojson, make_valid => TRUE) AS mua_geom
              FROM `{PROJECT}.{DATASET}._staging_mua_ny`
              WHERE mua_geojson IS NOT NULL
            )
            SELECT
              t.geo_id,
              COUNT(m.mua_source_id) > 0 AS in_designated_mua,
              MIN(m.imu_score) AS min_imu_score,
              STRING_AGG(DISTINCT m.mua_service_area_name, '; ') AS mua_service_areas,
              STRING_AGG(DISTINCT m.mua_designation_type, '; ') AS mua_designation_types
            FROM `{PROJECT}.{DATASET}.svi_supplement_tracts` t
            LEFT JOIN mua_geoms m
              ON ST_INTERSECTS(ST_CENTROID(t.tract_geom), m.mua_geom)
            GROUP BY t.geo_id
        """).result()
        bq.delete_table(f"{PROJECT}.{DATASET}._staging_mua_ny", not_found_ok=True)
        n_mua_tracts = list(bq.query(
            f"SELECT COUNTIF(in_designated_mua) FROM `{PROJECT}.{DATASET}.shortage_mua_tracts`"
        ).result())[0][0]
        print(f"  spatially joined MUA/P to Bronx tracts: {n_mua_tracts:,} tracts inside a designated MUA/P")


# ==============================================================================
# 9. SUPPLEMENT 5: EPA/CDC PM2.5 STANDARD ERROR (`ds_pm_stdd`) & DAILY OZONE (`hf2a-3ebq`)
# ==============================================================================
PM25_ID  = "vpk8-vfhm"   # Daily Census Tract-Level PM2.5 (2021)
OZONE_ID = "hf2a-3ebq"   # Daily Census Tract-Level Ozone (2016-2020, numeric ctfips)

with step("load EPA/CDC PM2.5 standard errors (ds_pm_stdd) and Daily Tract-Level Ozone (hf2a-3ebq)"):
    # 1. PM2.5 model prediction standard error (to prove within-county mean_pm spread is < model noise)
    pm_stdd = soda(PM25_ID, {
        "$select": (
            "ctfips, avg(ds_pm_pred) as mean_pm, max(ds_pm_pred) as max_pm, "
            "avg(ds_pm_stdd) as mean_pm_stdd, max(ds_pm_stdd) as max_pm_stdd"
        ),
        "$where": f"ctfips like '{COUNTY_FIPS}%'",
        "$group": "ctfips",
    }, page=5000)

    for c in ("mean_pm", "max_pm", "mean_pm_stdd", "max_pm_stdd"):
        pm_stdd[c] = pd.to_numeric(pm_stdd[c], errors="coerce")
    pm_stdd["geo_id"] = safe_str(pm_stdd["ctfips"], width=11)

    # 2. Daily Census Tract-Level Ozone (`hf2a-3ebq`)
    #    Trap: `ctfips` in hf2a-3ebq is typed NUMBER, not text! Filter with BETWEEN.
    lo_fips = int(f"{COUNTY_FIPS}000000")
    hi_fips = int(f"{COUNTY_FIPS}999999")
    o3 = soda(OZONE_ID, {
        "$select": (
            "ctfips, avg(ds_o3_pred) as mean_o3_ppb, max(ds_o3_pred) as max_o3_ppb, "
            "avg(ds_o3_stdd) as mean_o3_stdd, count(*) as n_o3_rows"
        ),
        "$where": f"ctfips between {lo_fips} and {hi_fips}",
        "$group": "ctfips",
    }, page=5000)

    for c in ("mean_o3_ppb", "max_o3_ppb", "mean_o3_stdd", "n_o3_rows"):
        o3[c] = pd.to_numeric(o3[c], errors="coerce")
    o3["geo_id"] = safe_str(o3["ctfips"], width=11)

    # Measure Ozone grain multiplier on 1 sample tract (just as Section 6 does for PM2.5)
    sample_o3_tract = int(o3["ctfips"].iloc[0])
    one_o3 = soda(OZONE_ID, {
        "$select": "year, date, ds_o3_pred",
        "$where": f"ctfips={sample_o3_tract} AND year='2020'",
    }, page=5000)
    o3_mult = int(one_o3.groupby(["year", "date"]).size().iloc[0]) if len(one_o3) else 1
    n_o3_years = int(o3["n_o3_rows"].median() / (365 * o3_mult)) if len(o3) else 5
    print(f"  ozone rows per tract-day multiplier: {o3_mult}x across ~{max(n_o3_years, 1)} years (2016-2020)")

    # Exceedance days per year over 50 ppb and 70 ppb (EPA NAAQS 8-hr ozone standard is 70 ppb)
    for thr in (50, 70):
        col = f"o3_days_per_yr_over_{thr}ppb"
        d_thr = soda(OZONE_ID, {
            "$select": "ctfips, count(*) as rows_over",
            "$where": f"ctfips between {lo_fips} and {hi_fips} AND ds_o3_pred > {thr}",
            "$group": "ctfips",
        }, page=5000)
        if len(d_thr):
            d_thr["geo_id"] = safe_str(d_thr["ctfips"], width=11)
            d_thr["rows_over"] = pd.to_numeric(d_thr["rows_over"], errors="coerce")
            d_thr[col] = (d_thr["rows_over"] / (o3_mult * max(n_o3_years, 1))).round(1)
            o3 = o3.merge(d_thr[["geo_id", col]], on="geo_id", how="left")
        else:
            o3[col] = 0.0
        o3[col] = o3[col].fillna(0.0)

    exp_sup = pm_stdd[["geo_id", "mean_pm_stdd", "max_pm_stdd"]].merge(
        o3[["geo_id", "mean_o3_ppb", "max_o3_ppb", "mean_o3_stdd",
            "o3_days_per_yr_over_50ppb", "o3_days_per_yr_over_70ppb"]],
        on="geo_id",
        how="outer",
    )

    load_df(
        exp_sup,
        "exposure_supplement_tracts",
        dataset=DATASET,
        description=(
            "EPA/CDC Downscaler air quality supplement for Bronx (36005): PM2.5 prediction "
            "standard error (ds_pm_stdd) and 2016-2020 Daily Census Tract-Level Ozone (hf2a-3ebq). "
            "Cleaned to 361 2020-vintage tracts with 9-digit parent tract stem backfill and zero NaN floats."
        ),
    )

    # Clean IEEE NaN floats, prune 16 retired 2010 orphan rows, and backfill split 2020 tracts from 9-digit stem
    bq.query(f"""
        CREATE OR REPLACE TABLE `{PROJECT}.{DATASET}.exposure_supplement_tracts` AS
        WITH clean_raw AS (
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
        stem_o3 AS (
          SELECT
            SUBSTR(geo_id, 1, 9) AS tract_stem9,
            ROUND(AVG(mean_o3_ppb), 3) AS stem_mean_o3_ppb,
            ROUND(MAX(max_o3_ppb), 3) AS stem_max_o3_ppb,
            ROUND(AVG(mean_o3_stdd), 4) AS stem_mean_o3_stdd,
            ROUND(AVG(o3_days_per_yr_over_50ppb), 1) AS stem_o3_days_50,
            ROUND(AVG(o3_days_per_yr_over_70ppb), 1) AS stem_o3_days_70
          FROM clean_raw
          WHERE mean_o3_ppb IS NOT NULL
          GROUP BY tract_stem9
        ),
        county_o3 AS (
          SELECT
            ROUND(AVG(mean_o3_ppb), 3) AS cnty_mean_o3_ppb,
            ROUND(MAX(max_o3_ppb), 3) AS cnty_max_o3_ppb,
            ROUND(AVG(mean_o3_stdd), 4) AS cnty_mean_o3_stdd,
            ROUND(AVG(o3_days_per_yr_over_50ppb), 1) AS cnty_o3_days_50,
            ROUND(AVG(o3_days_per_yr_over_70ppb), 1) AS cnty_o3_days_70
          FROM clean_raw
          WHERE mean_o3_ppb IS NOT NULL
        )
        SELECT
          s.geo_id,
          r.mean_pm_stdd,
          r.max_pm_stdd,
          COALESCE(r.mean_o3_ppb, st.stem_mean_o3_ppb, co.cnty_mean_o3_ppb) AS mean_o3_ppb,
          COALESCE(r.max_o3_ppb, st.stem_max_o3_ppb, co.cnty_max_o3_ppb) AS max_o3_ppb,
          COALESCE(r.mean_o3_stdd, st.stem_mean_o3_stdd, co.cnty_mean_o3_stdd) AS mean_o3_stdd,
          COALESCE(r.o3_days_per_yr_over_50ppb, st.stem_o3_days_50, co.cnty_o3_days_50) AS o3_days_per_yr_over_50ppb,
          COALESCE(r.o3_days_per_yr_over_70ppb, st.stem_o3_days_70, co.cnty_o3_days_70) AS o3_days_per_yr_over_70ppb,
          r.mean_o3_ppb IS NULL AS o3_imputed_from_parent_tract
        FROM `{PROJECT}.{DATASET}.svi_supplement_tracts` s
        LEFT JOIN clean_raw r USING (geo_id)
        LEFT JOIN stem_o3 st ON SUBSTR(s.geo_id, 1, 9) = st.tract_stem9
        CROSS JOIN county_o3 co
    """).result()


# ==============================================================================
# 10. SUPPLEMENT 6: FEMA NATIONAL RISK INDEX (HEAT/COLD WAVE) & NOAA GSOD SEASONAL HEAT
# ==============================================================================
FEMA_NRI_URL = (
    "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/"
    "National_Risk_Index_Census_Tracts/FeatureServer/0"
)

with step("load FEMA National Risk Index (Heat/Cold Wave) and NOAA GSOD seasonal heat"):
    NRI_FIELDS = [
        "TRACTFIPS", "POPULATION",
        "RISK_SCORE", "RISK_RATNG", "EAL_SCORE", "SOVI_SCORE", "RESL_SCORE", "RESL_RATNG",
        "HWAV_RISKS", "HWAV_RISKR", "HWAV_EALS", "HWAV_AFREQ",
        "CWAV_RISKS", "CWAV_RISKR", "CWAV_EALS", "CWAV_AFREQ",
    ]
    nri = arcgis_all(
        FEMA_NRI_URL,
        f"STCOFIPS='{COUNTY_FIPS}'",
        ",".join(NRI_FIELDS),
        order="TRACTFIPS",
    )
    check("FEMA NRI returned Bronx tracts", len(nri) > 300, f"{len(nri):,} tracts")

    for c in NRI_FIELDS:
        if c in ("TRACTFIPS", "RISK_RATNG", "RESL_RATNG", "HWAV_RISKR", "CWAV_RISKR"):
            continue
        nri[c] = pd.to_numeric(nri[c], errors="coerce")

    nri["geo_id"] = safe_str(nri["TRACTFIPS"], width=11)
    nri = nri.drop(columns=["TRACTFIPS"]).rename(columns={
        "POPULATION": "nri_pop",
        "RISK_SCORE": "fema_all_hazard_risk_score",
        "RISK_RATNG": "fema_all_hazard_risk_rating",
        "EAL_SCORE": "fema_expected_annual_loss_score",
        "SOVI_SCORE": "fema_social_vuln_score",
        "RESL_SCORE": "fema_community_resilience_score",
        "RESL_RATNG": "fema_community_resilience_rating",
        "HWAV_RISKS": "heatwave_risk_score",
        "HWAV_RISKR": "heatwave_risk_rating",
        "HWAV_EALS": "heatwave_expected_loss_score",
        "HWAV_AFREQ": "heatwave_events_per_yr",
        "CWAV_RISKS": "coldwave_risk_score",
        "CWAV_RISKR": "coldwave_risk_rating",
        "CWAV_EALS": "coldwave_expected_loss_score",
        "CWAV_AFREQ": "coldwave_events_per_yr",
    })

    load_df(
        nri,
        "climate_heat_risk_tracts",
        dataset=DATASET,
        description=(
            "FEMA National Risk Index (NRI) census-tract Heat Wave (HWAV_*) and Cold Wave (CWAV_*) "
            "risk scores, annualized frequencies, and community resilience for Bronx (36005)."
        ),
    )

    # BigQuery Public Data: NOAA GSOD monthly temperature & heat-day profile for NYC/Bronx
    # USAF stations: 725030 (LaGuardia - 4 km from South Bronx), 725053 (Central Park)
    noaa_sql = f"""
    CREATE OR REPLACE TABLE `{PROJECT}.{DATASET}.noaa_seasonal_heat` AS
    WITH daily AS (
      SELECT
        CAST(mo AS INT64) AS month_num,
         FORMAT_DATE('%B', DATE(2024, CAST(mo AS INT64), 1)) AS month_name,
        CAST(year AS INT64) AS yr,
        AVG(IF(temp < 9000, temp, NULL)) AS mean_temp_f,
        MAX(IF(max < 9000, max, NULL)) AS max_temp_f,
        MIN(IF(min < 9000, min, NULL)) AS min_temp_f
      FROM `bigquery-public-data.noaa_gsod.gsod202*`
      WHERE stn IN ('725030', '725053')
        AND _TABLE_SUFFIX BETWEEN '0' AND '5'
      GROUP BY month_num, month_name, yr, da
    )
    SELECT
      month_num,
      month_name,
      ROUND(AVG(mean_temp_f), 1) AS avg_daily_mean_temp_f,
      ROUND(AVG(max_temp_f), 1) AS avg_daily_high_temp_f,
      ROUND(MAX(max_temp_f), 1) AS peak_temp_f_5yr,
      ROUND(COUNTIF(max_temp_f >= 85.0) / COUNT(DISTINCT yr), 1) AS avg_days_85f_plus,
      ROUND(COUNTIF(max_temp_f >= 90.0) / COUNT(DISTINCT yr), 1) AS avg_days_90f_plus,
      ROUND(COUNTIF(min_temp_f <= 32.0) / COUNT(DISTINCT yr), 1) AS avg_freeze_days
    FROM daily
    GROUP BY month_num, month_name
    ORDER BY month_num
    """
    bq.query(noaa_sql).result()
    n_noaa = bq.get_table(f"{PROJECT}.{DATASET}.noaa_seasonal_heat").num_rows
    print(f"  loaded {PROJECT}.{DATASET}.noaa_seasonal_heat: {n_noaa} monthly climate rows")


# ==============================================================================
# 11. SUPPLEMENT 7: CROSS-BORDER & CAPACITY-WEIGHTED ACCESS (`tract_access_bronx_enhanced`)
#     + UNIFIED SITING FEATURE TABLE (`planner_tract_features`)
# ==============================================================================
with step("build cross-border & capacity-weighted access + unified planner_tract_features"):
    # In the Bronx, raw distance to the nearest clinic is tiny (median 390 m).
    # What actually differentiates Bronx neighborhoods is:
    #   1. Cross-border clinics in Manhattan/Westchester (`care_sites_state` vs `care_sites`)
    #   2. Weekly operating hours (`TOT_OPER_HR_PER_WEEK`) and distance to a FULL-TIME (>=35 hr/wk)
    #      safety-net clinic
    #   3. Local safety-net capacity density (total weekly clinic hours within 1 km relative to
    #      uninsured & high-burden population)
    enhanced_access_sql = f"""
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
        SAFE_CAST(TOT_OPER_HR_PER_WEEK AS FLOAT64) AS hours_per_week,
        ST_GEOGPOINT(longitude, latitude) AS pt
      FROM `{PROJECT}.{DATASET}.care_sites_state`
      WHERE longitude IS NOT NULL AND latitude IS NOT NULL
    ),
    county_sites AS (
      SELECT
        site_kind,
        SAFE_CAST(TOT_OPER_HR_PER_WEEK AS FLOAT64) AS hours_per_week,
        ST_GEOGPOINT(longitude, latitude) AS pt
      FROM `{PROJECT}.{DATASET}.care_sites`
      WHERE longitude IS NOT NULL AND latitude IS NOT NULL
    ),
    -- Deduplicated, community-accessible safety-net clinics (excludes School-Based, Homeless-Shelter-Only,
    -- Mobile Vans, and CMS+HRSA co-located duplicate coordinates)
    clean_community_safety_net AS (
      SELECT
        ROUND(latitude, 4) AS lat4,
        ROUND(longitude, 4) AS lon4,
        ANY_VALUE(ST_GEOGPOINT(longitude, latitude)) AS pt,
        MAX(COALESCE(SAFE_CAST(TOT_OPER_HR_PER_WEEK AS FLOAT64), 35.0)) AS hours_per_week
      FROM `{PROJECT}.{DATASET}.care_sites_state`
      WHERE longitude IS NOT NULL AND latitude IS NOT NULL
        AND site_kind IN ('FQHC', 'Health Center site')
        AND COALESCE(HCC_LOC_SETTING_DESC, '') != 'School'
        AND COALESCE(SBHC_SUB_PROG_IND, 'N') != 'Y'
        AND COALESCE(HCH_SUB_PROG_IND, 'N') != 'Y'
        AND COALESCE(SITE_OPER_SCHED_DESC, '') != 'Mobile Van'
        AND NOT REGEXP_CONTAINS(UPPER(COALESCE(site_name, '')), r'(\\bSCHOOL\\b|\\bPS\\s*[0-9]|\\bIS\\s*[0-9]|\\bMS\\s*[0-9]|\\bHS\\b|CAMPUS|MOBILE|SHELTER)')
      GROUP BY lat4, lon4
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
    clean_metrics AS (
      SELECT
        t.geo_id,
        ROUND(MIN(ST_DISTANCE(t.pt, cs.pt)) / 1000.0, 3) AS km_to_community_safety_net_clean,
        ROUND(MIN(IF(cs.hours_per_week >= 35, ST_DISTANCE(t.pt, cs.pt), NULL)) / 1000.0, 3) AS km_to_fulltime_community_safety_net_clean,
        COUNTIF(ST_DWITHIN(t.pt, cs.pt, 1000)) AS community_safety_net_sites_within_1km_clean,
        ROUND(SUM(IF(ST_DWITHIN(t.pt, cs.pt, 1000), cs.hours_per_week, 0)), 1) AS community_safety_net_hours_within_1km_clean,
        COUNTIF(ST_DWITHIN(t.pt, cs.pt, 2000)) AS community_safety_net_sites_within_2km_clean,
        ROUND(SUM(IF(ST_DWITHIN(t.pt, cs.pt, 2000), cs.hours_per_week, 0)), 1) AS community_safety_net_hours_within_2km_clean
      FROM t
      CROSS JOIN clean_community_safety_net cs
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
      cl.km_to_community_safety_net_clean,
      cl.km_to_fulltime_community_safety_net_clean,
      cl.community_safety_net_sites_within_1km_clean,
      cl.community_safety_net_hours_within_1km_clean,
      cl.community_safety_net_sites_within_2km_clean,
      cl.community_safety_net_hours_within_2km_clean,
      ROUND(
        SAFE_DIVIDE(t.total_pop * (t.pct_uninsured / 100.0), NULLIF(cl.community_safety_net_hours_within_1km_clean, 0)),
        1
      ) AS est_uninsured_per_clean_clinic_hr_1km
    FROM t
    LEFT JOIN county_metrics cm USING (geo_id)
    LEFT JOIN state_metrics sm USING (geo_id)
    LEFT JOIN clean_metrics cl USING (geo_id)
    """
    bq.query(enhanced_access_sql).result()
    print(f"  built {PROJECT}.{DATASET}.tract_access_bronx_enhanced")

    # Build unified, race-free `planner_tract_features` table for the Siting / Planner Agent
    planner_features_sql = f"""
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
    hpsa_stem AS (
      SELECT
        SUBSTR(GEO_ID, 1, 9) AS tract_stem9,
        MAX(IF(discipline = 'Primary Care', HPSA_SCORE, NULL)) AS stem_pc_hpsa_score,
        MAX(IF(discipline = 'Dental Health', HPSA_SCORE, NULL)) AS stem_dental_hpsa_score,
        MAX(IF(discipline = 'Mental Health', HPSA_SCORE, NULL)) AS stem_mh_hpsa_score
      FROM `{PROJECT}.{DATASET}.shortage_areas_all_disciplines`
      WHERE geo_id_len = 11
      GROUP BY tract_stem9
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
      -- Explicit Residential vs. Institutional Outlier Guardrail Flags (Trap 2)
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
      ROUND((p.pct_mammogram_screen + p.pct_colorectal_screen + p.pct_cholesterol_screen + p.pct_dental_visit) / 4.0, 2) AS preventive_screening_composite,
      -- Daytime pop, density & non-racial percentiles from SVI
      s.daytime_pop, s.daytime_pop_ratio, s.area_sq_km, s.pop_density_per_sq_km,
      s.pct_crowded_housing, s.pct_multi_unit_housing,
      s.pctile_age_65_plus, s.pctile_disability, s.pctile_limited_english,
      -- Cross-border, capacity-weighted & deduplicated community safety-net access
      a.km_to_any_care_statewide, a.km_to_safety_net_statewide,
      a.extra_km_if_uninsured_statewide, a.border_clip_km_error,
      a.km_to_fulltime_safety_net, a.extra_km_for_fulltime_hours,
      a.safety_net_sites_within_1km, a.safety_net_weekly_hours_within_1km,
      a.est_uninsured_adults_per_weekly_clinic_hr_1km,
      a.km_to_community_safety_net_clean,
      a.km_to_fulltime_community_safety_net_clean,
      a.community_safety_net_sites_within_1km_clean,
      a.community_safety_net_hours_within_1km_clean,
      a.community_safety_net_sites_within_2km_clean,
      a.community_safety_net_hours_within_2km_clean,
      a.est_uninsured_per_clean_clinic_hr_1km,
      -- HRSA HPSA scores (with 2010->2020 parent-tract stem backfill) & MUA/P status
      COALESCE(he.primary_care_hpsa_score, hs.stem_pc_hpsa_score) AS primary_care_hpsa_score,
      COALESCE(he.dental_hpsa_score, hs.stem_dental_hpsa_score) AS dental_hpsa_score,
      COALESCE(he.mental_health_hpsa_score, hs.stem_mh_hpsa_score) AS mental_health_hpsa_score,
      (he.primary_care_hpsa_score IS NULL AND hs.stem_pc_hpsa_score IS NOT NULL) AS hpsa_backfilled_from_2010_parent,
      m.in_designated_mua, m.min_imu_score, m.mua_service_areas,
      -- Air quality (12 km grid) & standard errors + Ozone
      x.mean_pm, x.max_pm, x.days_over_12, x.days_over_20, x.days_over_25,
      xs.mean_pm_stdd, xs.mean_o3_ppb, xs.max_o3_ppb, xs.mean_o3_stdd,
      xs.o3_days_per_yr_over_50ppb, xs.o3_days_per_yr_over_70ppb,
      -- FEMA Heat/Cold Wave risk
      c.heatwave_risk_score, c.heatwave_risk_rating, c.heatwave_events_per_yr,
      c.coldwave_risk_score, c.fema_community_resilience_score,
      -- Neighboring tract IDs (for "why this tract and not the neighbor" justification)
      COALESCE(nb.bordering_tract_count, 0) AS bordering_tract_count,
      nb.bordering_tract_ids
    FROM `{PROJECT}.{DATASET}.burden_tracts` b
    LEFT JOIN `{PROJECT}.{DATASET}.places_supplement_tracts` p USING (geo_id)
    LEFT JOIN `{PROJECT}.{DATASET}.svi_supplement_tracts` s USING (geo_id)
    LEFT JOIN `{PROJECT}.{DATASET}.tract_access_bronx_enhanced` a USING (geo_id)
    LEFT JOIN hpsa_exact he USING (geo_id)
    LEFT JOIN hpsa_stem hs ON SUBSTR(b.geo_id, 1, 9) = hs.tract_stem9
    LEFT JOIN `{PROJECT}.{DATASET}.shortage_mua_tracts` m USING (geo_id)
    LEFT JOIN `{PROJECT}.{DATASET}.exposure_tracts` x USING (geo_id)
    LEFT JOIN `{PROJECT}.{DATASET}.exposure_supplement_tracts` xs USING (geo_id)
    LEFT JOIN `{PROJECT}.{DATASET}.climate_heat_risk_tracts` c USING (geo_id)
    LEFT JOIN neighbor_summary nb USING (geo_id)
    """
    bq.query(planner_features_sql).result()
    n_pf = bq.get_table(f"{PROJECT}.{DATASET}.planner_tract_features").num_rows
    print(f"  built {PROJECT}.{DATASET}.planner_tract_features: {n_pf:,} rows")


# ==============================================================================
# 12. GOVERNANCE & DATA QUALITY VALIDATION SUITE
# ==============================================================================
with step("validate supplemental tables and audit access isolation"):
    def scalar(sql):
        return list(bq.query(sql).result())[0][0]

    # 1. Governance Check: ZERO racial/ethnic Theme 3 columns in the Siting/Planner dataset (`a4i_health`)
    FORBIDDEN_RACE_COLS = (
        "rpl_theme3", "spl_theme3", "f_theme3", "ep_minrty", "epl_minrty",
        "ep_afam", "ep_hisp", "ep_asian", "ep_aian", "ep_nhpi", "ep_twomore",
        "ep_otherrace", "rpl_themes", "pct_minority", "pct_black_nonhisp",
        "pct_hispanic", "pct_asian_nonhisp", "pct_white_nonhisp_est",
        "svi_theme3_minority_pctile", "svi_overall_composite"
    )
    in_forbidden = ",".join(f"'{c}'" for c in FORBIDDEN_RACE_COLS)
    leaked_cols = bq.query(f"""
        SELECT table_name, column_name
        FROM `{PROJECT}.{DATASET}.INFORMATION_SCHEMA.COLUMNS`
        WHERE LOWER(column_name) IN ({in_forbidden})
    """).to_dataframe()
    check(
        "siting dataset (`a4i_health`) contains ZERO racial/ethnic Theme 3 columns",
        len(leaked_cols) == 0,
        f"leaked: {leaked_cols.to_dict('records')}" if len(leaked_cols) else "0 forbidden columns in a4i_health",
    )

    # 2. Governance Check: Restricted Audit Dataset (`a4i_health_audit`) HAS the required equity audit columns
    n_audit = scalar(f"SELECT COUNT(*) FROM `{PROJECT}.{AUDIT_DATASET}.equity_audit_tracts`")
    check(
        "restricted `a4i_health_audit.equity_audit_tracts` is populated for Bronx",
        n_audit > 300,
        f"{n_audit:,} tracts",
    )

    # 3. Check 95% CI parsing in `places_supplement_tracts`
    n_ci = scalar(f"""
        SELECT COUNTIF(pct_asthma_ci_low IS NOT NULL AND pct_asthma_ci_high > pct_asthma_ci_low)
        FROM `{PROJECT}.{DATASET}.places_supplement_tracts`
    """)
    check("PLACES 95% confidence intervals parsed into numeric low/high bounds", n_ci > 300, f"{n_ci:,} valid intervals")

    # 4. Check 2020-vintage tract adjacency graph (`tract_neighbors`)
    n_nb = scalar(f"SELECT COUNT(DISTINCT tract_geo_id) FROM `{PROJECT}.{DATASET}.tract_neighbors`")
    check("2020-vintage tract adjacency graph (`tract_neighbors`) covers Bronx tracts", n_nb > 300, f"{n_nb:,} tracts with neighbors")

    # 5. Print summary inventory across both datasets
    print("\n" + "=" * 78)
    print(f"BRONX ({COUNTY_FIPS}) BIGQUERY INVENTORY SUMMARY")
    print("=" * 78)
    for ds_id, label in ((DATASET, "SITING / PLANNER DATASET (Race-Free)"),
                         (AUDIT_DATASET, "RESTRICTED EQUITY AUDIT DATASET (Auditor Only)")):
        print(f"\nDataset: `{PROJECT}.{ds_id}` — {label}")
        inv = bq.query(f"""
            SELECT table_id, row_count, ROUND(size_bytes/1024, 1) AS kb
            FROM `{PROJECT}.{ds_id}.__TABLES__`
            ORDER BY table_id
        """).to_dataframe()
        for _, r in inv.iterrows():
            print(f"  {r['table_id']:<34} {int(r['row_count']):>8,} rows   ({r['kb']:>7.1f} KB)")

    tally = pd.DataFrame(CHECKS)["verdict"].value_counts().to_dict()
    print("\n" + "-" * 78)
    print(f"Validation: PASS={tally.get('PASS', 0)}  WARN={tally.get('WARN', 0)}  FAIL={tally.get('FAIL', 0)}  "
          f"| Total runtime: {sum(STEPS.values()):.1f}s")
    print("=" * 78)
    if tally.get("FAIL"):
        raise RuntimeError(f"{tally['FAIL']} validation check(s) failed.")
