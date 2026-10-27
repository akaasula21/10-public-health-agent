#!/usr/bin/env python3
"""Unified County-Agnostic Dataset Loader CLI.

Loads, supplements, cleans, and validates public health datasets for any US county in BigQuery.
Bronx County, NY (FIPS 36005) is the default pilot county.

Usage:
    # Run full end-to-end pipeline for the default pilot county (Bronx, NY - 36005):
    python scripts/load_county_data.py

    # Run for another pre-staged Challenge 5 county (e.g. Fulton County, GA - 13121):
    python scripts/load_county_data.py --county-fips 13121

    # Run for Cook County, IL using live APIs only:
    python scripts/load_county_data.py --county-fips 17031 --base-source live

    # Run only the supplemental tables stage:
    python scripts/load_county_data.py --county-fips 36005 --stage supplement

    # List all pre-configured reference counties:
    python scripts/load_county_data.py --list-counties
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.config import (
    BQ_AUDIT_DATASET,
    BQ_DATASET,
    COUNTY_FIPS,
    GCP_PROJECT_ID,
    KNOWN_COUNTIES,
    PILOT_COUNTY_FIPS,
    get_county_config,
    normalize_county_fips,
)
from agent.data.loader import CountyDataLoader, run_unified_loader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("load_county_data")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Unified County-Agnostic Dataset Loader for Public Health Mobile Care Broker.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--county-fips",
        "-f",
        default=COUNTY_FIPS,
        help=f"5-digit target county FIPS code (default: '{COUNTY_FIPS}', Bronx County NY pilot).",
    )
    parser.add_argument(
        "--county-name",
        "-n",
        default=None,
        help="Optional county display name (e.g., 'Fulton County, GA'). Auto-inferred if omitted.",
    )
    parser.add_argument(
        "--state-abbr",
        "-s",
        default=None,
        help="Optional 2-letter USPS state abbreviation (e.g., 'GA', 'NY'). Auto-inferred if omitted.",
    )
    parser.add_argument(
        "--project",
        "-p",
        default=GCP_PROJECT_ID,
        help=f"GCP Project ID (default: '{GCP_PROJECT_ID}').",
    )
    parser.add_argument(
        "--dataset",
        "-d",
        default=BQ_DATASET,
        help=f"Destination BigQuery main dataset (default: '{BQ_DATASET}').",
    )
    parser.add_argument(
        "--audit-dataset",
        "-a",
        default=BQ_AUDIT_DATASET,
        help=f"Destination BigQuery equity audit dataset (default: '{BQ_AUDIT_DATASET}').",
    )
    parser.add_argument(
        "--stage",
        choices=["all", "base", "supplement", "clean", "validate"],
        default="all",
        help="Pipeline stage to execute: 'all' (default), 'base', 'supplement', 'clean', or 'validate'.",
    )
    parser.add_argument(
        "--base-source",
        choices=["auto", "gcs", "live"],
        default="auto",
        help="Source for 8 core base tables: 'auto' (use GCS if pre-staged else live), 'gcs', or 'live'.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Skip exporting local Parquet/JSON/GeoJSON caches in data/cache/.",
    )
    parser.add_argument(
        "--list-counties",
        action="store_true",
        help="Print list of known Challenge 5 pre-staged and reference counties, then exit.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.list_counties:
        print("=" * 80)
        print("KNOWN REFERENCE & PRE-STAGED COUNTIES IN REGISTRY:")
        print("=" * 80)
        for fips, cfg in KNOWN_COUNTIES.items():
            pilot_tag = " [DEFAULT PILOT COUNTY]" if cfg.is_pilot else ""
            gcs_tag = " (GCS Pre-Staged Snapshot)" if cfg.pre_staged_gcs else ""
            print(f"  FIPS: {fips}  |  {cfg.county_name:<30}  |  Transit: {cfg.transit_agency:<25}{pilot_tag}{gcs_tag}")
        print("=" * 80)
        print("Note: Any other valid 5-digit US county FIPS is supported via live federal APIs.")
        return 0

    target_fips = normalize_county_fips(args.county_fips)
    cfg = get_county_config(target_fips, county_name=args.county_name, state_abbr=args.state_abbr)

    logger.info("Target County : %s (%s)", cfg.county_name, cfg.county_fips)
    logger.info("Pilot County  : %s", "YES (Default Pilot County)" if cfg.is_pilot else "NO (General County)")
    logger.info("GCP Project   : %s", args.project)
    logger.info("BigQuery DS   : %s (Audit: %s)", args.dataset, args.audit_dataset)
    logger.info("Stage Target  : %s", args.stage)
    logger.info("Base Source   : %s", args.base_source)

    try:
        results = run_unified_loader(
            county_fips=target_fips,
            county_name=cfg.county_name,
            state_abbr=cfg.state_abbr,
            project_id=args.project,
            dataset=args.dataset,
            audit_dataset=args.audit_dataset,
            base_source=args.base_source,
            stage=args.stage,
            export_cache=not args.no_cache,
        )
        print("\n" + "=" * 80)
        print("UNIFIED DATASET LOADER EXECUTION SUMMARY:")
        print("=" * 80)
        print(json.dumps(results, indent=2, default=str))
        print("=" * 80)
        return 0
    except Exception as exc:
        logger.exception("Unified County Loader failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
