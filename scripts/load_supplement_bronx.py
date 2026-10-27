#!/usr/bin/env python3
"""CLI entrypoint for supplemental dataset loading and equity audit isolation.

By default, loads the vetted supplemental tables and restricted equity audit
dataset for the pilot county (Bronx County, NY, FIPS 36005). Supports `--county-fips`
to load supplemental data for any US county.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.config import PILOT_COUNTY_FIPS, normalize_county_fips, BQ_DATASET, BQ_AUDIT_DATASET
from agent.data.loader import CountyDataLoader


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Load supplemental tables and restricted equity audit dataset in BigQuery."
    )
    parser.add_argument(
        "--county-fips",
        "-c",
        default=os.environ.get("A4I_COUNTY_FIPS", PILOT_COUNTY_FIPS),
        help=f"5-digit county FIPS code (default: {PILOT_COUNTY_FIPS} for Bronx pilot).",
    )
    parser.add_argument(
        "--project-id",
        "-p",
        default=os.environ.get("GOOGLE_CLOUD_PROJECT", None),
        help="Google Cloud project ID (defaults to GOOGLE_CLOUD_PROJECT or active default).",
    )
    parser.add_argument(
        "--dataset",
        "-d",
        default=BQ_DATASET,
        help=f"Planner dataset ID (default: {BQ_DATASET}).",
    )
    parser.add_argument(
        "--audit-dataset",
        "-a",
        default=BQ_AUDIT_DATASET,
        help=f"Restricted equity audit dataset ID (default: {BQ_AUDIT_DATASET}).",
    )
    parser.add_argument(
        "--skip-weather",
        action="store_true",
        help="Skip loading NOAA GSOD seasonal heat extremes.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    county_fips = normalize_county_fips(args.county_fips)

    loader = CountyDataLoader(
        county_fips=county_fips,
        project_id=args.project_id,
        dataset=args.dataset,
        audit_dataset=args.audit_dataset,
        stage="supplement",
        skip_weather=args.skip_weather,
    )
    summary = loader.run()
    print("\n" + "=" * 70)
    print(f"SUPPLEMENTAL LOAD COMPLETE FOR COUNTY {county_fips}")
    print("=" * 70)
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
