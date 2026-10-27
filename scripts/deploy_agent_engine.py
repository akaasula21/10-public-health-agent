"""Deploys the BronxMobileCareBroker Google ADK Agent to Vertex AI Agent Engine (Agent Runtime).

Once deployed, the ReasoningEngine resource can be linked directly into
Gemini Enterprise (Google Agentspace) or invoked via Vertex AI Agent Engine API.
"""

from __future__ import annotations

import os
import vertexai
from vertexai import agent_engines
from vertexai.preview.reasoning_engines import AdkApp

from agent.agent import (
    root_agent,
    planner_agent,
    auditor_agent,
    flyer_agent,
    director_agent,
)

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "qwiklabs-gcp-03-c81d344a3430")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
STAGING_BUCKET = os.environ.get("STAGING_BUCKET", f"gs://{PROJECT_ID}-flyers")


def main():
    print(f"Initializing Vertex AI Agent Engine in {PROJECT_ID} ({LOCATION}) using {STAGING_BUCKET}...")
    vertexai.init(project=PROJECT_ID, location=LOCATION, staging_bucket=STAGING_BUCKET)

    # Ensure live Vertex AI model endpoints on the deployed ADK agents
    planner_agent.model = "gemini-2.5-pro"
    auditor_agent.model = "gemini-2.5-pro"
    flyer_agent.model = "gemini-2.5-flash"
    director_agent.model = "gemini-2.5-flash"

    adk_app = AdkApp(
        agent=root_agent,
        enable_tracing=True,
    )

    print("Deploying BronxMobileCareBroker to Vertex AI Agent Engine (Reasoning Engine)...")
    remote_agent = agent_engines.create(
        adk_app,
        display_name="BronxMobileCareBroker",
        description=(
            "Dynamic Public Health Equity & Preventative Mobile Care Broker for Bronx County, NY (FIPS 36005). "
            "Orchestrates race-blind siting, isolated post-hoc demographic equity auditing, bilingual 6th-grade "
            "outreach flyers, and Commissioner executive briefings."
        ),
        requirements=[
            "google-adk>=1.0.0",
            "google-genai>=1.0.0",
            "google-cloud-bigquery>=3.25.0",
            "google-cloud-aiplatform[agent_engines,adk]",
            "pydantic>=2.8.0",
            "requests>=2.32.0",
            "httpx>=0.27.0",
        ],
        extra_packages=["./agent", "./data"],
        env_vars={
            "PROJECT_ID": PROJECT_ID,
            "ADK_PRO_MODEL": "gemini-2.5-pro",
            "ADK_FLYER_MODEL": "gemini-2.5-flash",
            "ADK_MODEL": "gemini-2.5-flash",
            "GCS_FLYER_BUCKET": f"{PROJECT_ID}-flyers",
        },
    )

    print("======================================================================")
    print("SUCCESS: Agent Deployed to Vertex AI Agent Engine (Gemini Enterprise Ready)")
    print(f"Resource Name: {remote_agent.resource_name}")
    print("======================================================================")


if __name__ == "__main__":
    main()
