"""Test runner for end-to-end Google ADK execution of the Bronx Mobile Care Broker.
"""

import asyncio
import os
import uuid
from google.genai import types
from google.adk.runners import InMemoryRunner
from agent.agent import root_agent

# Ensure Vertex AI configuration
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
os.environ["GOOGLE_CLOUD_PROJECT"] = "qwiklabs-gcp-03-c81d344a3430"
os.environ["GOOGLE_CLOUD_LOCATION"] = "us-central1"


async def main():
    print("======================================================================")
    print("RUNNING BRONX MOBILE CARE BROKER ADK PIPELINE")
    print("======================================================================")

    runner = InMemoryRunner(agent=root_agent)
    user_id = "test_health_director"
    session_id = f"session_{uuid.uuid4().hex[:6]}"

    await runner.session_service.create_session(
        app_name=runner.app_name,
        user_id=user_id,
        session_id=session_id,
    )

    prompt_text = (
        "Generate the complete 4-Saturday mobile clinic deployment plan for next month in Bronx County, NY (36005). "
        "Enforce HPSA diversity across 4 distinct zones, race-blind composite scoring, institutional outlier checks, "
        "and produce community flyers and the executive briefing."
    )
    user_content = types.Content(
        role="user",
        parts=[types.Part.from_text(text=prompt_text)],
    )

    print(f"\n[USER PROMPT]: {prompt_text}\n")
    print("Streaming agent events...\n")

    event_count = 0
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=user_content,
    ):
        event_count += 1
        author = getattr(event, "author", "agent")
        
        # Check for function calls
        if hasattr(event, "content") and event.content:
            for part in getattr(event.content, "parts", []):
                if getattr(part, "function_call", None):
                    fc = part.function_call
                    print(f"  ⚡ [{author}] TOOL CALL: {fc.name}({dict(fc.args) if fc.args else ''})")
                elif getattr(part, "function_response", None):
                    fr = part.function_response
                    print(f"  ✓ [{author}] TOOL RESPONSE: {fr.name}")
                elif getattr(part, "text", None) and part.text:
                    snippet = part.text.strip().replace("\n", " ")[:140]
                    print(f"  💬 [{author}]: {snippet}...")

    # Inspect final session state
    session = await runner.session_service.get_session(
        app_name=runner.app_name,
        user_id=user_id,
        session_id=session_id,
    )
    
    print("\n======================================================================")
    print(f"EXECUTION COMPLETE: {event_count} total events generated.")
    print("======================================================================")
    if session and session.state:
        print("\nSession State Keys written across agents:")
        for k in session.state.keys():
            val_str = str(session.state[k])
            print(f"  • {k}: {len(val_str)} characters")
    
    return session


if __name__ == "__main__":
    asyncio.run(main())
