"""Native Google ADK Multi-Agent Orchestration for Bronx Mobile Care Broker.

Exposes:
- `root_agent`: A SequentialAgent composing the Planner <-> Auditor Loop, Flyer Agent, and Director Agent.
- Sub-Agents:
  1. `planner_agent`: Siting strategist with BigQuery & Weather tools (race-blind, gemini-3.6-pro).
  2. `auditor_agent`: Independent watchdog (isolated context, gemini-3.6-pro) enforcing all 5 traps and post-hoc equity.
  3. `flyer_agent`: 6th-grade bilingual community outreach author (contradictory to auditor, gemini-2.5-flash-image).
  4. `director_agent`: Executive briefer and policy analyst (contradictory to flyer).
- `run_broker()`: Async runner using Google ADK's InMemoryRunner.
"""

from __future__ import annotations

import os
import uuid
from typing import Any
from google.adk.agents import LlmAgent, SequentialAgent, LoopAgent
from google.adk.runners import InMemoryRunner
from google.genai import types

# Default Vertex AI Configuration
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", os.environ.get("PROJECT_ID", "qwiklabs-gcp-03-c81d344a3430"))
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")

from agent.prompts import (
    PLANNER_SYSTEM_PROMPT,
    AUDITOR_SYSTEM_PROMPT,
    FLYER_SYSTEM_PROMPT,
    DIRECTOR_SYSTEM_PROMPT,
)
from agent.tools.bq_scoring import (
    score_bronx_tracts,
    run_director_bigquery_sql,
)
from agent.tools.equity_audit import (
    run_posthoc_equity_audit,
    approve_and_exit_audit_loop,
)
from agent.tools.weather_aq import get_saturday_weather_and_air_quality
from agent.tools.maps_landmarks import resolve_stop_landmark_and_map_context
from agent.tools.flyer_image_tool import generate_flyer_visual

PRO_MODEL = os.environ.get("ADK_PRO_MODEL", "gemini-3.6-pro")
FLYER_IMAGE_MODEL = os.environ.get("ADK_FLYER_MODEL", "gemini-2.5-flash-image")
DEFAULT_MODEL = os.environ.get("ADK_MODEL", PRO_MODEL)

# =====================================================================
# 1. PLANNER SUB-AGENT (Siting Strategist & Clinical Lead)
# =====================================================================
planner_agent = LlmAgent(
    name="PlannerSubAgent",
    model=PRO_MODEL,
    instruction=PLANNER_SYSTEM_PROMPT,
    tools=[
        score_bronx_tracts,
        get_saturday_weather_and_air_quality,
        resolve_stop_landmark_and_map_context,
    ],
    output_key="proposed_schedule",
)

# =====================================================================
# 2. AUDIT & ACCOUNTABILITY SUB-AGENT (The Trap Watchdog)
# Context-isolated: include_contents="none" so it critiques independently
# =====================================================================
auditor_agent = LlmAgent(
    name="AuditAccountabilitySubAgent",
    model=PRO_MODEL,
    instruction=AUDITOR_SYSTEM_PROMPT,
    include_contents="none",
    tools=[
        run_posthoc_equity_audit,
        approve_and_exit_audit_loop,
    ],
    output_key="audit_verdict",
)

# =====================================================================
# 3. PLANNER <-> AUDITOR SELF-CORRECTION LOOP (Capped at 3 iterations)
# Breaks cleanly when auditor calls approve_and_exit_audit_loop
# =====================================================================
siting_and_audit_loop = LoopAgent(
    name="SitingAndAuditLoop",
    sub_agents=[planner_agent, auditor_agent],
    max_iterations=3,
)

# =====================================================================
# 4. EXCLUSIVE FLYER SUB-AGENT (Community Outreach Persona)
# Contradictory instructions: Warm, 6th-grade, bilingual, zero jargon
# =====================================================================
flyer_agent = LlmAgent(
    name="ExclusiveFlyerAgent",
    model=FLYER_IMAGE_MODEL,
    instruction=FLYER_SYSTEM_PROMPT,
    tools=[
        resolve_stop_landmark_and_map_context,
        generate_flyer_visual,
    ],
    output_key="outreach_flyers",
)

# =====================================================================
# 5. DIRECTOR BRIEFING AGENT (Health Department Executive Persona)
# Contradictory instructions: Hedged, statistical, data-scale caveats
# =====================================================================
director_agent = LlmAgent(
    name="DirectorBriefingAgent",
    model=DEFAULT_MODEL,
    instruction=DIRECTOR_SYSTEM_PROMPT,
    tools=[
        run_director_bigquery_sql,
        score_bronx_tracts,
        run_posthoc_equity_audit,
    ],
    output_key="director_briefing",
)

# =====================================================================
# ROOT AGENT (Exposed for ADK Web & Runners)
# =====================================================================
root_agent = SequentialAgent(
    name="BronxMobileCareBroker",
    sub_agents=[
        siting_and_audit_loop,
        flyer_agent,
        director_agent,
    ],
)


async def run_broker(
    user_prompt: str = (
        "Generate next month's 4-Saturday mobile clinic deployment plan for Bronx County, NY (36005). "
        "Enforce HPSA diversity across 4 distinct zones, race-blind composite scoring, institutional outlier checks, "
        "and produce community flyers and the executive briefing."
    ),
    verbose: bool = True,
) -> dict[str, Any]:
    """Runs the full multi-agent broker pipeline end-to-end using InMemoryRunner."""
    orig_models = (planner_agent.model, auditor_agent.model, flyer_agent.model, director_agent.model)
    try:
        # Map logical spec models to live Vertex AI endpoints for tool-calling execution
        if planner_agent.model == "gemini-3.6-pro":
            planner_agent.model = "gemini-2.5-pro"
        if auditor_agent.model == "gemini-3.6-pro":
            auditor_agent.model = "gemini-2.5-pro"
        if flyer_agent.model == "gemini-2.5-flash-image":
            flyer_agent.model = "gemini-2.5-flash"
        if director_agent.model == "gemini-3.6-pro":
            director_agent.model = "gemini-2.5-flash"

        runner = InMemoryRunner(agent=root_agent)
        user_id = "health_admin_01"
        session_id = f"bronx_run_{uuid.uuid4().hex[:8]}"

        await runner.session_service.create_session(
            app_name=runner.app_name,
            user_id=user_id,
            session_id=session_id,
        )

        user_content = types.Content(
            role="user",
            parts=[types.Part.from_text(text=user_prompt)],
        )

        events = []
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=user_content,
        ):
            events.append(event)
            if verbose:
                author = getattr(event, "author", "system")
                content = getattr(event, "content", None)
                if content and getattr(content, "parts", None):
                    for part in content.parts:
                        if getattr(part, "function_call", None):
                            fc = part.function_call
                            print(f"  ⚡ [{author}] TOOL CALL: {fc.name}")
                        elif getattr(part, "text", None) and part.text:
                            snippet = part.text.strip().replace("\n", " ")[:120]
                            print(f"  💬 [{author}]: {snippet}...")

        session = await runner.session_service.get_session(
            app_name=runner.app_name,
            user_id=user_id,
            session_id=session_id,
        )
        final_state = dict(session.state) if (session and session.state) else {}

        return {
            "status": "COMPLETED",
            "session_id": session_id,
            "events_count": len(events),
            "proposed_schedule": final_state.get("proposed_schedule"),
            "audit_verdict": final_state.get("audit_verdict"),
            "outreach_flyers": final_state.get("outreach_flyers"),
            "director_briefing": final_state.get("director_briefing"),
            "session_state": final_state,
        }
    finally:
        planner_agent.model, auditor_agent.model, flyer_agent.model, director_agent.model = orig_models
