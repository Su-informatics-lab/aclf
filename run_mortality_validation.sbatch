#!/bin/bash
#SBATCH --job-name=aclf_mortality
#SBATCH --account=r01834
#SBATCH --partition=general
#SBATCH --time=01:00:00
#SBATCH --mem=8G
#SBATCH --cpus-per-task=2
#SBATCH --output=logs/aclf_mortality_%j.out
#SBATCH --error=logs/aclf_mortality_%j.err
#SBATCH --mail-type=END,FAIL

set -euo pipefail
module load python/3.12.4
module load r/4.4.1 r-tools/4.4.1
cd /N/project/depot/hw56/aclf
source .venv/bin/activate
export PYTHONNOUSERSITE=1
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
mkdir -p logs results/mortality_internal results/mortality_share

# Fail rather than downloading a package during the analysis job.
R_LIBS_USER="${PWD}/.r-lib" Rscript -e 'stopifnot(requireNamespace("cmprsk", quietly=TRUE))'

python -m analysis.build_validation_cohort \
    --assessments results/aclf_v2 \
    --ehr-db results/ehr.duckdb \
    --death-parquet /N/project/depot/hw56/aud/cirrhosis_regv20/data_tables_v1/parquet/death.parquet \
    --admin-censor-date 2023-07-10 \
    --output-dir results/mortality_internal

R_LIBS_USER="${PWD}/.r-lib" Rscript analysis/mortality_validation.R \
    results/mortality_internal/patient_level.csv \
    results/mortality_share

