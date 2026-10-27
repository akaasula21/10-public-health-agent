"""Database seeder for schedules, stops, self-correction audit logs, and bilingual flyers."""

from __future__ import annotations

from typing import Any

from agent.db.repository import (
    create_schedule_with_stops,
    get_latest_schedule_bundle,
    record_audit_log,
    save_outreach_flyers,
)
from agent.tools.bq_scoring import score_bronx_tracts
from agent.tools.equity_audit import run_posthoc_equity_audit


def build_bilingual_flyer_for_stop(stop: dict[str, Any]) -> dict[str, Any]:
    """Generate 6th-grade reading level, zero-jargon English + Spanish outreach copy for a stop.

    Follows `ExclusiveFlyerSubAgent` persona rules:
    - Zero technical/policy acronyms (no 'FIPS', 'HPSA', 'SVI', 'GEOID', or 'FQHC').
    - Warm, 6th-grade reading level.
    - Side-by-side English and Spanish.
    - Includes core trust anchors: 'Free care. No health insurance needed. No ID required to be seen. Walk-ins welcome.'
    """
    sat_idx = int(stop["saturday_index"])
    sat_date = str(stop["saturday_date"])
    neighborhood = str(stop["neighborhood"])
    landmark = str(stop["landmark_name"])
    intersection = str(stop["street_intersection"])
    subways = ", ".join(stop.get("subway_lines", [])) or "local subway"
    buses = ", ".join(stop.get("bus_lines", [])) or "local bus"

    headline_en = f"Free Saturday Health Van at {landmark} ({neighborhood})"
    body_en = (
        f"Join your neighbors this Saturday ({sat_date}) from 9:00 AM to 4:00 PM at {landmark} "
        f"(near {intersection}).\n\n"
        f"What we offer for you and your family:\n"
        f"• Free blood pressure, blood sugar, and breathing checkups\n"
        f"• Free asthma inhalers, spacers, and quick flu/cold/COVID swabs\n"
        f"• Help signing up for free or low-cost health plans in English and Spanish\n\n"
        f"Free care. No health insurance needed. No ID required to be seen. Walk-ins welcome!\n"
        f"Easy to reach: Take the {subways} train or the {buses} bus right to {intersection}."
    )

    headline_es = f"Unidad Móvil de Salud Gratis este Sábado en {landmark} ({neighborhood})"
    body_es = (
        f"Acompáñenos este sábado ({sat_date}) de 9:00 AM a 4:00 PM en {landmark} "
        f"(cerca de {intersection}).\n\n"
        f"Servicios gratuitos para usted y su familia:\n"
        f"• Chequeos gratis de presión arterial, azúcar en la sangre y respiración\n"
        f"• Inhaladores para el asma, espaciadores y pruebas rápidas de gripe y COVID\n"
        f"• Ayuda en español para inscribirse en programas de salud gratuitos\n\n"
        f"Atención médica gratis. No necesita seguro médico. No se pide identificación para atenderle. ¡Sin cita previa!\n"
        f"Cómo llegar: Tome el tren {subways} o el autobús {buses} hasta {intersection}."
    )

    sms_en = (
        f"FREE Bronx Health Van Sat {sat_date} 9am-4pm @ {intersection} ({neighborhood}). "
        f"Free checkups, asthma & diabetes care. No ID or insurance needed!"
    )[:200]

    sms_es = (
        f"SALUD GRATIS este sáb {sat_date} 9am-4pm en {intersection} ({neighborhood}). "
        f"Chequeos de presión, azúcar y asma. ¡Sin seguro ni identificación!"
    )[:200]

    chw_en = (
        f"Hi neighbor! This Saturday ({sat_date}), our community health van will be parked right at "
        f"{landmark} ({intersection}), steps from the {subways} train and {buses} bus. "
        f"You can walk right up between 9 AM and 4 PM for a free blood pressure, blood sugar, or asthma checkup. "
        f"Everything is 100% free, you don't need health insurance, and we never ask for ID to see you."
    )

    chw_es = (
        f"¡Hola vecino/a! Este sábado ({sat_date}), nuestra unidad móvil de salud estará aquí mismo en "
        f"{landmark} ({intersection}), a pocos pasos del tren {subways} y el autobús {buses}. "
        f"Puede acercarse sin cita entre las 9 AM y las 4 PM para un chequeo gratis de la presión, el azúcar o el asma. "
        f"Todo es 100% gratis, no necesita seguro médico y nunca pedimos identificación para atenderle."
    )

    return {
        "stop_id": str(stop.get("id", "")),
        "saturday_index": sat_idx,
        "flyer_headline_en": headline_en,
        "flyer_body_en": body_en,
        "flyer_headline_es": headline_es,
        "flyer_body_es": body_es,
        "sms_broadcast_en": sms_en,
        "sms_broadcast_es": sms_es,
        "chw_script_en": chw_en,
        "chw_script_es": chw_es,
    }


def ensure_seeded_schedule(target_month: str = "November 2026", force_reseed: bool = False) -> dict[str, Any]:
    """Ensure the database contains an audited 4-Saturday schedule, self-correction trace, and flyers."""
    existing = get_latest_schedule_bundle()
    if existing is not None and not force_reseed:
        return existing

    # 1. Run Iteration 1 (Naive / Outlier-Exposed) to capture the autonomous self-correction trace
    iter1_plan = score_bronx_tracts(enforce_outlier_guardrail=False, enforce_hpsa_diversity=False)
    iter1_audit = run_posthoc_equity_audit(
        selected_geo_ids=[s["geo_id"] for s in iter1_plan["proposed_stops"]],
        proposed_stops=iter1_plan["proposed_stops"],
    )

    # 2. Run Iteration 2 (Self-Corrected: Clean Residential + HPSA Diverse across distinct ME zones)
    iter2_plan = score_bronx_tracts(enforce_outlier_guardrail=True, enforce_hpsa_diversity=True)
    iter2_audit = run_posthoc_equity_audit(
        selected_geo_ids=[s["geo_id"] for s in iter2_plan["proposed_stops"]],
        proposed_stops=iter2_plan["proposed_stops"],
    )

    # 3. Persist the Schedule and the 4 approved Saturday stops
    created = create_schedule_with_stops(
        target_month=target_month,
        stops_payload=iter2_plan["proposed_stops"],
        status="AUDITED",
    )
    schedule_id = created["schedule_id"]

    # 4. Persist Iteration 1 (REJECTED) and Iteration 2 (APPROVED) to `audit_logs`
    record_audit_log(
        schedule_id=schedule_id,
        iteration_number=1,
        audit_status=iter1_audit["audit_status"],
        demographic_coverage_ratios=iter1_audit["demographic_coverage_ratios"],
        auditor_comments=iter1_audit["auditor_comments"],
        institutional_outliers_detected=iter1_audit["institutional_outliers_detected"],
        hpsa_diversity_status=iter1_audit["hpsa_diversity_status"],
        violations=iter1_audit["violations"],
    )
    record_audit_log(
        schedule_id=schedule_id,
        iteration_number=2,
        audit_status=iter2_audit["audit_status"],
        demographic_coverage_ratios=iter2_audit["demographic_coverage_ratios"],
        auditor_comments=iter2_audit["auditor_comments"],
        institutional_outliers_detected=iter2_audit["institutional_outliers_detected"],
        hpsa_diversity_status=iter2_audit["hpsa_diversity_status"],
        violations=iter2_audit["violations"],
    )

    # 5. Generate and persist Bilingual English/Spanish Flyers for all 4 active stops
    flyers_payload = [build_bilingual_flyer_for_stop(stop) for stop in created["stops"]]
    save_outreach_flyers(schedule_id=schedule_id, flyers_payload=flyers_payload)

    return get_latest_schedule_bundle() or created
