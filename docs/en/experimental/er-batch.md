# Full-Period ER Batch (Day Shards, Slurm)

`sopran.experimental.kaguya.er_batch` runs finite-bin fits and Rm profiles over saved
paired distributions for the whole mission. The same commands run on a workstation
and as Slurm array jobs on the Kyoto University supercomputer. Inputs and outputs are
Store datasets split into daily Parquet shards, so `rsync` moves them as they are.

| dataset | layer | variant | content |
|---|---|---|---|
| `kaguya.er.paired_distributions` | `features` | input build (e.g. `halekas-mission-20260912`) | folded counts, exposures and record per window; one shard per day |
| `kaguya.er.finite_bin_fits` | `models` | run name (e.g. `bb-default-kyoto`) | fit, profile and candidate per window; one shard per day |

Use `python -m sopran.experimental.kaguya.er_batch [--data-root ROOT] <command>`.
Without `--data-root` the Store comes from `SOPRAN_DATA_ROOT` or the sopran config.
It needs the `experimental` and `kaguya` extras (numpy, scipy, polars).

## Workflow

```text
export-catalog -> verify-inputs -> prepare -> run (parallel, resumable) -> status -> finalize -> compare
```

| command | purpose |
|---|---|
| `export-catalog --catalog PATH --input-variant V [--workers N]` | SQLite catalog to day shards; existing days are skipped |
| `verify-inputs --input-variant V` | re-hash input shards after a transfer |
| `prepare --input-variant V --run-variant R [--groups G] [--fit-setting name=JSON]` | freeze settings, inputs and code/environment hashes in `run.json` |
| `run --run-variant R [--group i \| --days D...] [--workers N]` | fit the selected days; only unfinished days run |
| `status --run-variant R` | completed days and heartbeats |
| `finalize --run-variant R` | re-hash complete shards and register them in the Store catalog |
| `compare --run-variant R --reference FILE...` | objective, Beff and candidate agreement with another run's day Parquet |

**Export.** Each window's npz blob becomes row-major flattened list columns: folded
counts and exposures, `fit_valid`, `pair_observed`, full-pitch counts and exposures,
and energy/pitch edges. Every array is checked to be lossless as float64/bool.
Products of earlier fits (`observed_log_ratio`, `fitted_log_ratio`, `beam_ratio`) are
dropped. The window record (JSON) and the sha256 of record plus blob (`source_sha256`)
are kept. `days.json` lists every day, including days without input, with window and
distribution counts and checksums.

**Prepare and run.** `prepare` records the `FiniteBinFitSettings()` defaults with
`--fit-setting` overrides, the input catalog checksum, sha256 of the fit code and
native extension, and the Python/numpy/scipy/polars versions. `run` refuses to start
when these differ from the current environment; a run name cannot change settings.
`run` processes one day at a time and spreads its windows over spawned worker
processes, each forced to one BLAS/OpenMP thread. `--workers` defaults to the
allocated CPUs (affinity on Linux); `0` runs in-process. Every 256 windows a part is
saved in `work/<day>/`; a finished day becomes `shards/day=<day>.parquet` plus
`days/<day>.json`. Reruns skip finished days and reuse saved parts. Creating `STOP`
in the run directory makes every invocation save and exit after its current window.
Invocations write only their own days, so array tasks may run concurrently.
`--groups G` splits days into G groups balanced by distribution count; `run --group i`
processes group i.

Each window gets the default count-likelihood fit. The Rm profile (±1 dex, 13 points;
95% interval and `minimum_fit`) runs only for windows that pass the geometry gate (Bsc>0,
direction deviation ≤20°, radial angle <80°, `model_connected`) and carry no field flag.
`finalize` writes the column meanings to `schema.json`.

## Kyoto University supercomputer

Scripts are in `scripts/hpc/kyoto/`. Kyoto's Slurm is customized: resources are
`--rsc p=PROCS:t=THREADS:c=CORES:m=MEMORY`, `-p QUEUE` is required, and programs start
with `srun` ([KUDPC batch manual](https://web.kudpc.kyoto-u.ac.jp/manual/en/run/batch)).
The template follows that syntax; confirm queue names, limits and array variables
with the first pilot.

1. **Move data:** `rsync -av` `F:/sopran_data/features/kaguya/er/paired_distributions/`
   to `$SOPRAN_DATA_ROOT/features/kaguya/er/paired_distributions/` (about 15 GB).
2. **Build on a login node:**
   `SOPRAN_SRC=$HOME/src/sopran ENV_ROOT=/LARGE0/grXXXXX/$USER/sopran-env bash scripts/hpc/kyoto/setup_env.sh`
   installs uv and Rust under `$HOME` and builds sopran non-editable into a pinned venv.
   A manylinux x86_64 wheel from CI (`publish.yml`) installed with `--no-deps` also works.
3. **Verify and freeze on the login node:** `verify-inputs`, then
   `prepare --run-variant bb-default-kyoto --groups 16`.
4. **Pilot:** prepare a run with `--days 2009-02-17`, run it as one task (`-a 0`), and
   `compare` it with that day from the local run. Linux and Windows maths libraries
   differ, so expect small objective differences rather than bit equality; candidates
   should agree.
5. **Submit:** edit `-p`, `-t`, `--rsc` and `-a 0-(G-1)` in `er_fit.sbatch`, export
   `ENV_ROOT`, `SOPRAN_DATA_ROOT`, `RUN_VARIANT`, and `sbatch` it. Resubmit timed-out
   tasks with the same command; they resume.
6. **Collect:** check `status`, run `finalize`, and `rsync` the run directory
   `models/kaguya/er/finite_bin_fits/variants/<run>/` back.

## Verification

- `tests/test_er_batch.py`: lossless export, prepare→run→finalize→scan, part resume,
  STOP, refusal after code changes, balanced groups, spawned vs in-process equality.
- On 2026-10-10, 46 windows of 2009-02-17 from the local full-period run (which read the
  catalog directly) matched fits through the day shards exactly: Beff, objective,
  profile interval and candidate.
