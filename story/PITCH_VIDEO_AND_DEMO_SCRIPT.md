# Pitch Video & Live Demo Script (3–4 Minute Walkthrough)
## Dynamic Public Health Equity & Preventative Mobile Care Broker — Bronx County (`FIPS 36005`)

> **Submission Requirement Reminder**:
> Judges score asynchronously from your **GitHub Repo**, **Qwiklabs Project**, **Pitch Deck**, and **Pitch Video (screen-share walkthrough)**. There is no live Q&A—every judge question must be answered explicitly during this walkthrough.

---

## Part 1: 3.5-Minute Timed Screen-Share Script

### [0:00 – 0:35] Hook & The Bronx Siting Paradox (Show Slide 1 $\rightarrow$ Tab 2 Map)
- **What's on screen**: Start on Slide 1 (or Tab 2 Interactive Bronx Map showing 347 tracts and 252 existing clinics).
- **What you say**:
  > "We built the **Bronx Mobile Care Broker** for Challenge 5. Our agent helps a county outreach lead, community health workers, and the Health Department Director in **Bronx County, New York (`FIPS 36005`)** decide where to park a preventative mobile clinic across four Saturdays—and explain why in both clinical detail and 6th-grade English and Spanish.
  >
  > Here is the first thing our data revealed that breaks a naive agent: in the Bronx, **straight-line distance is a 390-meter illusion**. The median census tract is `0.39 km` from a clinic, and `94%` of tracts have a `0 km` distance gap to a safety-net site. Worse, if you rank Bronx tracts by raw asthma or diabetes rates, your top two recommendations are **Tract `36005028400`—the Bronx Psychiatric Center—and Tract `36005000100`—the Rikers Island Jail Complex**, both `100%` institutional group quarters."

---

### [0:35 – 1:25] Multi-Agent ADK Architecture & Autonomous Self-Correction (Show Tab 4 Trace Inspector)
- **What's on screen**: Switch to **Tab 4 (Director Chat & Equity/Audit Inspector)** and click the **ADK `session.state` & Rejection Loop Trace**. Toggle/highlight Iteration 1 $\rightarrow$ Iteration 2.
- **What you say**:
  > "That is why our system uses **7 specialized Google ADK agents** across three stages:
  > 1. First, a `ParallelAgent` runs three domain scouts concurrently—`BurdenScout`, `AccessScout`, and `EnvSurveillanceScout`—writing to distinct `session.state` keys (`burden_findings`, `access_findings`, `env_findings`).
  > 2. Second, a `LoopAgent` pairs `SchedulePlannerAgent` with `EquityAndScaleAuditorAgent`. Why must the Auditor be a separate agent with `include_contents='none'`? Because Challenge 5 forbids using race as a ranking input, but requires auditing the output against race. Our Auditor has access to the demographic columns the Planner is denied, and it does not share the Planner's conversation history so it never rubber-stamps the plan.
  >
  > Look at our execution trace right here—this answers **Judge Question 4 (where our system rejected its own first answer)**: when institutional outliers aren't pre-filtered, Iteration 1 proposes `36005028400` (Psychiatric Center) and `36005000100` (Rikers Island). `EquityAndScaleAuditorAgent` inspects `session.state['proposed_schedule']`, catches `pct_group_quarters = 100%`, rejects the plan in `session.state['audit_verdict']`, and forces `SchedulePlannerAgent` to self-correct on Iteration 2 to four true residential neighborhoods across four distinct Medicaid Exception HPSA zones."

---

### [1:25 – 2:15] Live Demo: The 4-Saturday Schedule & Admin "Deny with Reason" Re-Plan (Show Tab 1 & Tab 2)
- **What's on screen**: Switch to **Tab 1 (Monthly Scheduler & HITL Re-Planner)**. Point out the 4 Saturday cards, then click **"Deny with Reason"** on Saturday 2 (`36005008600` Pelham), select *"Road Construction / Street Closure"*, type *"ConEd utility work blocking White Plains Rd plaza"*, and submit.
- **What you say**:
  > "In **Tab 1**, the Healthcare Admin gets a calendar-ready 4-Saturday plan across four distinct HPSA zones:
  > - **Saturday 1: High Bridge (`36005006700`, HPSA 18)** — `27.5%` uninsured, `86.2%` no vehicle, anchored at Mullaly Park Plaza (`165th St & Ogden Ave`).
  > - **Saturday 2: Pelham (`36005008600`, HPSA 19)** — the highest shortage score in the Bronx, `37.6%` high blood pressure.
  > - **Saturday 3: Fordham (`36005040302`, HPSA 17)** — `43.8%` limited English proficiency.
  > - **Saturday 4: Hunts Point (`36005002300`, HPSA 16)** — `13.6%` asthma and `86.3%` no vehicle.
  >
  > Notice each stop includes live Saturday weather and air quality posture (`get_saturday_weather_and_air_quality`) and a custom clinical kit: because `disease_weekly` has **0 out of 212 weeks populated (`100% NULL`)** in the Bronx, our agent flags an active NSSP surveillance blind spot and packs **Point-of-Care Rapid Flu/COVID/RSV Swab Kits** on the van. And because `exposure_tracts.mean_pm` comes from a coarse **12 km satellite grid** (`8.08–8.37 µg/m³`), we block `mean_pm` from tract ranking and instead use peak `max_pm` (`57.0 µg/m³`) plus live AQI to stock nebulizers and pediatric spacers.
  >
  > Now watch what happens when operational reality hits: the Admin clicks **Deny with Reason** on Saturday 2 because ConEd utility work is blocking the plaza. Our `replan_rejected_saturday` tool appends `36005008600` to `session.state['admin_excluded_tracts']`, re-runs the Planner and Equity Auditor live, and swaps in backup tract **`36005022000`** (or cross-zone #5 **`36005020501` in Crotona**) while re-verifying demographic equity."

---

### [2:15 – 3:05] Contradictory Personas: Bilingual 6th-Grade Flyer vs. Executive Briefing & Equity Audit (Show Tab 3 & Tab 4)
- **What's on screen**: Switch to **Tab 3 (Public Notice & Bilingual Flyer Studio)** showing the English/Spanish flyer and SMS copy, then back to **Tab 4** showing the **Post-Hoc Demographic Equity Scorecard** and a live Director Chat prompt.
- **What you say**:
  > "Why can't one prompt write all of our outputs? Compare **Tab 3** and **Tab 4**.
  > In **Tab 3**, `CommunityOutreachAgent` writes for a resident standing at a bus stop: strictly **6th-grade reading level**, side-by-side **English and Spanish**, zero database acronyms (`FIPS`, `HPSA`, `SVI`, and `FQHC` are banned), anchored to Mullaly Park and the 4/B/D trains, leading with: *'Free care. No health insurance needed. No ID required.'*
  >
  > In **Tab 4**, `DirectorBriefingAgent` follows the exact opposite instructions: it cites exact census tract GEOIDs, distinguishes **modeled CDC PLACES estimates** from **measured ACS SVI and HRSA facility hours (`TOT_OPER_HR_PER_WEEK`)**, states that federal clinic distances are upper bounds, and presents our **Post-Hoc Demographic Equity Audit**: across the `19,977` residents in our four selected tracts, **`69.8%` are Hispanic (`1.23x` the Bronx baseline)**, **`93.9%` are Black or Hispanic (vs. `84.8%` baseline)**, and **`38.6%` live below the poverty line (`1.41x` baseline)**—proving our race-blind structural model delivers equitable outcomes."

---

## Part 2: Quick Reference — Verbatim Answers to All 8 Judge Checklist Items

| Judge Checklist Item | Exact Proof in Our Deck & Demo |
| :--- | :--- |
| **1. Delete any one agent—does the answer get worse?** | • Delete `EquityAndScaleAuditorAgent` $\rightarrow$ Van is dispatched to Rikers Island (`36005000100`) & Bronx Psychiatric Center (`36005028400`).<br>• Delete `AccessScout` $\rightarrow$ Planner ranks on `0.39 km` straight-line distance instead of `HPSA_SCORE` and clinic operating hours.<br>• Delete `CommunityOutreachAgent` $\rightarrow$ Residents get hedged clinical text full of `FIPS`/`HPSA`/`SVI` jargon. |
| **2. Show a key in `session.state` written by one agent and read by another.** | • `burden_findings`, `access_findings`, `env_findings` (written by Stage 1 Parallel Scouts $\rightarrow$ read by `SchedulePlannerAgent`).<br>• `proposed_schedule` (written by `SchedulePlannerAgent` $\rightarrow$ read by `EquityAndScaleAuditorAgent`, `DirectorBriefingAgent`, `CommunityOutreachAgent`).<br>• `audit_verdict` & `admin_excluded_tracts` (written by Auditor / HITL tool $\rightarrow$ read by `SchedulePlannerAgent`). |
| **3. Show two agents whose instructions genuinely conflict.** | • `DirectorBriefingAgent`: *"Hedge where modeled, cite exact 11-digit tract GEOIDs, HPSA scores, SVI percentiles, and confidence/scale limits."*<br>• `CommunityOutreachAgent`: *"Warm, plain language, 6th-grade reading level, bilingual English and Spanish. NEVER output GEOIDs, FIPS codes, HPSA, SVI, or FQHC."* |
| **4. Show where the system rejected its own first answer.** | • **Autonomous Loop**: Iteration 1 proposes `36005028400` (Psychiatric Center) / `36005000100` (Rikers Island) $\rightarrow$ Auditor rejects due to `pct_group_quarters = 100%` $\rightarrow$ Iteration 2 self-corrects to High Bridge, Pelham, Fordham, Hunts Point.<br>• **HITL Loop**: Admin clicks *Deny with Reason* $\rightarrow$ `replan_rejected_saturday` excludes stop and re-audits replacement tract. |
| **5. Which numbers are measured vs. modeled?** | • **Modeled**: CDC PLACES chronic prevalence (`pct_asthma`, `pct_diabetes`, `pct_high_bp`, `pct_checkup`, `pct_uninsured` via MRP) and EPA `exposure_tracts` (`mean_pm`, `max_pm` via 12 km Downscaler model).<br>• **Measured**: CDC SVI (`pct_no_vehicle`, `pct_limited_english`, `pct_group_quarters` from ACS 5-year survey), HRSA/CMS `care_sites` (`TOT_OPER_HR_PER_WEEK`), `shortage_areas` (`HPSA_SCORE`), and straight-line `tract_access` distances. |
| **6. Which resolution did each claim come from?** | • **Census Tract (`347` rows)**: `burden_tracts`, `tract_access`, `shortage_areas`.<br>• **12 km Modeling Grid (`361` rows)**: `exposure_tracts` (`mean_pm` blocked from neighborhood ranking).<br>• **Facility Point (`252` / `8` rows)**: `care_sites`, `shortage_facilities` (never `UNION`ed with `shortage_areas`).<br>• **Multi-County Health Service Area (`212` rows on county key `36005`)**: `disease_weekly` (`100% NULL` in Bronx). |
| **7. Did you run the post-hoc demographic equity audit?** | Yes (`run_posthoc_equity_audit` on `19,977` residents across the 4 selected tracts vs. `1,472,508` Bronx baseline): **`69.8%` Hispanic (`1.23x`)**, **`93.9%` Black + Hispanic (`1.11x`)**, **`38.6%` poverty (`1.41x`)**, **`24.3%` uninsured (`1.55x`)** — **PASS**. |
| **8. Honest limitations named out loud?** | 1. Straight-line distance (`0.39 km` median) ignores transit/highway barriers (FHWA transit dataset is `CC BY-NC 4.0`, so excluded).<br>2. Federal facility list omits municipal/free/charity clinics and pharmacies (distances are upper bounds).<br>3. `disease_weekly` is `100% NULL` in the Bronx.<br>4. PLACES estimates are modeled with confidence intervals (`_crude95ci`). |
