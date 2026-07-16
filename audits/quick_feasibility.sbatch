#!/bin/bash
#SBATCH --job-name=aclf-feasibility
#SBATCH --account=r01834
#SBATCH --partition=general
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=32G
#SBATCH --output=logs/aclf_feasibility_%j.out
#SBATCH --error=logs/aclf_feasibility_%j.err

set -euo pipefail
cd /N/project/depot/hw56/aclf
module load python/3.12.4
source .venv/bin/activate
mkdir -p logs

python audits/quick_feasibility.py \
  --mapping /N/project/depot/hw56/aud/medace_aud/resources/mapped_report_ids.csv \
  --note-dates /N/project/depot/hw56/aud/medace_aud/resources/note_dates.csv \
  --notes-dir /N/project/depot/hw56/aud/cirrhosis_regv20/redacted_txt \
  --notes-dir /N/project/depot/hw56/aud/cirrhosis_regv20/redacted_pdf-text \
  --ehr-db results/ehr.duckdb \
  --raw-dir /N/project/depot/hw56/aud/cirrhosis_regv20/data_tables_v1/parquet \
  --output-dir results/aclf_v2
