"""Maps, transit, and street landmark resolution tool bound to ExclusiveFlyerSubAgent & PlannerSubAgent."""

from __future__ import annotations

import os
from typing import Any

import requests

from agent.data.bq_client import load_clean_tracts_df
from agent.data.landmarks_catalog import lookup_bronx_landmark_context


def resolve_stop_landmark_and_map_context(
    geo_id: str,
    lat: float | None = None,
    lon: float | None = None,
) -> dict[str, Any]:
    """Resolve real-world Bronx park/plaza landmark, street intersection, MTA subway/bus lines, and Street View URLs.

    Uses the curated Bronx landmark catalog (`agent/data/landmarks_catalog.py`) and enriches with
    Google Maps Reverse Geocoding API if `GOOGLE_MAPS_API_KEY` is configured in the environment.
    """
    geo_id_str = str(geo_id).strip()
    if lat is None or lon is None:
        df = load_clean_tracts_df(prefer_cache=True)
        match = df[df["geo_id"].astype(str) == geo_id_str]
        if not match.empty:
            lat = float(match.iloc[0]["lat"])
            lon = float(match.iloc[0]["lon"])
        else:
            lat = 40.8448
            lon = -73.8648

    ctx = lookup_bronx_landmark_context(geo_id_str, float(lat), float(lon))

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if api_key:
        try:
            resp = requests.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"latlng": f"{lat},{lon}", "key": api_key},
                timeout=4,
            )
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                if results:
                    ctx["formatted_address"] = results[0].get("formatted_address", "")
        except Exception:
            pass

    return ctx
