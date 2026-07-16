#!/bin/bash
#SBATCH --job-name=aclf_rdeps
#SBATCH --account=r01834
#SBATCH --partition=general
#SBATCH --time=00:30:00
#SBATCH --mem=2G
#SBATCH --cpus-per-task=1
#SBATCH --output=logs/aclf_rdeps_%j.out
#SBATCH --error=logs/aclf_rdeps_%j.err

set -euo pipefail
module load r/4.4.1 r-tools/4.4.1
cd /N/project/depot/hw56/aclf
mkdir -p logs .r-lib
Rscript analysis/setup_r_deps.R

