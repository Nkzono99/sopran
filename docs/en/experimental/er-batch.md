# Full-Period ER Batch (Day Shards, Slurm)

`sopran.experimental.kaguya.er_batch` runs finite-bin fits and Rm profiles over saved
paired distributions for the whole mission. The same commands run on a workstation
and as Slurm array jobs on the Kyoto University supercomputer. Inputs and outputs are
Store datasets split into daily Parquet shards, so `rsync` moves them as they are.

| dataset | layer | variant | content |
|---|---|---|---|
| `experimental.kaguya.er.paired_distributions` | `features` | input build | folded counts, exposures and record per window; one shard per day |
| `experimental.kaguya.er.finite_bin_fits` | `models` | run name | fit, profile and candidate per window; one shard per day |

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

**Input contract.** A SQLite catalog, built outside SOPRAN, has one
table `windows(sample_id TEXT, day TEXT, record TEXT, maps BLOB)`. `record` is the
window record as JSON (`time`, `b_sc_nT`, `affected_side`, `field_connection_status`,
`field_radial_abs_cosine_min`, `magnetic_direction_max_deviation_deg`, `reason`).
`maps` is an `.npz` with the `FLOAT_ARRAYS` and `BOOL_ARRAYS` arrays (folded arrays
`energy x pitch_folded`, `global_*` arrays `energy x pitch`), or NULL for a window
without a distribution.

**Export.** Each window's npz blob becomes row-major flattened list columns: folded
counts and exposures, `fit_valid`, `pair_observed`, full-pitch counts and exposures,
and energy/pitch edges. Every array is checked to be lossless as float64/bool.
Products of earlier fits (`observed_log_ratio`, `fitted_log_ratio`, `beam_ratio`) are
dropped. The window record (JSON) and the sha256 of record plus blob (`source_sha256`)
are kept. `days.json` lists every day, including days without input, with window and
distribution counts and checksums.

**Building inputs with SOPRAN parts.** Instead of a SQLite catalog, input shards can
be built from raw data with these parts; their defaults follow the 2026-09
full-period run (`halekas_mission_v1`). Parallelizing days, resuming and logging a
full-period build stay in the caller's script.

| step | parts |
|---|---|
| one day of native records with LMAG geometry | `KaguyaErInstrument(mission).native_records(day)` |
| 16 s windows and diagnostics | `er_windows.calendar_windows`, `window_record`, `window_input_diagnostic` |
| SVM3D connection | `moon.connection.trace_connection`, `classify_connection` (`ConnectionPolicy`) |
| paired map | `er_windows.window_pitch_records` then `electron_reflection.maps.build_paired_map` |
| write and register | `er_batch.window_input_row` then `er_batch.write_input_days` |

`window_record` takes the field-direction spread from LMAG samples in the window
and `field_radial_abs_cosine_min` from the B/r cosine at the records.
`build_paired_map` orients each record so the affected side is at low pitch,
redistributes it by bin overlap onto a 20-1500 eV, 24 energy x 16 pitch grid,
sums counts and exposure, and folds into affected and reference halves;
`fit_valid` needs positive exposure on both sides, counts, and at least three
cells per energy row. The connection traces SVM3D plus a uniform residual at
0.5 km steps to a 6.1 km stop altitude within 1000 km; a window is
`model_connected` when every inward trace reaches the shell, no reverse trace
does, and the sign does not change. The Japanese page has a full example.

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

1. **Move data:** the input dataset is managed, so the Store sync recipe applies
   `sopran-store sync-list --dataset experimental.kaguya.er.paired_distributions > files.txt`,
   `rsync -av --delay-updates --files-from=files.txt /path/to/sopran_data/ <host>:$SOPRAN_DATA_ROOT/`,
   then `sopran-store rebuild` and `verify-inputs` on the cluster.
2. **Build on a login node:**
   `SOPRAN_SRC=$HOME/src/sopran ENV_ROOT=/LARGE0/grXXXXX/$USER/sopran-env bash scripts/hpc/kyoto/setup_env.sh`
   installs uv and Rust under `$HOME` and builds sopran non-editable into a pinned venv.
   A manylinux x86_64 wheel from CI (`publish.yml`) installed with `--no-deps` also works.
3. **Verify and freeze on the login node:** `verify-inputs`, then
   `prepare --input-variant <build> --run-variant <run> --groups 16`.
4. **Pilot:** prepare a run with `--days` set to one day finished locally, run it as
   one task (`-a 0`), and `compare` it with that day from the local run. Linux and Windows maths libraries
   differ, so expect small objective differences rather than bit equality; candidates
   should agree.
5. **Submit:** edit `-p`, `-t`, `--rsc` and `-a 0-(G-1)` in `er_fit.sbatch`, export
   `ENV_ROOT`, `SOPRAN_DATA_ROOT`, `RUN_VARIANT`, and `sbatch` it. Resubmit timed-out
   tasks with the same command; they resume.
6. **Collect:** check `status`, run `finalize`, list the run with
   `sopran-store sync-list --dataset experimental.kaguya.er.finite_bin_fits --variant <run>`,
   copy it back with `rsync --files-from`, and run `sopran-store rebuild` locally.

## Verification

- `tests/test_er_batch.py`: lossless export, prepare→run→finalize→scan, part resume,
  STOP, refusal after code changes, balanced groups, spawned vs in-process equality.
- Real-data agreement is checked with `compare`; keep each run's record under `working/`.
