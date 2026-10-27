"""Seed an audited and approved 4-Saturday schedule into Cloud SQL for immediate UI demo."""

import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from db.database import SessionLocal, init_db
from db.repository import save_schedule_run, get_current_schedule

def seed():
    init_db()
    db = SessionLocal()
    try:
        current = get_current_schedule(db)
        if current and len(current.stops) == 4:
            print(f"Schedule already exists with 4 stops: {current.id} ({current.status})")
            return

        mock_schedule = {
            "county": "Bronx County, NY",
            "county_fips": "36005",
            "target_month": "November 2026",
            "methodology_note": "Race-blind composite ranking across 347 tracts, audited post-hoc for demographic equity, zero group-quarters outliers, spanning 4 distinct HPSA zones.",
            "schedule": [
                {
                    "saturday_index": 1,
                    "saturday_date": "2026-11-07",
                    "geo_id": "36005006700",
                    "neighborhood": "High Bridge",
                    "hpsa_designation_zone": "ME - High Bridge",
                    "hpsa_score": 18.0,
                    "composite_need_score": 77.9,
                    "landmark_name": "Mullaly Park & Reverend T. Wendell Foster Recreation Center Plaza",
                    "street_intersection": "E 165th St & Jerome Ave / River Ave",
                    "transit_connections": {
                        "subway_lines": ["4", "B", "D"],
                        "bus_lines": ["Bx6", "Bx6-SBS", "Bx13", "Bx1"]
                    },
                    "lat": 40.8195,
                    "lon": -73.9182,
                    "demographics": {
                        "total_pop": 5420,
                        "pct_uninsured": 22.4,
                        "pct_asthma": 16.8,
                        "pct_diabetes": 14.2
                    },
                    "weather_posture": {
                        "posture_mode": "Standard Open-Air Curbside Canopy + Walk-Up Intake Tent",
                        "forecast_temp_f": 56.0,
                        "aqi_pm25": 42.0,
                        "precipitation_risk": "Low (10%)"
                    },
                    "clinical_kit_allocations": {
                        "asthma_nebulizer_units": 45,
                        "hypertension_cuffs": 40,
                        "point_of_care_a1c_tests": 50,
                        "naloxone_nasal_kits": 50,
                        "flu_covid_vaccine_doses": 75
                    },
                    "clinical_siting_justification": "Severe evening and Saturday clinic operating bottleneck. High asthma ER admission history along Jerome Ave corridor."
                },
                {
                    "saturday_index": 2,
                    "saturday_date": "2026-11-14",
                    "geo_id": "36005008600",
                    "neighborhood": "Soundview / Pelham Bay Border",
                    "hpsa_designation_zone": "ME - Pelham",
                    "hpsa_score": 19.0,
                    "composite_need_score": 81.74,
                    "landmark_name": "Soundview Park & Colgate Avenue Community Entrance",
                    "street_intersection": "Bruckner Blvd & Colgate Ave / Morrison Ave",
                    "transit_connections": {
                        "subway_lines": ["6"],
                        "bus_lines": ["Bx27", "Bx39", "Bx4", "Bx4A"]
                    },
                    "lat": 40.8199,
                    "lon": -73.8498,
                    "demographics": {
                        "total_pop": 4890,
                        "pct_uninsured": 24.1,
                        "pct_asthma": 15.3,
                        "pct_diabetes": 15.8
                    },
                    "weather_posture": {
                        "posture_mode": "Heated Van-Only Enclosed Intake (Brisk Coastal Breeze)",
                        "forecast_temp_f": 48.0,
                        "aqi_pm25": 38.0,
                        "precipitation_risk": "Low (15%)"
                    },
                    "clinical_kit_allocations": {
                        "asthma_nebulizer_units": 35,
                        "hypertension_cuffs": 50,
                        "point_of_care_a1c_tests": 60,
                        "naloxone_nasal_kits": 40,
                        "flu_covid_vaccine_doses": 80
                    },
                    "clinical_siting_justification": "Highest HPSA shortage severity (19.0) in South Bronx; transit bottleneck between Cross Bronx and Soundview waterfront."
                },
                {
                    "saturday_index": 3,
                    "saturday_date": "2026-11-21",
                    "geo_id": "36005040302",
                    "neighborhood": "Fordham / Belmont",
                    "hpsa_designation_zone": "ME - Fordham",
                    "hpsa_score": 17.0,
                    "composite_need_score": 59.73,
                    "landmark_name": "Fordham Plaza Regional Transit & Retail Hub",
                    "street_intersection": "E Fordham Rd & Webster Ave / Third Ave",
                    "transit_connections": {
                        "subway_lines": ["B", "D", "4"],
                        "bus_lines": ["Bx12-SBS", "Bx9", "Bx15", "Bx41-SBS", "Metro-North"]
                    },
                    "lat": 40.8678,
                    "lon": -73.8922,
                    "demographics": {
                        "total_pop": 6120,
                        "pct_uninsured": 26.8,
                        "pct_asthma": 17.9,
                        "pct_diabetes": 16.4
                    },
                    "weather_posture": {
                        "posture_mode": "Standard Open-Air Curbside Canopy + High-Capacity Triage Booths",
                        "forecast_temp_f": 52.0,
                        "aqi_pm25": 45.0,
                        "precipitation_risk": "None (0%)"
                    },
                    "clinical_kit_allocations": {
                        "asthma_nebulizer_units": 55,
                        "hypertension_cuffs": 45,
                        "point_of_care_a1c_tests": 55,
                        "naloxone_nasal_kits": 60,
                        "flu_covid_vaccine_doses": 100
                    },
                    "clinical_siting_justification": "Central pedestrian transit hub connecting East and West Bronx. Severe weekend clinic deficit despite massive pedestrian foot traffic."
                },
                {
                    "saturday_index": 4,
                    "saturday_date": "2026-11-28",
                    "geo_id": "36005002300",
                    "neighborhood": "Hunts Point",
                    "hpsa_designation_zone": "ME - Hunts Point",
                    "hpsa_score": 16.0,
                    "composite_need_score": 58.93,
                    "landmark_name": "Hunts Point Riverside Park & Food Distribution Terminal Border",
                    "street_intersection": "Lafayette Ave & Edgewater Rd / Tiffany St",
                    "transit_connections": {
                        "subway_lines": ["6"],
                        "bus_lines": ["Bx6", "Bx6-SBS"]
                    },
                    "lat": 40.8091,
                    "lon": -73.9258,
                    "demographics": {
                        "total_pop": 4280,
                        "pct_uninsured": 27.5,
                        "pct_asthma": 19.4,
                        "pct_diabetes": 15.1
                    },
                    "weather_posture": {
                        "posture_mode": "Canopy + HEPA Air Purification Filtration Station (Freight Corridor)",
                        "forecast_temp_f": 50.0,
                        "aqi_pm25": 48.0,
                        "precipitation_risk": "Low (10%)"
                    },
                    "clinical_kit_allocations": {
                        "asthma_nebulizer_units": 60,
                        "hypertension_cuffs": 40,
                        "point_of_care_a1c_tests": 45,
                        "naloxone_nasal_kits": 55,
                        "flu_covid_vaccine_doses": 70
                    },
                    "clinical_siting_justification": "Heavy diesel freight emissions corridor ('Asthma Alley'). High uninsured worker concentration with zero operating weekend care sites."
                }
            ]
        }

        mock_audit = {
            "iteration_number": 2,
            "audit_status": "APPROVED",
            "traps_checked": {
                "urban_distance_trap": "PASS (0% physical distance penalty applied; access measured via transit & weekend hours)",
                "institutional_outliers_detected": [],
                "hpsa_diversity": "PASS (4 distinct zones: High Bridge, Pelham, Fordham, Hunts Point)",
                "pm25_spatial_scale": "PASS (Paired 12km grid with real-time hourly curbside posture)",
                "nssp_missingness_guardrail": "PASS (Non-reporting hospital zero-fill rejected)"
            },
            "coverage_ratios_vs_county_baseline": {
                "black_or_hispanic_combined_ratio": 1.13,
                "hispanic_ratio": 1.18,
                "poverty_concentration_ratio": 1.60,
                "uninsured_concentration_ratio": 1.54
            },
            "violations": [],
            "summary": "The proposed 4-Saturday schedule passes all audit criteria. Zero institutional outliers detected. 4 distinct HPSA shortage zones covered. Equitable post-hoc demographic coverage achieved (95.7% Black/Hispanic vs 84.4% county baseline)."
        }

        flyers_text = """
================================================================================
BRONX COMMUNITY MOBILE HEALTH CLINIC — FREE SATURDAY CARE
CLÍNICA DE SALUD MÓVIL COMUNITARIA DEL BRONX — ATENCIÓN GRATIS LOS SÁBADOS
================================================================================

ENGLISH:
Welcome! The Bronx Mobile Health Van is visiting your neighborhood this month to provide 100% free, confidential health checkups, breathing treatments for asthma, blood pressure screenings, diabetes checks, and free medications right on the spot!
No health insurance is needed. No ID is required. Everyone is welcome!

ESPAÑOL:
¡Bienvenidos! La Unidad Móvil de Salud del Bronx visitará su vecindario este mes para ofrecer chequeos médicos 100% gratuitos y confidenciales, tratamientos para el asma, control de la presión arterial, pruebas de diabetes y medicamentos gratis en el momento.
¡No se requiere seguro médico! ¡No se requiere identificación! ¡Todos son bienvenidos!

SATURDAY LOCATIONS / UBICACIONES DE LOS SÁBADOS:
• Saturday 1 (Nov 7): High Bridge — Mullaly Park Plaza (E 165th St & Jerome Ave) [Subway 4, B, D | Bus Bx6, Bx13]
• Saturday 2 (Nov 14): Soundview/Pelham — Soundview Park Entrance (Bruckner Blvd & Colgate Ave) [Subway 6 | Bus Bx27, Bx39]
• Saturday 3 (Nov 21): Fordham — Fordham Plaza Transit Hub (E Fordham Rd & Webster Ave) [Subway B, D, 4 | Bus Bx12-SBS]
• Saturday 4 (Nov 28): Hunts Point — Riverside Park (Lafayette Ave & Edgewater Rd) [Subway 6 | Bus Bx6]

Hours: 9:00 AM to 3:00 PM every Saturday. Hot tea, bilingual staff, and warm care waiting for you!
"""

        director_briefing = """
EXECUTIVE BRIEFING FOR BRONX HEALTH COMMISSIONER & HACKATHON EVALUATION
================================================================================
DEPLOYMENT: November 2026 Mobile Preventative Care Van Schedule (FIPS 36005)

1. METHODOLOGY & ALGORITHMIC RACE-BLIND SITING:
The 4 stops were identified by evaluating all 347 Bronx residential census tracts using a race-blind composite need algorithm. Scoring was driven by primary care shortage scores (HPSA), clinic operating-hour deficits (TOT_OPER_HR_PER_WEEK), uninsured adult rates, and chronic disease prevalence (asthma, hypertension, diabetes). Straight-line Euclidean distance was weighted at 0% to prevent the Urban Distance Illusion.

2. AVOIDANCE OF 5 BRONX DATA TRAPS:
• Trap 1 (Urban Distance Illusion): Solved via MTA transit line proximity and clinic operating hour bottlenecks.
• Trap 2 (Institutional Outliers): Auditor automatically screened and rejected Rikers Island (36005000100, 83.2% group quarters) and Bronx Psychiatric Center (36005028400, 39.8% group quarters).
• Trap 3 (12 km PM2.5 Grid Coarseness): Micro-climate canopy postures deployed (HEPA intake in Hunts Point freight corridor; enclosed heating in Soundview).
• Trap 4 (NSSP ED Missingness): Prevented zero-bias from non-reporting South Bronx emergency rooms.
• Trap 5 (Demographic Siting vs Audit): Race was excluded from ranking inputs (SVI Theme 3 separation) and verified post-hoc.

3. POST-HOC EQUITY AUDIT RATIOS:
• Black & Hispanic Population: 95.7% in served tracts vs. 84.4% Bronx County baseline (Coverage Ratio: 1.13x).
• Poverty Rate: 61.3% in served tracts vs. 38.2% Bronx County baseline (Concentration Ratio: 1.60x).
• Uninsured Adult Rate: 25.1% in served tracts vs. 16.3% Bronx County baseline (Concentration Ratio: 1.54x).

4. HITL AUDIT TRAIL:
The schedule is in 'AUDITED' state awaiting Human-in-the-Loop administrative approval or denial via the Dashboard.
"""

        sched = save_schedule_run(
            db=db,
            proposed_schedule_data=mock_schedule,
            audit_verdict_data=mock_audit,
            outreach_flyers_text=flyers_text,
            director_briefing_text=director_briefing,
            target_month="November 2026"
        )
        print(f"Successfully seeded full 4-Saturday schedule in Cloud SQL: {sched.id} ({sched.status})")
    finally:
        db.close()

if __name__ == "__main__":
    seed()
