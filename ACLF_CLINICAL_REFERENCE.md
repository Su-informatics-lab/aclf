# ACLF Clinical Reference for LLM Prompt

This document is embedded verbatim into the LLM system prompt. It provides
the clinical knowledge needed for ACLF identification and grading.

Source: EASL Clinical Practice Guidelines on ACLF (J Hepatol 2023;79:461-491),
CANONIC study (Moreau et al., Gastroenterology 2013), PREDICT study (Trebicka
et al., J Hepatol 2021).

---

## 1. Definition of ACLF

Acute-on-chronic liver failure (ACLF) is a severe form of acutely decompensated
cirrhosis characterized by:
- Existence of organ system failure(s) in one or more of 6 major organ systems
- High risk of short-term mortality (28-day mortality ≥20%)
- Caused by excessive systemic inflammatory response

ACLF can occur in patients with cirrhosis who experience ACUTE decompensation,
defined as: new onset or worsening of ascites, hepatic encephalopathy,
gastrointestinal hemorrhage, or jaundice requiring hospitalization.

Both patients with and without prior decompensation episodes are included.

## 2. CLIF-C Organ Failure (OF) Scoring System

Evaluate each of 6 organ systems. Assign sub-score 1 (normal), 2 (dysfunction),
or 3 (failure).

### Liver
- Score 1: Total bilirubin < 6.0 mg/dl
- Score 2: Total bilirubin ≥ 6.0 and < 12.0 mg/dl
- Score 3 (FAILURE): Total bilirubin ≥ 12.0 mg/dl

### Kidney
- Score 1: Serum creatinine < 1.5 mg/dl
- Score 2 (DYSFUNCTION): Serum creatinine ≥ 1.5 and < 2.0 mg/dl
- Score 3 (FAILURE): Serum creatinine ≥ 2.0 mg/dl OR need for renal replacement therapy (hemodialysis, CRRT)

### Brain (Hepatic Encephalopathy — West-Haven Criteria)
- Score 1: No hepatic encephalopathy
- Score 2 (DYSFUNCTION): HE Grade I or II
  - Grade I: trivial lack of awareness, shortened attention span, altered sleep, euphoria/anxiety
  - Grade II: lethargy, apathy, disorientation for time, obvious personality change, inappropriate behavior, asterixis
- Score 3 (FAILURE): HE Grade III or IV
  - Grade III: somnolence to semi-stupor, responsive to stimuli, confused, gross disorientation, bizarre behavior
  - Grade IV: coma, unresponsive to verbal or noxious stimuli

KEY NOTE INDICATORS for HE:
- Direct mentions: "hepatic encephalopathy", "HE grade", "West-Haven"
- Grade I-II: "confused", "disoriented to time", "asterixis present", "flapping tremor", "inappropriate behavior", "somnolent but arousable"
- Grade III-IV: "obtunded", "semi-stuporous", "unresponsive", "GCS 3-8", "comatose", "intubated for airway protection due to encephalopathy"
- Treatment indicators: lactulose started/increased, rifaximin prescribed, ammonia level elevated

### Coagulation
- Score 1: INR < 2.0
- Score 2: INR ≥ 2.0 and < 2.5
- Score 3 (FAILURE): INR ≥ 2.5

### Circulation
- Score 1: Mean arterial pressure (MAP) ≥ 70 mmHg, no vasopressors
- Score 2: MAP < 70 mmHg, no vasopressors
- Score 3 (FAILURE): Need for vasopressor therapy

VASOPRESSORS (indicates circulatory failure): norepinephrine (levophed), vasopressin, terlipressin, epinephrine, phenylephrine, dopamine (at pressor doses >5 mcg/kg/min)

NOTE: Midodrine (oral) for hepatorenal syndrome does NOT count as vasopressor therapy for CLIF-C scoring.

KEY NOTE INDICATORS:
- "on pressors", "vasopressor support", "norepinephrine drip", "levophed"
- "hemodynamically unstable", "requiring vasopressor support"
- "MAP maintained >65 on norepinephrine"

### Respiration
- Score 1: PaO₂/FiO₂ > 300 OR SpO₂/FiO₂ > 357
- Score 2: PaO₂/FiO₂ > 200 and ≤ 300 OR SpO₂/FiO₂ > 214 and ≤ 357
- Score 3 (FAILURE): PaO₂/FiO₂ ≤ 200 OR SpO₂/FiO₂ ≤ 214 OR mechanical ventilation for respiratory failure

If PaO₂/FiO₂ is unavailable, use SpO₂/FiO₂ ratio as surrogate.

KEY NOTE INDICATORS:
- "mechanically ventilated", "intubated", "on ventilator"
- "BiPAP", "CPAP" (indicates at least dysfunction)
- "ARDS", "respiratory failure", "oxygen requirement"
- "FiO2 60%", "P/F ratio 150"

IMPORTANT: Intubation for airway protection during GI bleed or for a procedure does NOT count as respiratory failure unless PaO₂/FiO₂ ≤ 200.

## 3. ACLF Grading Algorithm

After scoring all 6 organs, count the number of FAILURES (score = 3):

### No ACLF
- Zero organ failures, OR
- Single organ failure that is NOT kidney, AND no kidney dysfunction (Cr <1.5) AND no brain dysfunction (no HE)

### ACLF Grade 1
- **1a**: Single kidney failure (Cr ≥2.0 or RRT)
- **1b**: Single non-kidney organ failure PLUS kidney dysfunction (Cr 1.5-1.9) AND/OR brain dysfunction (HE grade I-II)

### ACLF Grade 2
- Exactly 2 organ failures (any combination)

### ACLF Grade 3
- **3a**: Exactly 3 organ failures
- **3b**: 4, 5, or 6 organ failures

## 4. Precipitants of ACLF

Systematically evaluate for each of the following. A patient may have multiple simultaneous precipitants.

### Proven bacterial infection
Diagnostic criteria by type:
- **SBP**: Neutrophils in ascites ≥ 250/mm³
- **UTI**: Abnormal urinary sediment (>10 leukocytes/field) + positive culture
- **Pneumonia**: Clinical infection features + new infiltrate on imaging
- **Bacteremia**: Positive blood cultures
- **Skin/soft tissue**: Clinical features + swelling, erythema, heat, tenderness
- **Cholangitis**: Cholestasis + RUQ pain/jaundice + biliary obstruction on imaging
- **C. difficile**: ≥3 unformed stools + toxigenic C. diff in stool

### Severe alcohol-related hepatitis
NIAAA criteria (if biopsy unavailable):
1. Active alcohol consumption, AND
2. At least 3 of: bilirubin >3 mg/dl, AST >50 IU/ml, AST/ALT >1.5, AST and ALT <400 IU/ml

### GI hemorrhage with shock
- Hematemesis, melena, or sudden hemoglobin drop ≥2 g/dl
- PLUS hypovolemic shock

### Drug-induced brain injury
- Recent sedative administration (benzodiazepines, opioids)
- Leading to acute encephalopathy

### Drug-induced acute kidney injury
- Recent nephrotoxic drug: NSAIDs, ACEi/ARBs, aminoglycosides, vancomycin, IV contrast, amphotericin B

### Hepatitis B reactivation
- Elevated HBV DNA, elevated AST/ALT, possibly positive anti-HBc IgM

### No identifiable precipitant
- Systematic workup negative for all above (occurs in ~35% of ACLF cases)

## 5. Assessment Instructions

For each patient, you must:

1. **Determine if acute decompensation is present**: Is there new/worsening ascites, encephalopathy, GI hemorrhage, or jaundice requiring hospitalization?

2. **Identify the acute episode time window**: Focus on the worst hospitalization episode. Use labs, vitals, and clinical notes from ±7 days of the admission.

3. **Score each of the 6 organ systems**: Use the WORST (peak) value during the acute episode.
   - For liver: use peak total bilirubin
   - For kidney: use peak serum creatinine (or note RRT)
   - For brain: use worst documented HE grade
   - For coagulation: use peak INR
   - For circulation: note any vasopressor use
   - For respiration: use worst PaO₂/FiO₂ ratio (or note mechanical ventilation)

4. **Identify precipitants**: Apply the diagnostic criteria from §4 above.

5. **Record additional data** for CLIF-C prognostic scores:
   - Age
   - WBC count (closest to the acute episode)
   - Serum sodium (closest to the acute episode)

6. **Assess data quality**: Is there enough clinical documentation to make a reliable assessment?
   - "sufficient": lab values available for most organs, clinical notes describe the episode
   - "limited": some organs assessable, others missing data
   - "insufficient": too little data to assess ACLF

## 6. Common pitfalls to avoid

- **Do NOT assume normal if data is missing.** If no creatinine is documented, the kidney score is uncertain, not "normal." Flag this in the evidence.
- **Distinguish chronic from acute.** A patient with CKD and baseline creatinine 2.5 should NOT automatically get kidney failure score. Look for ACUTE rise above baseline.
- **HE grading requires clinical description.** "Encephalopathy" alone could be any grade. Look for specific descriptors (asterixis → grade II, coma → grade IV).
- **Vasopressor context matters.** Vasopressors given briefly during a procedure or for sedation do NOT indicate circulatory failure. Look for sustained vasopressor support for hemodynamic instability.
- **Intubation context matters.** Elective intubation for a procedure or for airway protection during GI bleed is NOT respiratory failure unless PaO₂/FiO₂ ≤ 200.
- **Multiple episodes.** A patient may have multiple decompensation episodes over time. Assess the most severe episode (highest ACLF grade).
