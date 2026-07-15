#!/bin/bash
#SBATCH --job-name=aclf
#SBATCH --account=r01834
#SBATCH --partition=general
#SBATCH --time=4-00:00:00
#SBATCH --mem=16G
#SBATCH --cpus-per-task=4
#SBATCH --output=logs/aclf_%j.out
#SBATCH --error=logs/aclf_%j.err
#SBATCH --mail-type=END,FAIL

set -euo pipefail

# Quartz's default module stack supplies sqlite/gdbm/openblas prerequisites;
# `module purge` makes python/3.12.4 unloadable here.
module load python/3.12.4

cd /N/project/depot/hw56/aclf
source .venv/bin/activate
export PYTHONNOUSERSITE=1
export PYTHONUNBUFFERED=1
: "${CATCHAT_API_KEY:?Set CATCHAT_API_KEY before submitting}"

mkdir -p logs results/aclf

MODEL="${MODEL:-gpt-oss:120b}"
CONCURRENCY="${CONCURRENCY:-4}"
EXTRA_ARGS="${EXTRA_ARGS:-}"

python run_aclf.py \
    --cohort /N/project/depot/hw56/aud/medace_aud/resources/patient_roster.csv \
    --mapping /N/project/depot/hw56/aud/medace_aud/resources/mapped_report_ids.csv \
    --notes-dir \
        /N/project/depot/hw56/aud/cirrhosis_regv20/redacted_txt \
        /N/project/depot/hw56/aud/cirrhosis_regv20/redacted_pdf-text \
    --note-dates /N/project/depot/hw56/aud/medace_aud/resources/note_dates.csv \
    --ehr-db results/ehr.duckdb \
    --output-dir results/aclf \
    --api-base https://catchat-api.msu.montana.edu/v1 \
    --model "${MODEL}" \
    --concurrency "${CONCURRENCY}" \
    --skip-existing \
    ${EXTRA_ARGS}
