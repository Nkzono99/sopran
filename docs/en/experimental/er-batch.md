# ER Full-Period Batch

`sopran.experimental.kaguya.er_batch` is a CLI that runs finite-bin fits and $R_m$ profiles over the full mission on saved paired distributions.
The same commands run on a workstation and as Slurm array jobs on the Kyoto University supercomputer.
Inputs and outputs are Store datasets split into daily Parquet, so `rsync` can move them as they are.

| Dataset | Layer | variant | Contents |
|---|---|---|---|
| `experimental.kaguya.er.paired_distributions` | `features` | Input build name | Folded counts, exposures, and window records per 16 s window; one shard per day |
| `experimental.kaguya.er.finite_bin_fits` | `models` | Run name | Fits, profiles, and candidates per window; one shard per day |

Commands take the form `python -m sopran.experimental.kaguya.er_batch [--data-root ROOT] <command>`.
Without `--data-root`, the Store from `SOPRAN_DATA_ROOT` (or the SOPRAN configuration) is used.
It needs the `experimental` and `kaguya` extras.

## Flow

```text
export-catalog → verify-inputs → prepare → run (parallel, resumable) → status → finalize → compare
```

| Command | Action |
|---|---|
| `export-catalog --catalog PATH --input-variant V [--workers N]` | Convert a SQLite catalog to daily shards; existing days are skipped |
| `verify-inputs --input-variant V` | Check input shard checksums after a transfer |
| `prepare --input-variant V --run-variant R [--groups G] [--fit-setting name=JSON]` | Freeze settings, inputs, and code and environment hashes in `run.json` |
| `run --run-variant R [--group i \| --days D...] [--workers N]` | Fit the given days; only unfinished days are processed |
| `status --run-variant R` | Show completed days and heartbeats |
| `finalize --run-variant R` | Recompute checksums of completed shards and register them in the Store catalog |
| `compare --run-variant R --reference FILE...` | Compare objectives, $B_\mathrm{eff}$, and candidates of the same windows with daily Parquet from another run |

## Preparing inputs

Inputs are either converted from a SQLite catalog of per-window paired distributions, or built from source data with the SOPRAN parts below.

### Converting a SQLite catalog

The catalog has one table, `windows`.

| Column | Type | Contents |
|---|---|---|
| `sample_id` | TEXT | ID of the 16 s window |
| `day` | TEXT | UTC day (`YYYY-MM-DD`) |
| `record` | TEXT | Window record (JSON); `time`, `b_sc_nT`, `affected_side`, `field_connection_status`, `field_radial_abs_cosine_min`, `magnetic_direction_max_deviation_deg`, and `reason` are read |
| `maps` | BLOB | `.npz`; NULL for windows without a distribution |

`maps` holds the arrays in `FLOAT_ARRAYS` and `BOOL_ARRAYS`. Folded arrays are `energy × pitch_folded`,
and `global_*` arrays are `energy × pitch`.

```bash
python -m sopran.experimental.kaguya.er_batch --data-root /path/to/sopran_data export-catalog \
  --catalog /path/to/catalog.sqlite --input-variant <build> --workers 3
```

The conversion moves folded counts, exposures, `fit_valid`, and `pair_observed`, plus all-pitch counts, exposures,
and energy and pitch edges, from each window's npz into row-major flattened list columns. It also checks that every array is representable losslessly as float64 or bool.
Derived quantities of earlier fits (`observed_log_ratio`, `fitted_log_ratio`, `beam_ratio`) are not carried over.
The window record (JSON) and the sha256 of record plus npz (`source_sha256`) are kept, and `days.json` lists window counts,
distribution counts, and checksums for every day, including days without input.

### Building from source data with SOPRAN parts

Parts are also available to build input shards from source data without a SQLite catalog.
Their defaults match the rules of the September 2026 full-period run (`halekas_mission_v1`).
Assembling a full-period run (parallel days, resuming, logs) is left to your own script.

| Stage | Part |
|---|---|
| Native records and LMAG geometry for one day | `KaguyaErInstrument(mission).native_records(day)` |
| Aggregation into 16 s windows and diagnostics | `er_windows.calendar_windows`, `window_record`, `window_input_diagnostic` |
| Connection screening with SVM3D | `moon.connection.trace_connection`, `classify_connection` (`ConnectionPolicy`) |
| Paired distribution | `er_windows.window_pitch_records` → `electron_reflection.maps.build_paired_map` |
| Writing and registration | `er_batch.window_input_row` → `er_batch.write_input_days` |

```python
import numpy as np
import sopran as spn
from sopran.experimental.electron_reflection.maps import build_paired_map
from sopran.experimental.kaguya import er_batch
from sopran.experimental.kaguya.er import KaguyaErInstrument
from sopran.experimental.kaguya.er_windows import (
    calendar_windows, usable_record_indices, window_input_diagnostic,
    window_pitch_records, window_record,
)
from sopran.experimental.moon.connection import (
    classify_connection, trace_connection, unconnected_window,
)
from sopran.experimental.moon.svm3d import SVM3DShellGrid

day = spn.day("2008-02-10")
records = KaguyaErInstrument(spn.Kaguya(download="never")).native_records(day)
usable = np.unique(np.concatenate(
    [usable_record_indices(a, np.arange(records.times.size)) for a in records.arrays.values()]
))
traces = trace_connection(
    SVM3DShellGrid.load("svm3d_shell.npz"),
    records.position_km[usable], records.magnetic_field_nT[usable],
)
connection = classify_connection(
    traces, records.times[usable].astype("datetime64[s]").astype(int) // 16
)

rows = []
for window_id, indices in calendar_windows(records.times, day):
    record = window_record(window_id, indices, records)
    record.update(connection.get(window_id, unconnected_window()))
    record["joint_input_diagnostic"] = window_input_diagnostic(indices, records.arrays)
    usable_here = any(usable_record_indices(a, indices).size for a in records.arrays.values())
    reason = "no_records" if not indices.size else None if usable_here else "no_usable_geometry"
    if reason is None and not record["connection_eligible"]:
        reason = "connection_" + record["field_connection_status"]
    if reason:
        record["reason"] = reason
    maps = None if reason else build_paired_map(window_pitch_records(records, indices))
    rows.append(er_batch.window_input_row(record, maps))
er_batch.write_input_days(spn.Store(), "<build>", {"2008-02-10": rows})
```

The parts follow these rules.

- `window_record` derives the maximum field-direction deviation from the LMAG samples in the window, and `field_radial_abs_cosine_min`
  from the cosine between $B$ and $r$ at the record times.
- `build_paired_map` orients each record so the affected side is at low pitch angles, distributes it onto a 20–1500 eV, 24 energy × 16 pitch grid
  by bin overlap, sums counts and exposures, and folds into affected and reference.
  `fit_valid` marks the range where both sides of the pair have positive exposure and counts, with at least three cells per energy row.
- Connection screening traces the SVM3D field plus a uniform residual in 0.5 km steps, stopping at 6.1 km altitude and at most 1000 km.
  Windows where the inward trace reaches the shell, the opposite one does not, and the side does not change within the window are `model_connected`.

## Freezing and running

`prepare` records in `run.json` the settings (defaults of `FiniteBinFitSettings()` plus `--fit-setting` overrides) and the input catalog checksum.
`--min-fit-energy E` removes rows whose centre energy is below E eV from the fitted cells and records it as `config.min_fit_energy_eV`.
It also records the sha256 of the fitting code and the Rust extension, and the versions of Python, numpy, scipy, and polars.
`run` compares these with the current environment at startup and stops on any difference. To change settings, `prepare` a new run name.

`run` processes days one at a time and spreads each day's windows over worker processes (spawn).
Workers pin `OMP_NUM_THREADS` and similar variables to 1. `--workers` defaults to the allocated CPUs (affinity on Linux), and `0` runs in process.
Every 256 windows are saved to `work/<day>/part-*.parquet`; when a day finishes, `shards/day=<day>.parquet` and `days/<day>.json` are written.
Rerunning skips completed days and never recomputes saved parts.
Creating a file named `STOP` in the run directory makes every invocation save and exit after its current window.
Each invocation writes only its own days' files, so array jobs may run at the same time.
`--groups G` splits days into G groups balanced by distribution count, and `run --group i` processes group i.

Each window is fitted with the default count-likelihood settings. Profiles are computed only for windows that meet the geometry conditions
($B_\mathrm{sc} > 0$, field-direction deviation ≤ 20°, angle to radial < 80°, `model_connected`) and have no `field_flags`.
Profiles use 13 points over $R_m$ ±1 dex and give the 95% interval and `minimum_fit`. Column meanings are in the `schema.json` written by `finalize`.

## Running on the Kyoto University supercomputer

Scripts are in `scripts/hpc/kyoto/`. Kyoto's Slurm is extended: resources are requested with
`--rsc p=PROCS:t=THREADS:c=CORES:m=MEMORY`, the `-p` queue is mandatory, and programs start with `srun`
([KUDPC batch processing manual](https://web.kudpc.kyoto-u.ac.jp/manual/en/run/batch)).
The templates follow this format, but confirm queue names, limits, and array-job environment variables in a first pilot.

1. **Move the data.** Input datasets are managed and thus in the default list, but here only the inputs are selected by name.

    ```bash
    sopran-store --data-root /path/to/sopran_data sync-list \
      --dataset experimental.kaguya.er.paired_distributions > files.txt
    rsync -av --delay-updates --files-from=files.txt /path/to/sopran_data/ <host>:$SOPRAN_DATA_ROOT/
    ```

    After the transfer, run `sopran-store rebuild` and `verify-inputs` on the destination.

2. **Build the environment on a login node.** Clone SOPRAN with git and run the following; it installs uv and Rust under `$HOME`
   and builds SOPRAN (non-editable) into a version-pinned venv.

    ```bash
    SOPRAN_SRC=$HOME/src/sopran ENV_ROOT=/LARGE0/grXXXXX/$USER/sopran-env \
      bash scripts/hpc/kyoto/setup_env.sh
    ```

    Alternatively, install the manylinux x86_64 wheel built by CI (`publish.yml`) with `--no-deps`.

3. **Check and freeze on the login node.**

    ```bash
    source $ENV_ROOT/venv/bin/activate
    export SOPRAN_DATA_ROOT=/LARGE0/grXXXXX/$USER/sopran_data
    python -m sopran.experimental.kaguya.er_batch verify-inputs --input-variant <build>
    python -m sopran.experimental.kaguya.er_batch prepare --input-variant <build> \
      --run-variant <run> --groups 16
    ```

4. **Check agreement with a pilot.** Create a separate run with `--days` set to one day already completed locally, and run one task (`-a 0`).
   Transfer that day's Parquet from the local run and compare with `compare`. Linux and Windows implement exponential and logarithm functions differently,
   so exact agreement is not expected; check that relative objective differences are small and candidates agree.

5. **Submit production.** Edit `-p`, `-t`, `--rsc`, and `-a 0-(G-1)` in `scripts/hpc/kyoto/er_fit.sbatch`,
   export `ENV_ROOT`, `SOPRAN_DATA_ROOT`, and `RUN_VARIANT`, and `sbatch`. Tasks that time out continue where they stopped when resubmitted with the same command.

6. **Collect results.** Confirm completion with `status` and register with `finalize`.
   Bring results back with the list from `sopran-store sync-list --dataset experimental.kaguya.er.finite_bin_fits --variant <run>`, then run `sopran-store rebuild` locally.

## Validation

`tests/test_er_batch.py` checks that conversion is lossless, the prepare → run → finalize → scan flow, resuming from parts, `STOP`,
rejection after code changes, balanced day groups, and agreement between spawn workers and in-process runs.
Comparisons on real data use `compare`, and their results are recorded per run in `working/`.
