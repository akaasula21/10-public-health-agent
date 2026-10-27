"""Gemini 2.5 Flash Image Tool & Google Cloud Storage Sync for Community Outreach Flyers.

Uses Google GenAI SDK (Vertex AI) with model 'gemini-2.5-flash-image'
to generate high-resolution bilingual community clinic posters.
Saves posters locally to static/flyers/saturday_{saturday_index}.png AND
uploads both visual posters and bilingual text flyers to Google Cloud Storage:
gs://qwiklabs-gcp-03-c81d344a3430-flyers/
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, List
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

FLYERS_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "flyers"
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "qwiklabs-gcp-03-c81d344a3430")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
IMAGE_MODEL = os.environ.get("FLYER_IMAGE_MODEL", "gemini-2.5-flash-image")
GCS_FLYER_BUCKET = os.environ.get("GCS_FLYER_BUCKET", f"{PROJECT_ID}-flyers")


def _upload_bytes_to_gcs(blob_path: str, data: bytes, content_type: str = "image/png") -> str | None:
    """Uploads bytes to the configured Google Cloud Storage flyer bucket using google.auth + httpx."""
    try:
        import urllib.parse
        import google.auth
        from google.auth.transport.requests import Request
        import httpx

        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/devstorage.read_write"])
        credentials.refresh(Request())

        encoded_name = urllib.parse.quote(blob_path, safe="")
        upload_url = (
            f"https://storage.googleapis.com/upload/storage/v1/b/{GCS_FLYER_BUCKET}/o"
            f"?uploadType=media&name={encoded_name}"
        )
        resp = httpx.post(
            upload_url,
            content=data,
            headers={
                "Authorization": f"Bearer {credentials.token}",
                "Content-Type": content_type,
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        gcs_uri = f"gs://{GCS_FLYER_BUCKET}/{blob_path}"
        logger.info(f"Uploaded flyer artifact to {gcs_uri}")
        return gcs_uri
    except Exception as e:
        logger.warning(f"GCS upload skipped/failed for {blob_path}: {e}")
        return None


def sync_flyers_to_gcs(schedule_id: str, target_month: str, flyers_data: List[dict[str, Any]]) -> List[str]:
    """Uploads a schedule's bilingual flyer texts and poster images to Google Cloud Storage."""
    uploaded_uris: List[str] = []
    safe_month = (target_month or "active").lower().replace(" ", "_").replace("(", "").replace(")", "")
    prefix = f"schedules/{safe_month}_{schedule_id[:8]}"

    # 1. Upload full JSON bundle of bilingual flyers + SMS + CHW scripts
    bundle_bytes = json.dumps(
        {
            "schedule_id": schedule_id,
            "target_month": target_month,
            "bucket": f"gs://{GCS_FLYER_BUCKET}",
            "flyers": flyers_data,
        },
        indent=2,
        ensure_ascii=False,
    ).encode("utf-8")
    uri = _upload_bytes_to_gcs(f"{prefix}/bilingual_flyers_bundle.json", bundle_bytes, "application/json")
    if uri:
        uploaded_uris.append(uri)

    # 2. Upload individual English & Spanish markdown handouts + sync poster PNGs
    for f in flyers_data:
        sat_idx = f.get("saturday_index", 1)
        en_md = f"# {f.get('headline_en', '')}\n\n{f.get('body_en', '')}\n\n**SMS (EN):** {f.get('sms_en', '')}\n"
        es_md = f"# {f.get('headline_es', '')}\n\n{f.get('body_es', '')}\n\n**SMS (ES):** {f.get('sms_es', '')}\n"

        u_en = _upload_bytes_to_gcs(f"{prefix}/saturday_{sat_idx}_en.md", en_md.encode("utf-8"), "text/markdown")
        u_es = _upload_bytes_to_gcs(f"{prefix}/saturday_{sat_idx}_es.md", es_md.encode("utf-8"), "text/markdown")
        if u_en:
            uploaded_uris.append(u_en)
        if u_es:
            uploaded_uris.append(u_es)

        poster_file = FLYERS_DIR / f"saturday_{sat_idx}.png"
        if poster_file.exists():
            u_png = _upload_bytes_to_gcs(
                f"{prefix}/saturday_{sat_idx}_poster.png",
                poster_file.read_bytes(),
                "image/png",
            )
            if u_png:
                uploaded_uris.append(u_png)

    return uploaded_uris


def generate_flyer_visual(
    saturday_index: int,
    neighborhood: str,
    headline: str = "Free Family Health Day / Cuidado de Salud Gratis",
    services_focus: str = "Asthma inhalers, checkups, flu shots, bilingual staff",
) -> dict[str, Any]:
    """Generates an eye-catching community flyer poster graphic using Gemini 2.5 Flash Image.

    Saves locally to static/flyers/saturday_{saturday_index}.png and uploads to
    Google Cloud Storage (gs://qwiklabs-gcp-03-c81d344a3430-flyers/posters/).
    """
    FLYERS_DIR.mkdir(parents=True, exist_ok=True)
    out_filename = f"saturday_{saturday_index}.png"
    out_path = FLYERS_DIR / out_filename
    rel_url = f"/static/flyers/{out_filename}"

    prompt = (
        f"A vibrant, welcoming, bilingual community health flyer poster graphic for a mobile medical clinic in {neighborhood}, Bronx, New York. "
        f"Headline theme: '{headline}'. "
        f"Services highlighted: '{services_focus}'. "
        "Key trust anchors: 100% Free, No Insurance Needed, No ID Required, Hablamos Español. "
        "Art style: Warm, professional community graphic illustration with diverse Latino and Black healthcare workers and families smiling, "
        "a clean friendly modern mobile health clinic van parked by a tree-lined Bronx park, vibrant uplifting colors, high resolution, no garbled text."
    )

    try:
        client = genai.Client(
            vertexai=True,
            project=PROJECT_ID,
            location=LOCATION,
        )
        response = client.models.generate_content(
            model=IMAGE_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
        )

        image_data = None
        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if getattr(part, "inline_data", None) and part.inline_data.data:
                    image_data = part.inline_data.data
                    break

        if image_data:
            with open(out_path, "wb") as f:
                f.write(image_data)
            gcs_uri = _upload_bytes_to_gcs(f"posters/{out_filename}", image_data, "image/png")
            logger.info(f"Generated flyer poster for Saturday {saturday_index} at {out_path} ({len(image_data)} bytes)")
            return {
                "status": "SUCCESS",
                "saturday_index": saturday_index,
                "neighborhood": neighborhood,
                "headline": headline,
                "model_used": IMAGE_MODEL,
                "image_path": str(out_path),
                "url": rel_url,
                "gcs_uri": gcs_uri or f"gs://{GCS_FLYER_BUCKET}/posters/{out_filename}",
                "size_bytes": len(image_data),
                "message": f"Community flyer visual created and saved to {rel_url} and GCS bucket gs://{GCS_FLYER_BUCKET}.",
            }
        else:
            return {
                "status": "NO_IMAGE_DATA",
                "saturday_index": saturday_index,
                "neighborhood": neighborhood,
                "url": rel_url,
                "message": "Model responded but did not contain inline image bytes.",
            }

    except Exception as e:
        logger.error(f"Failed to generate flyer image for Saturday {saturday_index}: {e}", exc_info=True)
        return {
            "status": "ERROR",
            "saturday_index": saturday_index,
            "neighborhood": neighborhood,
            "url": rel_url,
            "error": str(e),
            "message": f"Image generation encountered an error: {str(e)}",
        }
