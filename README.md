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
2. ranks candidate inpatient episodes using bilirubin, creatinine, and INR;
3. retrieves traceable evidence for the leading episodes;
4. determines whether new or worsening acute decompensation occurred;
5. assesses all six EASL-CLIF organ systems;
6. identifies supported precipitants, such as bacterial infection;
7. validates every cited note and OMOP record ID against the collected source
   evidence; and
8. applies deterministic Python scoring to produce ACLF presence, grade, and
   prognostic scores when the required inputs are available.

The language model is used for evidence synthesis and structured extraction.
It does **not** get to invent missing values or directly determine the final
grade.

## Guardrails against overcalling ACLF

The implementation intentionally favors an explicit “unknown” over an
unsupported normal or abnormal result.

- Evidence from different hospitalizations cannot be combined.
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

## Smoke-test result

The pipeline was tested on Quartz with CatChat `gpt-oss:120b` using two
deliberately contrasting cases.

| Test case | Result | Interpretation |
|---|---|---|
| High-severity acute admission | ACLF present; three proven failures; grade bounded 3a–3b | Bilirubin 25.5 mg/dL, creatinine 4.26 mg/dL, and INR 3.85 established liver, kidney, and coagulation failure. The exact grade remained bounded because HE grade, MAP, and FiO2 were unavailable. |
| Planned liver-transplant admission | No qualifying acute decompensation; no ACLF | The discharge summary documented no acute change. The pipeline did not convert peri-transplant abnormalities into native-liver ACLF. |

Both outputs passed schema, temporal, deterministic-scoring, and source-citation
validation. The remaining uncertainty reflects missing source data rather than
values filled in by the model.

## What one output contains

Each patient JSON includes:

- the selected hospitalization and assessment date;
- whether acute decompensation was documented and the supporting records;
- one assessment for each of the six organ systems;
- peak values, dates, units, note excerpts, and source record IDs;
- supported precipitant(s) and confidence;
- data-quality and missing-evidence fields;
- deterministic ACLF presence and exact or bounded grade;
- CLIF-C ACLF or CLIF-C AD score when all required inputs are available; and
- traceable source records for audit and reproducibility.

## Clinical review task

The model is asked to review one patient with cirrhosis as a hepatology
specialist: select one hospitalization with new or worsening acute
decompensation, assess the six EASL-CLIF organ systems, identify supported
precipitants, and cite the underlying clinical records. When required evidence
is unavailable, the model must report the organ as indeterminate rather than
assume a normal value. Deterministic Python code then assigns the final ACLF
status and grade.

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
python validate.py --output-dir results/aclf
```

Run the local test suite:

```bash
python -m pytest -q -p no:cacheprovider
python -m ruff check --no-cache .
```

## Current interpretation

The smoke tests show that the pipeline can distinguish a genuine high-severity
acute episode from a planned transplant admission while preserving missing
data and evidence provenance. The appropriate next step is a small blinded
chart-review pilot before running and interpreting the complete cohort.
