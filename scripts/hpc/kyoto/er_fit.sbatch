#!/bin/bash
# Kyoto University supercomputer: one array task per day group of a prepared ER run.
# Edit the four #SBATCH lines marked EDIT, then submit from the directory for logs:
#
#   ENV_ROOT=/LARGE0/grXXXXX/$USER/sopran-env \
#   SOPRAN_DATA_ROOT=/LARGE0/grXXXXX/$USER/sopran_data \
#   RUN_VARIANT=bb-default-kyoto sbatch scripts/hpc/kyoto/er_fit.sbatch
#
# Kyoto's Slurm takes resources as --rsc p=PROCS:t=THREADS:c=CORES:m=MEMORY and sets
# OMP_NUM_THREADS from it; the worker pool uses that many processes (each forced to one
# BLAS thread). Programs must be started with srun. Tasks resume unfinished days, so a
# timed-out or cancelled task is simply resubmitted with the same command.
#SBATCH -p gr00000b
#SBATCH -t 12:00:00
#SBATCH --rsc p=1:t=40:c=40:m=80G
#SBATCH -a 0-15
#SBATCH -J er-fit
#SBATCH -o er-fit.%A_%a.out
# EDIT above: -p your group queue; -t time limit; --rsc cores and memory per task
# (about 0.2 GB per worker plus 2 GB); -a 0..(groups-1) from 'prepare --groups'.
set -euo pipefail

: "${ENV_ROOT:?export ENV_ROOT}" "${SOPRAN_DATA_ROOT:?export SOPRAN_DATA_ROOT}" "${RUN_VARIANT:?export RUN_VARIANT}"
# shellcheck disable=SC1091
source "$ENV_ROOT/venv/bin/activate"
WORKERS=${WORKERS:-${OMP_NUM_THREADS:-1}}
echo "task=${SLURM_ARRAY_TASK_ID} workers=${WORKERS} host=$(hostname) start=$(date -u +%FT%TZ)"
srun python -m sopran.experimental.kaguya.er_batch run \
  --run-variant "$RUN_VARIANT" --group "$SLURM_ARRAY_TASK_ID" --workers "$WORKERS"
echo "end=$(date -u +%FT%TZ)"
