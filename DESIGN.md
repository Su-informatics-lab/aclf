# ACLF Phenotyping: Design Document

**System**: AI-powered ACLF identification and grading from clinical notes + structured EHR
**Repo**: `aclf/`
**Date**: July 2026
**PI**: Wanzhu Tu, Archita Desai, Jing Su
**Engineers**: Haining Wang

---

## 1. Overview

This system identifies and grades Acute-on-Chronic Liver Failure (ACLF) in cirrhosis patients using a simplified version of the Agentic Delphi architecture. Unlike Delphi (7-expert multi-round consensus), this is a **single-expert, single-pass** assessment with **hybrid evidence retrieval** (clinical notes + structured EHR).

ACLF has **no ICD code** — it is a clinical syndrome defined by the co-occurrence of specific organ failures (EASL-CLIF Consortium criteria). Current administrative data cannot identify it. This system fills that gap by combining:

1. **LLM-powered note extraction** — for clinical context that only exists in narrative text (hepatic encephalopathy grading, precipitant identification, vasopressor/ventilation context)
2. **Structured EHR queries** — for objective lab values and medication records (bilirubin, creatinine, INR, vasopressors)
3. **Deterministic scoring** — CLIF-C OF algorithm to grade organ failures → ACLF grade

### 1.1 Pipeline at a glance

```
Patient roster (ICC cirrhosis cohort)
    ↓
Per-patient evidence retrieval:
    Tools: search_notes, query_labs, query_medications,
           query_conditions, query_procedures
    ↓
LLM assessment (single hepatologist expert):
    Input:  retrieved evidence + clinical instructions
    Output: ACLFAssessment (structured JSON per CLIF-C OF criteria)
    ↓
Deterministic ACLF scoring:
    CLIF-C OF score → ACLF grade (0/1a/1b/2/3a/3b)
    ↓
Output: per-patient ACLF status + organ failure detail + precipitants
```

### 1.2 Relationship to Agentic Delphi

This is a **simplified fork** of `agentic_delphi/`. What we keep and what we drop:

| Component | Agentic Delphi | ACLF |
|-----------|---------------|------|
| Expert panel | 7 specialists | 1 hepatologist |
| Rounds | R1→R2(debate)→R3 | Single pass |
| Questionnaire | 14 Likert-scored questions | 6 organ systems + precipitants |
| Evidence retrieval | PatientRAG (7 tools) | Same PatientRAG tools (6 internal) |
| Structured EHR | DuckDB OMOP | DuckDB OMOP (same pattern) |
| Note search | Nomic embeddings | Same (or skip if embeddings unavailable) |
| LLM backend | CatChat gpt-oss:120b | Same |
| Schema validation | Pydantic + repair loop | Same |
| Debate/consensus | Router, Moderator, Consensus | **REMOVED** |
| External RAG | PubMed/bioRxiv | **REMOVED** (clinical knowledge baked into prompt) |

### 1.3 Key files to port from `agentic_delphi/`

```
agentic_delphi/delphi/agent.py      → aclf/agent.py      (simplify: remove debate, single expert)
agentic_delphi/delphi/schema.py     → aclf/schema.py      (rewrite: ACLFAssessment replaces ExpertAssessment)
agentic_delphi/delphi/rag/tools.py  → aclf/rag/tools.py   (copy: same tool definitions, adjust descriptions)
agentic_delphi/delphi/rag/ehr.py    → aclf/rag/ehr.py     (copy: DuckDB backend, same OMOP queries)
agentic_delphi/delphi/rag/vectors.py→ aclf/rag/vectors.py  (copy: note embeddings search)
agentic_delphi/delphi/config.py     → aclf/config.py       (simplify: remove topology params)
agentic_delphi/runs/run_delphi.py   → aclf/run_aclf.py     (simplify: single expert, no rounds)
```

**Files NOT needed**: `orchestrator.py`, `router.py`, `moderator.py`, `consensus.py`, `state.py`, `expert.py`

---

## 2. Clinical background: ACLF

### 2.1 What is ACLF?

Acute-on-chronic liver failure (ACLF) is a severe form of acutely decompensated cirrhosis characterized by organ system failure(s) and high short-term mortality (28-day mortality ≥20%, vs ≤5% for decompensated cirrhosis without ACLF). It was formally defined by the EASL-CLIF Consortium in 2013 (CANONIC study, Moreau et al., Gastroenterology 2013).

ACLF is caused by an excessive systemic inflammatory response triggered by precipitants that may be clinically apparent (bacterial infection, severe alcohol-related hepatitis) or not.

**Critical fact: ACLF has no ICD-10 code.** It is invisible in administrative data. This is the core gap our system addresses.

### 2.2 CLIF-C Organ Failure (OF) scoring system

The EASL-CLIF-C OF score evaluates 6 organ systems. Each is scored on a 3-point scale (1=normal, 2=dysfunction, 3=failure):

| Organ | Score 1 (Normal) | Score 2 (Dysfunction) | Score 3 (Failure) |
|-------|------------------|-----------------------|-------------------|
| **Liver** | Bilirubin <6.0 mg/dl | Bilirubin ≥6.0 and <12.0 mg/dl | Bilirubin ≥12.0 mg/dl |
| **Kidney** | Creatinine <1.5 mg/dl | Creatinine ≥1.5 and <2.0 mg/dl | Creatinine ≥2.0 mg/dl OR renal replacement therapy |
| **Brain (HE)** | No HE | HE grade I-II (West-Haven) | HE grade III-IV (West-Haven) |
| **Coagulation** | INR <2.0 | INR ≥2.0 and <2.5 | INR ≥2.5 |
| **Circulation** | MAP ≥70 mmHg | MAP <70 mmHg | Need for vasopressors |
| **Respiration** | PaO₂/FiO₂ >300 OR SpO₂/FiO₂ >357 | PaO₂/FiO₂ ≤300 and >200 OR SpO₂/FiO₂ ≤357 and >214 | PaO₂/FiO₂ ≤200 OR SpO₂/FiO₂ ≤214 OR mechanical ventilation |

### 2.3 ACLF grading

Based on the number and type of organ failures (score=3):

| Grade | Criteria | 28-day mortality |
|-------|----------|-----------------|
| **No ACLF** | No organ failure; OR single non-kidney organ failure with no kidney/brain dysfunction | ~5% |
| **ACLF-1a** | Single kidney failure | ~22% |
| **ACLF-1b** | Single non-kidney organ failure PLUS kidney dysfunction (Cr 1.5-1.9) and/or brain dysfunction (HE I-II) | ~22% |
| **ACLF-2** | Two organ failures | ~32% |
| **ACLF-3a** | Three organ failures | ~73-79% |
| **ACLF-3b** | Four to six organ failures | ~73-79% |

### 2.4 CLIF-C ACLF score (prognostic)

For patients WITH ACLF, a continuous prognostic score:

```
CLIF-C ACLF score = 10 × (0.33 × CLIF-C OFs + 0.04 × Age + 0.63 × ln(WBC) − 2)
```

where CLIF-C OFs = sum of the 6 organ sub-scores (range 6-18), Age in years, WBC = white blood cell count (10⁹/L).

C-index: 0.76 for 28-day mortality, 0.73 for 90-day mortality (vs. MELD 0.69/0.66).

### 2.5 CLIF-C AD score (for patients WITHOUT ACLF)

For patients with acute decompensation but NO ACLF:

```
CLIF-C AD score = 10 × (0.03 × Age + 0.66 × ln(Creatinine) + 1.71 × ln(INR) + 0.88 × ln(WBC) − 0.05 × Sodium + 8)
```

Risk stratification: ≤45 (low, <2% 3-month mortality), 46-59 (intermediate, 2-30%), ≥60 (high, >30%).

### 2.6 Precipitants of ACLF

The PREDICT study (Trebicka et al., J Hepatol 2021) identified the following common precipitants (in order of frequency):

1. **Proven bacterial infection** (41.3% of cases with identified precipitant)
   - SBP, UTI, pneumonia, bacteremia, skin/soft tissue, cholangitis
   - Diagnosis: culture-positive, or neutrophils >250/mm³ in ascites (SBP)

2. **Severe alcohol-related hepatitis** (27.1%)
   - Active alcohol consumption + NIAAA criteria:
     - Bilirubin >3 mg/dl, AST >50, AST/ALT >1.5, both <400
   - OR liver biopsy: macrovesicular steatosis + neutrophil infiltration

3. **Combined infection + alcohol-related hepatitis** (20.4%)

4. **GI hemorrhage with shock** (2.2% as single precipitant)
   - Hematemesis/melena + hypovolemic shock

5. **Drug-induced brain/kidney injury** (never sole precipitant, always combined)
   - Sedatives, nephrotoxic drugs (NSAIDs, aminoglycosides, contrast)

6. **Hepatitis B reactivation** (primarily in Asian populations)

7. **No identifiable precipitant** (35% of ACLF cases)

### 2.7 West-Haven criteria for hepatic encephalopathy

This is the CRITICAL NLP target — HE grading almost never exists in structured data:

| Grade | Clinical features |
|-------|-------------------|
| **Minimal/Covert** | Abnormal psychometric tests only; clinically undetectable |
| **Grade I** | Trivial lack of awareness, shortened attention span, altered sleep rhythm, euphoria/anxiety |
| **Grade II** | Lethargy, apathy, disorientation for time, obvious personality change, inappropriate behavior, asterixis |
| **Grade III** | Somnolence to semi-stupor, responsive to stimuli, confused, gross disorientation, bizarre behavior |
| **Grade IV** | Coma, unresponsive to verbal or noxious stimuli |

**Key terms in notes that indicate HE**: asterixis, flapping tremor, encephalopathy, altered mental status, confusion, somnolence, hepatic coma, lactulose, rifaximin (treatment), disorientation, obtunded, unresponsive, GCS score.

### 2.8 Key lab concepts for OMOP queries

| Organ | OMOP measurement concept | Common LOINC |
|-------|--------------------------|--------------|
| Liver | Bilirubin, total | 1975-2 |
| Kidney | Creatinine, serum | 2160-0 |
| Coagulation | INR | 6301-6 |
| Respiration | PaO₂ | 2703-7 |
| Respiration | FiO₂ | 3150-0 |
| Respiration | SpO₂ | 2708-6 |
| Prognostic | WBC count | 6690-2 |
| Prognostic | Serum sodium | 2951-2 |

### 2.9 Key medication concepts for OMOP queries

| Category | Examples | Relevance |
|----------|----------|-----------|
| Vasopressors | norepinephrine, vasopressin, terlipressin, dopamine, epinephrine, phenylephrine | Circulation failure |
| Mechanical ventilation | (procedure, not drug) | Respiration failure |
| RRT/Dialysis | (procedure) hemodialysis, CRRT, CVVHD | Kidney failure |
| HE treatment | lactulose, rifaximin | Indicates HE present |
| Precipitant drugs | NSAIDs, aminoglycosides, vancomycin, ACEi/ARBs, contrast | Drug-induced AKI |
| Antibiotics | (broad-spectrum empirical) | Indicates infection treatment |
| Corticosteroids | prednisolone, prednisone, methylprednisolone | Alcohol-related hepatitis treatment |

---

## 3. Schema design

### 3.1 ACLFAssessment (main output)

The LLM produces one `ACLFAssessment` per patient. This replaces the Delphi `ExpertAssessment` (14 Likert-scored questions) with organ-by-organ structured extraction.

```python
class OrganAssessment(BaseModel):
    """Assessment of a single organ system per CLIF-C OF criteria."""

    organ: Literal["liver", "kidney", "brain", "coagulation", "circulation", "respiration"]

    # The key clinical value(s) — extracted from notes and/or structured EHR
    peak_value: float | None  # e.g., peak bilirubin, peak creatinine, peak INR
    peak_value_unit: str | None  # e.g., "mg/dl", "ratio"
    peak_value_date: str | None  # ISO date when peak occurred

    # For organs without numeric values (brain, circulation, respiration)
    clinical_finding: str | None  # e.g., "HE grade III", "on norepinephrine", "mechanically ventilated"

    # CLIF-C OF sub-score (1=normal, 2=dysfunction, 3=failure)
    clif_score: int  # 1, 2, or 3

    # Evidence
    evidence_source: Literal["structured_ehr", "clinical_notes", "both", "none"]
    evidence_text: str  # verbatim supporting text from notes or lab description

    reasoning: str  # clinical reasoning for the assigned score
    confidence: Literal["high", "moderate", "low"]


class Precipitant(BaseModel):
    """Identified precipitant of acute decompensation."""

    type: Literal[
        "bacterial_infection",
        "alcohol_related_hepatitis",
        "gi_hemorrhage_with_shock",
        "drug_induced_brain_injury",
        "drug_induced_kidney_injury",
        "hbv_reactivation",
        "hev_infection",
        "other",
        "none_identified",
    ]
    subtype: str | None  # e.g., "SBP", "pneumonia", "UTI" for infection
    evidence_text: str
    confidence: Literal["high", "moderate", "low"]


class ACLFAssessment(BaseModel):
    """Complete ACLF assessment for one patient at one time point."""

    sample_id: str
    assessment_date: str  # ISO date of the acute decompensation episode being assessed

    # Is this patient acutely decompensated?
    has_acute_decompensation: bool
    decompensation_type: list[Literal["ascites", "encephalopathy", "gi_hemorrhage", "jaundice", "other"]]

    # 6 organ assessments
    organs: list[OrganAssessment]  # exactly 6, one per organ system

    # Precipitants
    precipitants: list[Precipitant]

    # Additional prognostic data (for CLIF-C scores)
    age_years: int | None
    wbc_count: float | None  # 10^9/L
    wbc_date: str | None
    serum_sodium: float | None  # mEq/L
    sodium_date: str | None

    # Overall clinical narrative
    clinical_summary: str  # 3-5 sentence summary of the patient's acute episode
    data_quality: Literal["sufficient", "limited", "insufficient"]

    # Temporal note: when did the decompensation episode occur?
    episode_start_date: str | None
    episode_end_date: str | None
```

### 3.2 Deterministic scoring (post-LLM, pure Python)

After the LLM produces `ACLFAssessment`, a Python function computes:

```python
def score_aclf(assessment: ACLFAssessment) -> dict:
    """Deterministic ACLF grading from LLM assessment.

    Returns:
        {
            "clif_of_score": int (6-18),
            "n_organ_failures": int (0-6),
            "n_organ_dysfunctions": int (0-6),
            "failed_organs": list[str],
            "dysfunctional_organs": list[str],
            "aclf_grade": str ("no_aclf" | "1a" | "1b" | "2" | "3a" | "3b"),
            "clif_c_aclf_score": float | None,  # only if ACLF present
            "clif_c_ad_score": float | None,      # only if no ACLF
            "predicted_28d_mortality": str,        # risk category
        }
    ```

This is NOT an LLM call. It is a deterministic algorithm implementing the EASL-CLIF-C grading rules from §2.3.

---

## 4. Evidence retrieval (PatientRAG)

### 4.1 Tool definitions

Same 6 internal tools as Agentic Delphi, with ACLF-specific descriptions:

| Tool | Backend | ACLF-specific usage |
|------|---------|---------------------|
| `search_notes` | Cosine similarity on embeddings | HE grading, precipitant details, vasopressor context, clinical course |
| `query_labs` | DuckDB OMOP `measurement` | Bilirubin, creatinine, INR, PaO₂/FiO₂, WBC, sodium |
| `query_medications` | DuckDB OMOP `drug_exposure` | Vasopressors, lactulose/rifaximin, antibiotics, steroids |
| `query_conditions` | DuckDB OMOP `condition_occurrence` | Cirrhosis codes, infection codes, AKI codes |
| `query_procedures` | DuckDB OMOP `procedure_occurrence` | Dialysis, mechanical ventilation, paracentesis |
| `get_extraction` | JSON file (MedACE output) | Pre-extracted clinical facts (if available; may be absent for ICC cohort) |

### 4.2 Note search fallback

If note embeddings are not pre-computed for the ICC cohort, `search_notes` should fall back to keyword matching (simple TF-IDF or regex over raw notes). The pipeline must work with or without pre-computed embeddings.

### 4.3 Assessment time window

ACLF is an acute event. For each patient, the LLM should focus on **hospitalization episodes** where acute decompensation occurred. The time window for evidence retrieval should be centered on:

- The **index hospitalization** for acute decompensation, OR
- If multiple hospitalizations, the **most severe episode** (highest number of organ failures)

The time window for each episode: **±7 days** from the admission date (for capturing the acute phase) plus **±30 days** for background context (comorbidities, medications, precipitant onset).

---

## 5. LLM agent architecture

### 5.1 Single expert: hepatologist

Unlike Delphi's 7-specialist panel, ACLF uses a single expert. The rationale:
- ACLF is a hepatology-specific syndrome with well-defined diagnostic criteria
- The CLIF-C OF criteria are algorithmic (not judgment-based like irAKI differential)
- The LLM's job is primarily **information extraction**, not clinical judgment
- Multi-agent debate adds no value when the scoring is deterministic

### 5.2 Two-phase architecture (same as Delphi)

**Phase 1 — GATHER**: ReAct tool-calling loop.
- LLM calls PatientRAG tools to retrieve evidence
- Capped at `max_tool_rounds` (default 7) rounds
- Tools: search_notes, query_labs, query_medications, query_conditions, query_procedures, get_extraction

**Phase 2 — ASSESS**: Structured output generation.
- Gathered evidence formatted and appended to prompt
- LLM produces ACLFAssessment (Pydantic-validated JSON)
- Re-ask repair loop (max 3 retries) for validation errors

### 5.3 System prompt structure

```
[SYSTEM]
You are a senior hepatologist performing ACLF assessment on a cirrhosis patient.
Your task is to evaluate 6 organ systems per the EASL-CLIF Consortium criteria
and identify precipitants of acute decompensation.

[CLINICAL REFERENCE — ACLF CRITERIA]
(Full CLIF-C OF scoring table from §2.2)
(ACLF grading rules from §2.3)
(West-Haven HE criteria from §2.7)
(Precipitant definitions from §2.6)

[PATIENT EVIDENCE]
(Retrieved evidence from Phase 1)

[TASK]
Assess each of the 6 organ systems. For each:
1. Identify the worst (peak) value during the acute episode
2. Assign the CLIF-C OF sub-score (1/2/3)
3. Cite the evidence source (structured EHR, notes, or both)

Then identify any precipitants of acute decompensation.

[OUTPUT FORMAT]
(Auto-generated from ACLFAssessment Pydantic schema)
```

### 5.4 Baked-in clinical knowledge (no external RAG)

Unlike Delphi (which searches PubMed during assessment), ACLF criteria are well-defined and static. All clinical knowledge is **embedded directly in the prompt** via the `docs/ACLF_CLINICAL_REFERENCE.md` file. This eliminates:
- External API dependencies
- PII fence complexity
- Latency from literature search
- Risk of irrelevant search results

---

## 6. Batch runner

### 6.1 run_aclf.py

Simplified from `run_delphi.py`. Key differences:

- No orchestrator (no rounds, no debate)
- Single expert instantiation
- Per-patient: `gather → assess → score → save`
- `--skip-existing` on by default
- Async: 4-8 concurrent patients (CatChat can handle it)

```python
async def process_patient(pid, rag, agent, output_dir):
    """Process a single patient: gather evidence → assess → score."""
    assessment = await agent.assess(rag=rag, sample_id=str(pid))
    scores = score_aclf(assessment)

    output = {
        "assessment": assessment.model_dump(),
        "scores": scores,
    }
    save_json(output_dir / f"{pid}.json", output)
```

### 6.2 Output structure

```
results/aclf/{sample_id}.json
├── assessment:
│   ├── sample_id
│   ├── has_acute_decompensation
│   ├── organs: [{organ, peak_value, clif_score, evidence_text, ...}, ×6]
│   ├── precipitants: [{type, subtype, evidence_text, ...}]
│   ├── age_years, wbc_count, serum_sodium
│   └── clinical_summary
└── scores:
    ├── clif_of_score (6-18)
    ├── n_organ_failures
    ├── failed_organs
    ├── aclf_grade ("no_aclf" | "1a" | "1b" | "2" | "3a" | "3b")
    ├── clif_c_aclf_score (if ACLF present)
    └── clif_c_ad_score (if no ACLF)
```

---

## 7. Data requirements

### 7.1 ICC cohort (Archita Desai's cirrhosis registry)

- **Source**: Indiana Network for Patient Care (INPC), OMOP CDM
- **Cohort**: ~10,227 patients with compensated cirrhosis; initial test on ~500
- **Location**: Indiana University Slate/Quartz HPC
- **Key tables needed**:
  - `note` or `note_nlp` — clinical notes (progress notes, discharge summaries, admission notes)
  - `measurement` — labs (bilirubin, creatinine, INR, PaO₂, FiO₂, SpO₂, WBC, sodium)
  - `drug_exposure` — medications (vasopressors, lactulose, rifaximin, antibiotics)
  - `condition_occurrence` — diagnoses (cirrhosis, infection, AKI)
  - `procedure_occurrence` — procedures (dialysis, mechanical ventilation)
  - `visit_occurrence` — encounter timeline (to identify hospitalizations)

### 7.2 Pre-flight data check

Before running the pipeline, verify:

1. **Notes exist and are substantial**: `SELECT COUNT(*), AVG(LENGTH(note_text)) FROM note WHERE person_id IN (cohort)`
2. **Labs are populated**: Check non-null rates for bilirubin, creatinine, INR
3. **Hospitalizations identifiable**: `visit_occurrence` has inpatient visits
4. **Vasopressor records exist**: Check drug_exposure for norepinephrine, vasopressin, etc.

If notes are sparse or labs are missing, the pipeline will still run but produce low-confidence results with `data_quality: "insufficient"`.

---

## 8. Compute environment

Same as Agentic Delphi (Tempest HPC + CatChat). See agentic_delphi DESIGN.md §15 for details.

- **LLM backend**: CatChat `gpt-oss:120b` (from Tempest compute nodes only)
- **SLURM**: `unsafe` partition, 7-day time limit, CPU-only
- **Python**: 3.12 venv, same dependencies as agentic_delphi
- **DuckDB**: for structured EHR queries
- **Critical**: `module purge` before all module loads; `PYTHONNOUSERSITE=1` in sbatch

---

## 9. Implementation plan for Codex

### Phase 1: Schema + scoring (no LLM, pure Python)

1. Create `schema.py` with `OrganAssessment`, `Precipitant`, `ACLFAssessment`
2. Create `scoring.py` with `score_aclf()` implementing the deterministic CLIF-C OF → ACLF grade algorithm
3. Write unit tests for scoring edge cases (see §2.3 for grading rules)

### Phase 2: Agent + tools

4. Port `agentic_delphi/delphi/rag/tools.py` → `rag/tools.py` (update tool descriptions for ACLF context)
5. Port `agentic_delphi/delphi/rag/ehr.py` → `rag/ehr.py` (DuckDB OMOP queries — same code)
6. Port `agentic_delphi/delphi/rag/vectors.py` → `rag/vectors.py` (note embeddings — same code)
7. Create `agent.py`: simplified `ACLFAgent` with 2-phase gather→assess (port from `DelphiExpert`, remove debate)
8. Create `instructions.py`: system prompt with full ACLF clinical reference embedded

### Phase 3: Runner + batch

9. Create `run_aclf.py`: batch runner with `--skip-existing`, async concurrency
10. Create `run_aclf.sbatch`: SLURM job script
11. Create `config.py`: simplified config (no topology params)

### Phase 4: Validation

12. Create `validate.py`: QC script to check output completeness, score distributions
13. Manual review of first 10-20 patients against clinical notes

---

## 10. Key differences from Agentic Delphi to watch for

1. **No `expert_id` pool validation** — single expert, no need for pool checks in schema
2. **No debate schemas** — remove `DebateTurn`, `PrebriefItem`, `AdoptionDecision`
3. **No `build_guided_schema_assessment` with prefixItems** — ACLF schema doesn't need question-order pinning; use simpler `json_schema` mode
4. **No MedACE extraction dependency** — ICC cohort may not have MedACE extractions; `get_extraction` tool should gracefully return empty if no extraction file exists
5. **Time window is episode-based**, not ICI-index-date-based — need hospitalization episode detection
6. **Multiple episodes per patient possible** — a patient may have multiple acute decompensation episodes; assess the worst one (or all, configurable)

---

## 11. Reference files

- `docs/ACLF_CLINICAL_REFERENCE.md` — full EASL-CLIF-C criteria for embedding in LLM prompt
- `docs/EASL_ACLF_CPG_2023.md` — extracted key sections from EASL Clinical Practice Guidelines (J Hepatol 2023;79:461-491)
- `DESIGN.md` — this file
