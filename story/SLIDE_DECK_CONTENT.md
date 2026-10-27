# Story Track — Pitch Deck Blueprint & Speaker Notes
## Dynamic Public Health Equity & Preventative Mobile Care Broker (Bronx County, NY · `FIPS 36005`)

> **Template Presentation**: [Google Slides Deck (`1AdzeWSJwT_U-zO1_H9jaEEt_lIxMIYJUjNR0ixfXpIo`)](https://docs.google.com/presentation/d/1AdzeWSJwT_U-zO1_H9jaEEt_lIxMIYJUjNR0ixfXpIo/edit?slide=id.g3f76d7e2a9b_0_19#slide=id.g3f76d7e2a9b_0_19)
> **Design Principle**: Front-loaded, high-impact visual hierarchy. Assume judges score asynchronously from the deck and pitch video with zero Q&A. Every mandatory rubric question is answered explicitly on-slide.

---

## Slide 1 — Title & The Core Thesis (Front-Loaded Hook)

### On-Slide Copy
- **Headline**: **Bronx Mobile Care Broker**
- **Sub-headline**: *One County. One Van. Four Saturdays. And a Reason You Can Say Out Loud.*
- **The Challenge 5 Opening Statement**:
  > *"Our agent helps **the Mobile Outreach Lead, Community Health Workers, and Health Department Director** in **Bronx County, NY (`FIPS 36005`)** decide **where to park our preventative care van across 4 Saturdays—and how to explain that choice in plain English and Spanish**, and the thing it knows that a spreadsheet does not is **that in the Bronx, straight-line distance is a 390-meter illusion and raw disease rankings dispatch the van to Rikers Island unless an isolated auditor agent enforces institutional, multi-scale, and equity guardrails**."*
- **3 Callout Stat Cards**:
  - **`390 m` (`0.39 km`)** — Median distance to a clinic in the Bronx (`94%` of tracts have `0 km` uninsured distance gap). **Distance doesn't separate neighborhoods here—barriers do.**
  - **`100%` Group Quarters** — Top raw asthma/diabetes tracts (`36005000100` Rikers Island & `36005028400` Bronx Psychiatric Center) caught & rejected autonomously.
  - **`19,977` Residents Reached** — Across 4 distinct Medicaid Exception HPSA zones (`1.23x` Hispanic coverage, `1.41x` poverty concentration in post-hoc equity audit).

### Speaker Notes (0:00 – 0:30)
"A mobile clinic has four Saturdays next month and 347 census tracts in Bronx County. If you build the obvious spreadsheet—rank by distance to a safety-net clinic or rank by raw disease prevalence—you fail in the first ten minutes. In the Bronx, the median tract is 390 meters from a clinic, so distance is flat. Worse, if you rank by raw asthma or diabetes rates, your top recommendations are Tract 36005028400—the Bronx Psychiatric Center—and Tract 36005000100—the Rikers Island Jail Complex. Our multi-agent system solves what a spreadsheet cannot: it separates structural access barriers from spatial illusions, autonomously rejects institutional outliers, audits its race-blind schedule for demographic equity, and translates clinical siting data into 6th-grade English and Spanish neighborhood outreach."

---

## Slide 2 — The Problem & The 5 Bronx Data Traps We Caught

### On-Slide Copy
- **Headline**: **Why Naive Rankings Fail in Bronx County (`FIPS 36005`)**
- **Sub-headline**: *Five real defects across 4 spatial resolutions—and how our architecture guards against every one.*

| # | The Bronx Data Trap | What Happens to a Naive Agent | Our Architectural Guardrail |
| :---: | :--- | :--- | :--- |
| **1** | **The `390 m` Urban Distance Trap** (`tract_access`) | `94%` of tracts (`327/347`) have `extra_km_if_uninsured = 0 km` (max `0.65 km`). Ranking by distance picks low-need outer tracts near parks. | Weight distance at `0%` when `max_gap < 1 km`. Rank on **HPSA Score (`16–19`)**, **clinic hours (`8–20 hr/wk` bottlenecks)**, **uninsured (`pct_uninsured`)**, **chronic burden**, and **transport/language barriers**. |
| **2** | **The Rikers Island / Institutional Trap** (`burden_tracts`) | Top raw asthma/diabetes tracts are **`36005000100` (Rikers Island, pop `3,772`)** & **`36005028400` (Bronx Psychiatric, pop `297`)**—both `100%` group quarters with `NULL` vehicle data from `-999` SVI sentinels. | Two-layer filter (`pct_group_quarters <= 25%`, `total_pop >= 500`) + autonomous rejection loop in `EquityAndScaleAuditorAgent`. |
| **3** | **The 12 km $\text{PM}_{2.5}$ Grid Illusion** (`exposure_tracts`) | Annual `mean_pm` varies by only `1.33%` (`8.08–8.37 µg/m³`) across all 361 tracts because EPA models on a 12 km grid. | Block `mean_pm` from tract ranking. Combine peak `max_pm` (**`57.0 µg/m³`**) + **live Saturday Weather/AQI** with tract `pct_asthma` to stock nebulizer & spacer kits. |
| **4** | **The NSSP Dark-Signal Trap** (`disease_weekly`) | Arrives with `212` weekly rows on county key `36005`, but **100% NULL (`0/212` weeks)** for COVID, Flu, and RSV (`Data Unavailable`). | Flag an **Active Surveillance Blind Spot** and equip the van with **Point-of-Care Rapid Flu/COVID/RSV Swab Kits** as a mobile sentinel node. |
| **5** | **Race Input Ban vs. Audit Mandate** (`burden_tracts`) | Either illegally uses `pct_race_*` in ranking or skips demographic verification entirely ("fairness through unawareness"). | Strict context isolation: Planner is banned from `pct_race_*`; isolated Auditor runs `run_posthoc_equity_audit` after selection. |

### Speaker Notes (0:30 – 1:10)
"Every table in `a4i_health` wears an identifier that looks more precise than it is. First, `exposure_tracts` has an 11-digit tract ID, but annual PM2.5 sits between 8.08 and 8.37 micrograms per cubic meter across the entire borough—a 1.3% spread—because it's interpolated from a 12-kilometer grid. Second, `disease_weekly` has 212 rows for FIPS 36005, and every single respiratory column is NULL. Third, HRSA's facility layer (`shortage_facilities`) marks 8 existing FQHCs while `shortage_areas` marks 338 underserved tracts across 7 Medicaid Exception zones—merging them sites a van on top of existing hospitals. Our system checks the grain and completeness before a single tract is ranked."

---

## Slide 3 — Why Multi-Agent? Architecture & The 4 Judge Proof Points

### On-Slide Copy
- **Headline**: **Architecture Forced by the Problem (Google ADK + Vertex AI)**
- **Architecture Flow**:
  1. **Stage 1 — `ParallelAgent` (3 Concurrent Domain Scouts)**:
     - `BurdenScout` $\rightarrow$ `session.state["burden_findings"]` (PLACES + SVI, race-blind)
     - `AccessScout` $\rightarrow$ `session.state["access_findings"]` (7 `ME` HPSA zones + 252 clinics by `TOT_OPER_HR_PER_WEEK`)
     - `EnvSurveillanceScout` $\rightarrow$ `session.state["env_findings"]` (`max_pm = 57.0 µg/m³`, `0/212` NSSP blind spot, live Saturday Weather/AQI)
  2. **Stage 2 — `LoopAgent` (`max_iterations=3`, Autonomous Plan $\leftrightarrow$ Audit + HITL Re-Plan)**:
     - `SchedulePlannerAgent` writes `session.state["proposed_schedule"]`
     - `EquityAndScaleAuditorAgent` (`include_contents="none"`) reads only `proposed_schedule`, runs `run_posthoc_equity_audit`, writes `session.state["audit_verdict"]`, and either rejects or calls `exit_loop`.
     - Healthcare Admin **Approve / Deny with Reason** invokes `replan_rejected_saturday` $\rightarrow$ updates `session.state["admin_excluded_tracts"]`.
  3. **Stage 3 — Contradictory Persona Agents**:
     - `DirectorBriefingAgent` (`session.state["director_briefing"]`): Hedged, cites exact `geo_id`, `HPSA_SCORE`, scale caveats, and equity ratios.
     - `CommunityOutreachAgent` (`session.state["community_notices"]`): Strictly 6th-grade reading level, bilingual **English + Spanish**, zero acronyms (`FIPS`/`HPSA`/`SVI`/`FQHC` banned), anchored to Google Maps landmarks & MTA lines.

- **Direct Answers to the 4 Judge Architecture Questions**:
  1. *Delete any one agent—does it get worse?* Delete `EquityAndScaleAuditorAgent` $\rightarrow$ van goes to Rikers Island (`36005000100`). Delete `CommunityOutreachAgent` $\rightarrow$ flyers contain clinical hedging and database IDs.
  2. *State keys passed between agents?* `burden_findings`, `access_findings`, `env_findings` $\rightarrow$ `proposed_schedule` $\rightarrow$ `audit_verdict` & `admin_excluded_tracts`.
  3. *Two agents with conflicting instructions?* `DirectorBriefingAgent` (cite every tract ID, confidence caveat, and metric) vs. `CommunityOutreachAgent` (ban all acronyms/IDs; warm 6th-grade EN/ES).
  4. *Where did the system reject its own first answer?* Iteration 1 $\rightarrow$ 2: Auditor rejects `36005028400` (Psychiatric Center) & `36005000100` (Rikers Island) for `pct_group_quarters = 100%`, plus live Admin Deny-with-Reason re-planning.

### Speaker Notes (1:10 – 1:50)
"We didn't choose a 7-agent ADK architecture for decoration—the rules of Challenge 5 force it. First, evidence gathering across burden, access, and environmental surveillance is embarrassingly parallel, so three Scouts run concurrently into separate `session.state` keys. Second, because race is banned as a model input but required as an output audit, `EquityAndScaleAuditorAgent` runs in an isolated context (`include_contents='none'`) inside a `LoopAgent`—it sees demographic columns the Planner is denied, rejects institutional outliers on Iteration 1, and forces the Planner to self-correct. Third, our two output agents have genuinely contradictory prompts: `DirectorBriefingAgent` hedges and cites exact tract GEOIDs and scale limits, while `CommunityOutreachAgent` is strictly forbidden from using acronyms and writes 6th-grade English and Spanish flyers."

---

## Slide 4 — The Output Artifact (Part 1): The 4-Saturday Bronx Clinic Plan

### On-Slide Copy
- **Headline**: **Where the Van Goes, and Why (4 Saturdays · 4 Distinct HPSA Zones)**
- **Composite Need Formula (`score_bronx_tracts`)**:
  $$\text{Score} = 25\%\text{ HPSA Severity} + 25\%\text{ Uninsured \& Clinic Hours Gap} + 30\%\text{ Chronic Burden} + 20\%\text{ Mobility \& Language Barriers}$$

| Saturday | HPSA Zone (`Score`) | Tract (`geo_id`) & Pop | Why This Street & Not the Next One Over | Google Maps Landmark & Transit | Clinical Kit & Weather/AQ Posture | Backup If Admin Denies |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Sat 1** | **ME - High Bridge** (`18`) | **`36005006700`**<br>Pop: `6,893` | **`27.5%` uninsured**, `21.3%` diabetes, `13.0%` asthma, `86.2%` no vehicle, `svi_t1 = 0.990`. Nearby clinics bottleneck on weekends. | **165th St & Ogden Ave / Mullaly Park Plaza**<br>Subway `4/B/D`, `Bx13/Bx6` | **Asthma & Uninsured Primary Care Kit** + Medicaid/NYC Care navigator + Rapid Flu/COVID/RSV swabs | **`36005019500`** (High Bridge, pop `7,077`, `23.1%` uninsured) |
| **Sat 2** | **ME - Pelham** (`19` — Highest) | **`36005008600`**<br>Pop: `4,145` | **Highest HPSA (`19`) in Bronx**, `37.6%` high BP, `23.5%` uninsured, `13.7%` asthma, `77.1%` no vehicle (`svi_t1 = 0.994`). | **White Plains Rd & Pelham Pkwy S Hub**<br>Subway `2/5`, `Bx12/Bx22/Bx39` | **Cardiometabolic & Respiratory Surge Kit**: A1C/BP med check + nebulizers (`57 µg/m³` peak PM2.5 prep) | **`36005022000`** (Pelham, pop `1,743`, `29.1%` uninsured) |
| **Sat 3** | **ME - Fordham** (`17`) | **`36005040302`**<br>Pop: `4,197` | **`43.8%` limited English**, `24.7%` uninsured, `18.3%` diabetes, `21.0%` lack transport, `69.9%` no vehicle. | **W 188th St & Grand Concourse / Fordham Hub**<br>Subway `4/B/D`, `Bx1/Bx2/Bx12-SBS` | **100% Spanish-First Preventative Kit**: Bilingual clinicians, BP/glucose screening, NYC Care enrollment | **`36005039901`** (Fordham, pop `5,303`, `41.5%` limited English) |
| **Sat 4** | **ME - Hunts Point** (`16`) | **`36005002300`**<br>Pop: `4,742` | **`13.6%` asthma**, `37.9%` high BP, `21.8%` diabetes, **`86.3%` no vehicle**, `37.3%` limited English (`svi_t1 = 0.994`). | **Hunts Point Ave & Southern Blvd / Crames Sq**<br>Subway `6`, `Bx6-SBS/Bx5` | **Environmental Asthma & Industrial Corridor Kit**: Pediatric spirometry, EN/ES asthma plans, rapid swabs | **`36005020501`** (ME - Crotona, `HPSA = 17`, pop `7,859`) |

### Speaker Notes (1:50 – 2:30)
"Here is the calendar an outreach lead can put on the wall on Friday. Instead of clustering all four Saturdays in one neighborhood, our Planner and Auditor spread the van across four distinct Medicaid Exception HPSA zones: High Bridge, Pelham, Fordham, and Hunts Point—directly serving nearly 20,000 residents. Look at Saturday 1 in High Bridge, Tract 36005006700: 27.5% of working-age adults are uninsured and 86.2% of households have no car. Each stop is paired with a real Google Maps street anchor, MTA subway and bus lines, live Saturday weather and AQI posture, a tailored clinical kit, and a pre-audited backup tract if the Healthcare Admin clicks 'Deny with Reason' due to road work or a street fair."

---

## Slide 5 — The Output Artifact (Parts 2, 3 & 4): Audit, Limitations & Bilingual Outreach

### On-Slide Copy
- **Headline**: **Audited for Equity. Honest About Scale. Built for Residents.**

#### Left Column — Part 2: Measured vs. Modeled & What We Cannot See
- **Modeled Estimates (`burden_tracts`, `exposure_tracts`)**:
  - CDC PLACES disease rates are **small-area modeled predictions (MRP)** with overlapping confidence intervals—never patient counts.
  - EPA $\text{PM}_{2.5}$ (`mean_pm`) is a **12 km grid** (`8.08–8.37 µg/m³` across the Bronx)—used only via daily `max_pm` (`57.0 µg/m³`) for kit stocking.
- **Measured Realities & Blind Spots (`care_sites`, `disease_weekly`)**:
  - Distances (`0.39 km` median) are straight-line **upper bounds to federal sites only** (excludes free/municipal/pharmacy clinics). We weight `TOT_OPER_HR_PER_WEEK` (`8–112 hrs/wk`) to catch part-time clinic bottlenecks.
  - `disease_weekly` is a **multi-county Health Service Area metric** and is **100% NULL (`0/212` weeks)** in the Bronx—so the van carries rapid Flu/COVID/RSV swabs.

#### Center Column — Part 3: Post-Hoc Demographic Equity Audit (`run_posthoc_equity_audit`)
*Race/ethnicity was excluded from ranking and audited post-hoc across `19,977` residents in the 4 selected tracts vs. `1,472,508` Bronx baseline:*

| Metric | 4 Selected Stops | Bronx Baseline | Coverage Ratio | Verdict |
| :--- | :---: | :---: | :---: | :---: |
| **Hispanic / Latino** | **`69.8%`** | `56.6%` | **`1.23x`** | ✅ **PASS** |
| **Combined Black + Hispanic** | **`93.9%`** | `84.8%` | **`1.11x`** | ✅ **PASS** |
| **Below Poverty Line** | **`38.6%`** | `27.4%` | **`1.41x`** | ✅ **PASS** |
| **Uninsured (`18–64`)** | **`24.3%`** | `15.7%` | **`1.55x`** | ✅ **PASS** |

#### Right Column — Part 4: Zero-Jargon Bilingual Community Flyer (`CommunityOutreachAgent`)
- **English (6th-Grade Reading Level)**:
  > **FREE MOBILE HEALTH VAN — HIGH BRIDGE**
  > **This Saturday, 9 AM – 4 PM at Mullaly Park Plaza (165th St & Ogden Ave — near 4/B/D & Bx13)**
  > Free asthma inhalers, blood pressure & blood sugar checks, and flu/COVID tests. **No health insurance needed. No ID required. Walk right in!**
- **Español (Nivel de lectura accesible)**:
  > **CLÍNICA MÓVIL GRATUITA — HIGH BRIDGE**
  > **Este sábado, 9 AM – 4 PM en Mullaly Park Plaza (Calle 165 y Ogden Ave — cerca del tren 4/B/D y Bx13)**
  > Chequeos gratis de asma, presión arterial, azúcar en la sangre y pruebas rápidas. **Sin seguro médico. Sin identificación. ¡Atendemos en español sin cita!**

### Speaker Notes (2:30 – 3:00)
"Finally, our system delivers the three things most teams skip. First, an honest accounting of what is measured versus modeled and what federal data cannot see. Second, our post-hoc demographic equity audit: even though race was strictly excluded from the Planner's SQL, auditing our four selected tracts against the Bronx baseline shows 69.8% Hispanic residents—1.23 times the borough average—93.9% combined Black and Hispanic residents, and 1.41 times the poverty rate. Third, `CommunityOutreachAgent` turns that plan into print-ready 6th-grade English and Spanish flyers, WhatsApp alerts, and CHW door-knocking scripts with zero jargon. And next, we close the federal data loop with a conversational Field-Report Agent so the nurse practitioner driving back on Saturday feeds ground-truth clinic capacity and walk-in barriers straight back into BigQuery."
