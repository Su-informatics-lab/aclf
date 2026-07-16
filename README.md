# Evidence-grounded ACLF phenotyping

This research pipeline identifies acute-on-chronic liver failure (ACLF) from
clinical notes and structured electronic health record data. It applies the
EASL-CLIF organ-failure criteria to one hospitalization at a time and produces
an auditable, structured assessment for each patient.

No familiarity with Agentic Delphi or other agent frameworks is needed to
understand or use this repository.

> **Research use only.** This is a phenotyping prototype, not a clinical
> decision-support system. Its outputs require validation against clinician
> chart review before use in research analyses and must not guide patient care.

## Why this project exists

ACLF is a clinical syndrome rather than a single reliable diagnosis code. Its
identification requires evidence about acute decompensation and six organ
systems:

1. liver;
2. kidney;
3. brain (hepatic encephalopathy);
4. coagulation;
5. circulation; and
6. respiration.

The necessary evidence is scattered across laboratory results, diagnoses,
medications, procedures, and narrative notes. This pipeline brings those data
together, asks a language model to extract the clinical findings, and then uses
ordinary Python—not the language model—to calculate the final ACLF status and
grade.

## What the pipeline does

For each patient, the pipeline:

1. links redacted notes to the persistent OMOP person identifier;
2. orders inpatient episodes chronologically and selects the first eligible
   non-elective acute-decompensation admission;
3. retrieves traceable evidence tied to that exact visit;
4. determines whether new or worsening ascites, hepatic encephalopathy,
   gastrointestinal bleeding, or infection required admission;
5. assesses all six EASL-CLIF organ systems;
6. identifies supported precipitants, such as bacterial infection;
7. validates every cited note and OMOP record ID against the collected source
   evidence; and
8. accepts baseline laboratory inputs only from admission to less than 24
   hours after admission; and
9. applies deterministic Python scoring to produce ACLF presence, grade,
   CLIF-C ACLF, CLIF-C AD, MELD, study-era MELD-Na, and Child-Pugh scores when
   every required input is available.

The language model is used for evidence synthesis and structured extraction.
It does **not** get to invent missing values or directly determine the final
grade.

## Guardrails against overcalling ACLF

The implementation intentionally favors an explicit “unknown” over an
unsupported normal or abnormal result.

- Evidence from different hospitalizations cannot be combined.
- A future severe episode cannot cause an earlier, milder eligible admission
  to be skipped.
- A laboratory result at or after 24 hours is not a baseline value.
- Stable chronic ascites or encephalopathy is not labeled acute decompensation.
- Planned transplant admissions and postoperative findings are not mixed into
  native-liver ACLF.
- GI hemorrhage requires gastrointestinal bleeding; an abdominal-wall or
  paracentesis-site hematoma does not qualify.
- Undated notes cannot establish that a finding occurred in the acute window.
- Every cited note report ID or OMOP record ID must have been retrieved in that
  run.
- Missing HE grade, MAP, FiO2, or other required evidence remains missing.
- If ACLF is definite but missing organs prevent an exact grade, the output
  reports a defensible grade range rather than guessing.

## Initial phenotype smoke test

The pipeline was tested on Quartz with CatChat `gpt-oss:120b` using two
deliberately contrasting cases.

| Test case | Result | Interpretation |
|---|---|---|
| High-severity acute admission | ACLF present; three proven failures; grade bounded 3a–3b | Bilirubin 25.5 mg/dL, creatinine 4.26 mg/dL, and INR 3.85 established liver, kidney, and coagulation failure. The exact grade remained bounded because HE grade, MAP, and FiO2 were unavailable. |
| Planned liver-transplant admission | No qualifying acute decompensation; no ACLF | The discharge summary documented no acute change. The pipeline did not convert peri-transplant abnormalities into native-liver ACLF. |

These two outputs established that the earlier phenotype code could preserve
missing data and distinguish an acute episode from a planned transplant. They
are engineering smoke tests, not mortality-validation results. The current
study-aligned version requires a new 10–20 patient schema smoke test before the
locked mortality analysis.

## Mortality validation design

The repository now includes a separate, outcome-blinded validation workflow
aligned to the clinical questions behind three published figures:

- Figure 6 analogue: among patients with ACLF at the index admission, compare
  admission CLIF-C ACLF, MELD, MELD-Na, and Child-Pugh for 28-day mortality.
- Figure 5 analogue: among acute-decompensation admissions without ACLF,
  compare CLIF-C AD and the same conventional scores for 90-day mortality.
- Figure 1B analogue: describe 360-day mortality for SDC, UDC, pre-ACLF, and
  baseline ACLF grades 1–3, with a separate day-90 landmark analysis.

The language model never receives mortality or transplant outcomes. A stable
70/30 patient split is created without outcome information. Only after all
phenotypes are frozen does a separate program join EHR-recorded death and liver
transplant dates. Liver transplant is treated as a competing event; the
audience-facing bundle contains only aggregate figures and suppressed tables.

This is an IU single-center, retrospective internal validation using the OMOP
status “EHR record patient status Deceased.” Out-of-system deaths may be
missed. The results therefore cannot be described as a direct replication of
CANONIC or PREDICT, or as complete mortality ascertainment.

## What one output contains

Each patient JSON includes:

- the selected hospitalization and assessment date;
- whether acute decompensation was documented and the supporting records;
- one assessment for each of the six organ systems;
- peak values, dates, units, note excerpts, and source record IDs;
- the exact index visit, admission/discharge datetimes, and baseline 24-hour
  window;
- explicit yes/no/unknown eligibility criteria;
- supported precipitant(s) and confidence;
- data-quality and missing-evidence fields;
- deterministic ACLF presence and exact or bounded grade;
- CLIF-C ACLF or CLIF-C AD score when all required inputs are available; and
- traceable source records for audit and reproducibility.

## What is shared with clinical reviewers

Clinical reviewers receive this README and aggregate validation figures and
tables. Patient identifiers, model prompts, internal instructions, retrieval
traces, state dumps, and raw patient JSON are not part of the shareable bundle.
Cells smaller than five are suppressed.

## Data and provenance

The current cohort contains 499 persistent OMOP v1 person IDs. Clinical-note
report IDs and time-varying patient identifiers are retained as provenance but
are not used to deduplicate patients. See [`PROVENANCE.md`](PROVENANCE.md) for
the verified identifier chain, source paths, row counts, and episode-selection
contract.

## Repository guide

| File | Purpose |
|---|---|
| `docs/ACLF_CLINICAL_REFERENCE.md` | Clinical criteria embedded in the production prompt |
| `schema.py` | Strict structured assessment schema |
| `scoring.py` | Deterministic ACLF grading and prognostic formulas |
| `rag/` | Patient-scoped note and structured-EHR retrieval |
| `agent.py` | Evidence-gathering and assessment workflow |
| `run_aclf.py` | Batch runner and atomic per-patient output |
| `validate.py` | Output, provenance, and deterministic-rescoring QC |
| `analysis/build_validation_cohort.py` | Outcome join, trajectories, censoring, and auditable cohort tables |
| `analysis/mortality_validation.R` | ROC, cumulative-incidence, Gray-test, and sensitivity outputs |
| `prepare_ehr.sbatch` | Quartz job to build the roster-filtered EHR database |
| `run_aclf.sbatch` | Quartz job to run CatChat phenotyping |

## Running on Quartz

Set up the environment:

```bash
cd /N/project/depot/hw56/aclf
module load python/3.12.4
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Build the roster-filtered EHR database:

```bash
sbatch prepare_ehr.sbatch
```

Run one patient first:

```bash
export CATCHAT_API_KEY=...
EXTRA_ARGS="--pid OMOP_PERSON_ID --no-skip-existing" sbatch run_aclf.sbatch
```

Validate the outputs:

```bash
python validate.py --output-dir results/aclf_v2
```

Install the one project-local R dependency once, then run mortality analysis:

```bash
sbatch setup_mortality_r.sbatch
sbatch run_mortality_validation.sbatch
```

Run the local test suite:

```bash
python -m pytest -q -p no:cacheprovider
python -m ruff check --no-cache .
```

## Required sequence before interpreting results

Run a 10–20 patient outcome-blinded schema smoke test, review episode and
baseline-window evidence on the development split, freeze the code and schema,
and only then run the locked test analysis once. A ROC with fewer than 10 deaths
or 10 non-deaths is reported as descriptive and is not called a successful
validation.
