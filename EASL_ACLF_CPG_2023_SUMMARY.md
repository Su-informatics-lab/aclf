# EASL Clinical Practice Guidelines on ACLF — Key Extracts

Source: European Association for the Study of the Liver. EASL Clinical Practice
Guidelines on acute-on-chronic liver failure. J Hepatol. 2023;79:461-491.
doi:10.1016/j.jhep.2023.04.021

This is a condensed reference. For full text, see the original publication.

---

## Key recommendations (strong consensus, LoE 2)

1. Both patients with prior decompensation and those without should be included in the ACLF definition.

2. Organ failures as defined by EASL-CLIF-C criteria should be used for ACLF diagnosis.

3. The CLIF-C ACLF score outperforms MELD, MELD-Na, and Child-Pugh for 28-day and 90-day mortality prediction (C-index 0.76/0.73 vs 0.69/0.66 for MELD).

4. NACSELD criteria miss 62.7% of CLIF-C-defined ACLF patients. APASL criteria miss 76.0%.

5. Prognosis should be determined after 3-7 days of full organ support, not at ICU admission.

6. ≥4 organ failures or CLIF-C ACLF score >70 after 3-7 days → consider withdrawal of support (if no transplant option).

## Key statistics (CANONIC study, n=1,343)

- 28-day mortality by organ failure count:
  - No organ failure: 4.5%
  - One organ failure: 14.6%
  - Two organ failures: 32.0%
  - Three or more: 78.6%

- Liver transplantation for ACLF-2/3: 95% vs 23% 28-day survival (transplanted vs not)

## PREDICT study (precipitants, n=420 ACLF patients)

- 273/420 (65%) had at least one identifiable precipitant
- 147/420 (35%) had NO identifiable precipitant
- Single precipitant frequencies (denominator=273):
  - Proven bacterial infection: 41.3%
  - Severe alcohol-related hepatitis: 27.1%
  - Combined infection + alcohol hepatitis: 20.4%
  - GI hemorrhage with shock: 2.2%
  - Toxic encephalopathy: never seen alone

## CLIF-C scores formulas

### CLIF-C ACLF score (for patients WITH ACLF)
```
Score = 10 × (0.33 × OFs + 0.04 × Age + 0.63 × ln(WBC) − 2)
```
- OFs = sum of 6 organ sub-scores (range 6-18)
- Age in years
- WBC in 10⁹/L

### CLIF-C AD score (for patients WITHOUT ACLF)
```
Score = 10 × (0.03 × Age + 0.66 × ln(Cr) + 1.71 × ln(INR) + 0.88 × ln(WBC) − 0.05 × Na + 8)
```
- Cr = serum creatinine mg/dl
- INR = international normalized ratio
- WBC in 10⁹/L
- Na = serum sodium mEq/L

Risk categories: ≤45 low (<2%), 46-59 intermediate (2-30%), ≥60 high (>30%) 3-month mortality.

## Scoring system details (CLIF-C OF)

Full scoring table (replicated for precision):

| Sub-score | Liver (bilirubin mg/dl) | Kidney (creatinine mg/dl) | Brain (HE grade) | Coagulation (INR) | Circulation | Respiration |
|-----------|-------------------------|---------------------------|-------------------|--------------------|-------------|-------------|
| 1 | <6.0 | <1.5 | None | <2.0 | MAP≥70 | PaO₂/FiO₂>300 or SpO₂/FiO₂>357 |
| 2 | ≥6.0, <12.0 | ≥1.5, <2.0 | Grade I-II | ≥2.0, <2.5 | MAP<70 | >200,≤300 or >214,≤357 |
| 3 | ≥12.0 | ≥2.0 or RRT | Grade III-IV | ≥2.5 | Vasopressors | ≤200 or ≤214 or MV |

RRT = renal replacement therapy; MV = mechanical ventilation for respiratory failure.
MAP = mean arterial pressure in mmHg.

## ACLF grading rules (algorithmic)

Let N_fail = count of organs with sub-score 3 (failure).
Let kidney_dysfunction = (kidney sub-score == 2), i.e., Cr 1.5-1.9.
Let brain_dysfunction = (brain sub-score == 2), i.e., HE grade I-II.

```python
if N_fail == 0:
    grade = "no_aclf"
elif N_fail == 1:
    failed_organ = [organ for organ in organs if organ.score == 3][0]
    if failed_organ == "kidney":
        grade = "1a"  # single kidney failure
    elif kidney_dysfunction or brain_dysfunction:
        grade = "1b"  # single non-kidney failure + kidney/brain dysfunction
    else:
        grade = "no_aclf"  # single non-kidney failure WITHOUT dysfunction → NOT ACLF
elif N_fail == 2:
    grade = "2"
elif N_fail == 3:
    grade = "3a"
else:  # N_fail >= 4
    grade = "3b"
```

CRITICAL EDGE CASE: A patient with a single NON-kidney organ failure (e.g., liver failure alone with bilirubin ≥12) but NO kidney dysfunction and NO brain dysfunction does NOT have ACLF. They only qualify for ACLF-1b if they ALSO have kidney dysfunction (Cr 1.5-1.9) or brain dysfunction (HE I-II).
