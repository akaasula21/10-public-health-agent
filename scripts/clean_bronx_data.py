#!/usr/bin/env python3
"""CLI entrypoint to run the Bronx Dataset Cleaner & Local Cache Exporter."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.data.cleaner import run_dataset_cleaner


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    summary = run_dataset_cleaner()
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
