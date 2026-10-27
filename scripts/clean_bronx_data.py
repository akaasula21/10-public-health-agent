#!/usr/bin/env python3
"""CLI entrypoint to run the Dataset Cleaner & Local Cache Exporter.

Defaults to the Bronx County, NY (36005) pilot, but accepts `--county-fips`
to clean and export cache for any target county.
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

from agent.config import PILOT_COUNTY_FIPS, normalize_county_fips
from agent.data.cleaner import run_dataset_cleaner


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Run Dataset Cleaner to materialize clean views and local parquet caches."
    )
    parser.add_argument(
        "--county-fips",
        "-c",
        "-f",
        default=PILOT_COUNTY_FIPS,
        help=f"5-digit county FIPS code (default: {PILOT_COUNTY_FIPS} for Bronx pilot).",
    )
    parser.add_argument(
        "--project-id",
        "-p",
        default=None,
        help="Google Cloud project ID (defaults to GOOGLE_CLOUD_PROJECT or active default).",
    )
    parser.add_argument(
        "--dataset",
        "-d",
        default=None,
        help="Planner dataset ID (defaults to configured dataset, e.g. a4i_health).",
    )
    parser.add_argument(
        "--audit-dataset",
        "-a",
        default=None,
        help="Audit dataset ID (defaults to configured audit dataset, e.g. a4i_health_audit).",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Skip writing local parquet cache files.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    county_fips = normalize_county_fips(args.county_fips)

    summary = run_dataset_cleaner(
        project_id=args.project_id,
        county_fips=county_fips,
        dataset=args.dataset,
        audit_dataset=args.audit_dataset,
        export_cache=not args.no_cache,
    )
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
