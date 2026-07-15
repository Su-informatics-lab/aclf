# Codex Task: Build ACLF Phenotyping Pipeline

## Context

You are building a simplified fork of `agentic_delphi/` for ACLF (acute-on-chronic
liver failure) identification in cirrhosis patients. Read `DESIGN.md` first for
the full architecture. Read `docs/ACLF_CLINICAL_REFERENCE.md` for the clinical
criteria that must be embedded in the LLM prompt.

The reference codebase is at `/Users/haining/Desktop/github/agentic_delphi/`.
Key files to port (read these before writing any code):

- `delphi/agent.py` — the 2-phase gather→assess architecture (port this, remove debate)
- `delphi/schema.py` — Pydantic schemas (rewrite for ACLF)
- `delphi/rag/tools.py` — tool definitions (copy, update descriptions)
- `delphi/rag/ehr.py` — DuckDB OMOP queries (copy as-is)
- `delphi/rag/vectors.py` — note embedding search (copy as-is)
- `delphi/instructions.py` — prompt templates (rewrite for ACLF)
- `delphi/config.py` — configuration (simplify, remove topology params)
- `runs/run_delphi.py` — batch runner (simplify, single expert)

## What to build (in order)

### 1. `schema.py`

Pydantic models for ACLF assessment. Three models:

- `OrganAssessment` — per-organ-system extraction (see DESIGN.md §3.1)
- `Precipitant` — identified precipitant
- `ACLFAssessment` — complete patient assessment (contains 6 OrganAssessments + precipitants + metadata)

Include the `build_format_instructions()` helper from `medace_aud/schema_aud.py` pattern
(auto-generate prompt text from Pydantic field descriptions). This is the schema-as-prompt
pattern that eliminates prompt-schema drift.

Validation rules:
- `organs` list must have exactly 6 items, one per organ system
- `clif_score` must be 1, 2, or 3
- `peak_value` required for liver/kidney/coagulation; optional for brain/circulation/respiration
- `sample_id` must not be empty

### 2. `scoring.py`

Pure Python, no LLM. Deterministic CLIF-C OF scoring:

- `score_aclf(assessment: ACLFAssessment) -> dict` — implements the grading algorithm from DESIGN.md §2.3
- `compute_clif_c_aclf_score(of_score, age, wbc) -> float` — the prognostic score formula
- `compute_clif_c_ad_score(age, cr, inr, wbc, na) -> float` — for non-ACLF patients

Write thorough unit tests in `tests/test_scoring.py` covering:
- No ACLF (0 failures)
- Edge case: single liver failure without kidney/brain dysfunction → no ACLF
- ACLF-1a (single kidney failure)
- ACLF-1b (single non-kidney failure + kidney dysfunction)
- ACLF-2 (two failures)
- ACLF-3a (three failures)
- ACLF-3b (four+ failures)

### 3. `rag/` directory

Port from `agentic_delphi/delphi/rag/`:

- `rag/__init__.py` — exports
- `rag/tools.py` — tool definitions (update descriptions for ACLF context, remove `search_literature`)
- `rag/ehr.py` — DuckDB OMOP query backend (copy from agentic_delphi, same logic)
- `rag/vectors.py` — note embedding search (copy from agentic_delphi)
- `rag/patient_rag.py` — PatientRAG class that binds tools to a patient

Key change: remove `search_literature` tool (no external RAG needed). Keep all 6 internal tools.

Update tool descriptions to mention ACLF-relevant queries:
- `query_labs`: mention bilirubin, creatinine, INR, PaO2, FiO2, SpO2, WBC, sodium, ammonia
- `query_medications`: mention vasopressors (norepinephrine, vasopressin, terlipressin), lactulose, rifaximin, antibiotics
- `query_procedures`: mention dialysis, CRRT, mechanical ventilation, paracentesis, liver biopsy

### 4. `instructions.py`

System prompt construction. Must embed:

1. Expert persona: senior hepatologist specializing in ACLF assessment
2. Full CLIF-C OF scoring criteria (from `docs/ACLF_CLINICAL_REFERENCE.md` §2)
3. ACLF grading rules (§3)
4. West-Haven HE criteria with key note indicators (§2, detailed)
5. Precipitant definitions (§4)
6. Assessment instructions (§5)
7. Common pitfalls (§6)

Use `build_format_instructions()` from schema.py to auto-generate the output format section.

Two prompt templates:
- `GATHER_SYSTEM` — for Phase 1 (tool-calling to retrieve evidence)
- `ASSESS_SYSTEM` — for Phase 2 (structured output generation)

### 5. `agent.py`

Simplified from `agentic_delphi/delphi/agent.py`. Class `ACLFAgent`:

- `__init__(client, model, config)` — no expert_spec needed (single expert)
- `async _gather_evidence(rag, max_rounds, seed)` — same tool-calling loop as DelphiExpert
- `async assess(rag, sample_id) -> ACLFAssessment` — gather→assess 2-phase
- `async _validated_call(messages, response_model, json_schema, max_retries, seed) -> BaseModel` — same repair loop

Remove: debate(), _build_debate_section(), _truncate_transcript(), all R2/R3 logic.
Keep: _stable_seed(), _format_evidence_context(), _validated_call().

### 6. `config.py`

Simplified config:

```python
@dataclass
class ACLFConfig:
    max_tool_rounds: int = 7
    max_retries: int = 3
    temperature: float = 0.3
    top_p: float = 0.9
    reasoning_effort: str = "medium"
    gather_max_tokens: int = 4096
    assess_max_tokens: int = 16384
    concurrency: int = 4  # parallel patients
```

### 7. `run_aclf.py`

Batch runner. Simplified from `runs/run_delphi.py`:

```
Usage: python run_aclf.py \
    --cohort results/cohort/patient_roster.csv \
    --ehr-db results/ehr.duckdb \
    --vectors-dir results/vectors/ \
    --output-dir results/aclf/ \
    --model gpt-oss:120b \
    --api-base https://catchat-api.msu.montana.edu/v1 \
    [--skip-existing] \
    [--limit N] \
    [--concurrency 4]
```

Per-patient flow:
1. Create PatientRAG(pid)
2. agent.assess(rag, sample_id)
3. score_aclf(assessment)
4. Save combined JSON to output_dir/{pid}.json

### 8. `run_aclf.sbatch`

SLURM job script for Tempest HPC:

```bash
#!/bin/bash
#SBATCH --job-name=aclf
#SBATCH --partition=unsafe
#SBATCH --time=7-00:00:00
#SBATCH --mem=16G
#SBATCH --cpus-per-task=4
#SBATCH --output=logs/aclf_%j.out
#SBATCH --error=logs/aclf_%j.err
#SBATCH --account=group-jasonclark
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=haining.wang@montana.edu

module purge
module load OpenSSL/3
module load Python/3.12.3-GCCcore-13.3.0

export PYTHONNOUSERSITE=1
source ~/agentic_delphi/.venv/bin/activate  # share venv with agentic_delphi

python run_aclf.py \
    --cohort results/cohort/patient_roster.csv \
    --ehr-db results/ehr.duckdb \
    --output-dir results/aclf/ \
    --model gpt-oss:120b \
    --api-base https://catchat-api.msu.montana.edu/v1 \
    --skip-existing \
    --concurrency 4
```

## Coding standards

- Python 3.12, type hints everywhere
- Pydantic v2 for all schemas
- `async`/`await` for all LLM calls (AsyncOpenAI client)
- Logging via `logging.getLogger(__name__)`
- `--skip-existing` on by default for all batch operations
- No notebooks — standalone .py scripts only
- `ast.parse()` check before writing any Python to user filesystem
- Keep imports minimal; don't add dependencies beyond what agentic_delphi already uses

## Testing

- `tests/test_schema.py` — schema validation (valid/invalid ACLFAssessments)
- `tests/test_scoring.py` — deterministic ACLF grading (all grade paths)
- `tests/test_agent.py` — mock LLM calls, verify 2-phase architecture

Run with: `python -m pytest tests/ -v`
