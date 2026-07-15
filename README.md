# ACLF phenotyping

Single-hepatologist, two-phase ACLF phenotyping for the Indiana Cirrhosis
Cohort. The LLM gathers patient-scoped evidence and extracts a Pydantic-validated
assessment; Python assigns the final EASL-CLIF ACLF grade and prognostic scores.

The implementation is a deliberately small adaptation of Agentic Delphi:

- retained: separate gather/assess calls, native tools, stable seeds, strict
  structured output, and validation repair;
- removed: expert panels, debate, moderation, consensus, and external RAG;
- added: report/GPID/OMOP provenance, raw-note keyword fallback, observed
  inpatient episodes, deterministic scoring, and output QC. Episode dates are
  enforced against OMOP visits, transplant/postoperative findings cannot be
  merged into native-liver ACLF, and incomplete organ evidence yields explicit
  ACLF-presence and grade bounds instead of assumed normal scores.

Each schema-v1.1 result also records a compact retrieval trace and requires
traceable evidence for any positive acute-decompensation assertion. Core labs
are prefetched deterministically for the leading episode candidates, and every
note or OMOP source ID in the assessment must occur in that run's retrieval
trace.

See `PROVENANCE.md` for the verified identifier and dataset contracts.

## Quartz setup

```bash
cd /N/project/depot/hw56/aclf
module load python/3.12.4
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Build the roster-filtered read-only EHR database:

```bash
sbatch prepare_ehr.sbatch
```

Run one smoke patient:

```bash
export CATCHAT_API_KEY=...
EXTRA_ARGS="--pid OMOP_PERSON_ID --no-skip-existing" sbatch run_aclf.sbatch
```

Validate outputs:

```bash
python validate.py --output-dir results/aclf
```

Local tests:

```bash
python -m pytest tests -v
python -m compileall -q .
```
