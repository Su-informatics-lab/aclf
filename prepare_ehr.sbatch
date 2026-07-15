#!/bin/bash
#SBATCH --job-name=aclf_ehr
#SBATCH --account=r01834
#SBATCH --partition=general
#SBATCH --time=02:00:00
#SBATCH --mem=24G
#SBATCH --cpus-per-task=4
#SBATCH --output=logs/aclf_ehr_%j.out
#SBATCH --error=logs/aclf_ehr_%j.err

set -euo pipefail
module purge
module load python/3.12.4
cd /N/project/depot/hw56/aclf
source .venv/bin/activate
export PYTHONNOUSERSITE=1
mkdir -p logs results

python -m rag.build_ehr_db \
    --data-dir /N/project/depot/hw56/aud/cirrhosis_regv20/data_tables_v1/parquet \
    --roster /N/project/depot/hw56/aud/medace_aud/resources/patient_roster.csv \
    --output results/ehr.duckdb
