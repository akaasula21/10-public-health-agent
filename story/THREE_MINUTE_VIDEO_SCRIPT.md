# 3-Minute Video Pitch Script & Talking Points
## Dynamic Public Health Equity & Preventative Mobile Care Broker — Bronx County, NY (`FIPS 36005`)

> **Timing Goal**: Under 3 minutes spoken (~415 words at a conversational ~140 WPM pace).  
> **Format**: Conversational bullet points for screen-share demo and video voiceover.

---

### Video Hook (0:00 – 0:20 | ~20 sec)
* A mobile health van has one driver, one nurse, and four Saturdays a month.
* In the Bronx, picking where to park isn’t as simple as sorting by who is sickest—if you do that, your top recommendations are Rikers Island Jail and a state psychiatric hospital.
* Our agent picks the four best spots and explains the decision to both city directors and neighborhood residents.

---

### A. Top 5 Capabilities (0:20 – 1:10 | ~50 sec)

1. **Finds True Healthcare Deserts**
   * *What it does*: Ranks 347 Bronx neighborhoods by chronic illness, uninsured rates, and clinics that close early on weekends.
   * *Why it’s important*: Puts the van where people have nowhere else to go, rather than guessing based on politics.

2. **Catches and Rejects Locked Facilities**
   * *What it does*: Automatically detects institutional facilities like jails or inpatient centers and redirects the van to residential streets.
   * *Why it’s important*: Stops the van from being sent to places where everyday walk-in patients can’t enter.

3. **Audits Its Own Plan for Fairness**
   * *What it does*: A separate auditor agent checks the final stops to verify that Black and Hispanic communities are prioritized—without using race to pick the locations.
   * *Why it’s important*: Keeps the selection objective and legally compliant while ensuring care reaches underserved groups.

4. **Custom-Packs the Van’s Medical Supplies**
   * *What it does*: Looks at historical air quality and local disease risks to pack specific gear, like pediatric asthma spacers and rapid flu and COVID swabs.
   * *Why it’s important*: Nurses arrive with the exact supplies and tests that neighborhood needs that day.

5. **Translates Plans for Two Different Audiences**
   * *What it does*: Generates simple, 6th-grade bilingual English/Spanish flyers for residents, alongside a rigorous statistical briefing for health officials.
   * *Why it’s important*: Patients get welcoming flyers they can trust, while directors get the hard numbers needed for grant funding.

---

### B. Top Decisions Made (1:10 – 1:50 | ~40 sec)

1. **Ignored Physical Distance in the Formula**
   * *Why*: The average Bronx resident lives just 400 meters from a clinic. The real obstacles are limited weekend hours, high costs, and language barriers—not distance.

2. **Kept the Auditor Agent Separate from the Planner**
   * *Why*: When an AI critiques its own work in the same prompt, it defends its mistakes. An isolated auditor can reject flawed plans and force a re-plan.

3. **Kept Regional Air Pollution Off Neighborhood Rankings**
   * *Why*: Federal air pollution data covers a wide 12-kilometer grid across the whole borough. We use it to pack inhalers on bad air days, not to rank neighborhoods against each other.

4. **Gave Human Outreach Leads the Final Word**
   * *Why*: If a street is blocked by construction, the outreach lead can reject a stop with one click, and the system finds an approved backup in seconds.

---

### C. Constraints: What It Can’t Do (1:50 – 2:20 | ~30 sec)

* **Cannot Diagnose Patients or Prescribe Medicine**
  * *Why*: It is an operations planner, not a doctor. All clinical decisions belong to the licensed nurse on the van.
* **Cannot Track Real-Time Respiratory Outbreaks**
  * *Why*: Federal emergency room data for the Bronx is completely missing across all 212 historical weeks—which is why the van carries rapid test kits instead.
* **Cannot Guarantee Street Parking or Clearances**
  * *Why*: It uses public health data, not live city parking rules or construction permits.

---

### D. Architecture: The Deployed Pieces (2:20 – 2:50 | ~30 sec)

* **BigQuery Data Layer**: Holds federal health, shortage, and census data for all 347 Bronx tracts, paired with fast local snapshots.
* **Google Agent Development Kit (ADK)**: Coordinates the Planner and Auditor agents in a self-correcting feedback loop powered by Gemini.
* **Specialized Sub-Agents**: Dedicated workers divide the labor—handling planning, equity auditing, bilingual flyer creation, and executive reporting.
* **Cloud SQL Database**: Stores monthly calendars, tracks human approvals, and logs audit traces for complete transparency.

---

### Wrap-Up (2:50 – 3:00 | ~10 sec)
* One county, one van, four Saturdays—and an honest reason for every stop.
