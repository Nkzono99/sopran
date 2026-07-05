# KAGUYA PACE Energy Flux Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement ESA1 counts-to-energy_flux calibration as a first-class sibling endpoint, loaded-data helper, and pipeline stage.

**Architecture:** Keep `counts` as raw decoded PBF data and make `energy_flux` a calibrated `SopranArray` derived from decoded counts plus PACE calibration tables. Add a focused calibration helper in `sopran.missions.kaguya.data`, route `VariableEndpoint.load(..., calibration=...)` through `PaceInstrument.load`, and add `Pipeline.calibrate("energy_flux")` as an explicit stage before writing calibrated output.

**Tech Stack:** Python dataclasses, numpy, xarray, polars, pytest, existing SOPRAN Store/Pipeline APIs.

---

## File Map

- Modify `src/sopran/missions/kaguya/data.py`: add `to_energy_flux()`, calibrated xarray generation, and calibration error helper.
- Modify `src/sopran/missions/kaguya/mission.py`: pass calibration options through `VariableEndpoint`, auto-load calibration tables for energy_flux, and apply pipeline calibration.
- Modify `src/sopran/core/pipeline.py`: add `Pipeline.calibrate(name, **parameters)`.
- Modify `tests/test_kaguya_pace.py`: add synthetic calibration tests for helper behavior.
- Modify `tests/test_kaguya_loading.py`: add endpoint and pipeline behavior tests.
- Modify `docs/missions/kaguya/esa1.md` and `docs/reference/status.md`: update placeholder wording after implementation.

## Task 1: Add Synthetic Energy Flux Helper Tests

**Files:**
- Modify: `tests/test_kaguya_pace.py`

- [ ] **Step 1: Write failing helper test**

Add a test using a synthetic `PaceData` record with one nonzero count and synthetic INFO calibration where `gfactor_4x16=2.0`. Expected output uses the old Python reference formula for counts-to-eflux conversion:

```text
energy_flux = counts / (integ_t * gfactor * eff)
integ_t = 16 / sampl_time
eff = 0.6
```

```python
def test_kaguya_esa1_to_energy_flux_uses_synthetic_gfactor() -> None:
    sample_time = datetime(2008, 1, 1, 0, 0, tzinfo=UTC).timestamp()
    counts = np.zeros((32, 4, 16), dtype=np.uint16)
    counts[0, 0, 0] = 10
    pace = PaceData(
        sensor=0,
        headers=(
            {
                "time": sample_time,
                "type": 0x01,
                "sensor": 0,
                "data_quality": 0,
                "sampl_time": 16,
                "svs_tbl": 0,
            },
        ),
        records={0x01: (PaceRecord(type=0x01, index=0, arrays={"cnt": counts}),)},
        source_files=(),
        record_order=(PaceRecord(type=0x01, index=0, arrays={"cnt": counts}),),
    )
    shape = (8, 32, 4, 16)
    info = {
        "gfactor_4x16": np.full(shape, 2.0, dtype=float),
        "ene_4x16": np.ones(shape, dtype=float),
    }
    data = KaguyaESA1Data(
        time=spn.day("2008-01-01"),
        calibration=PaceCalibration(info={0: info}),
    )
    object.__setattr__(data, "pace", pace)

    flux = data.to_energy_flux()
    array = flux.to_xarray()

    assert flux.name == "energy_flux"
    assert array.shape == (1, 32, 64)
    assert array.values[0, 0, 0] == pytest.approx(10.0 / (1.0 * 2.0 * 0.6))
    assert array.attrs["physical_validity"] == "calibrated"
```

- [ ] **Step 2: Run test to verify failure**

Run: `python -m pytest tests/test_kaguya_pace.py::test_kaguya_esa1_to_energy_flux_uses_synthetic_gfactor -q`

Expected: FAIL because `KaguyaESA1Data.to_energy_flux` does not exist.

## Task 2: Implement Minimal ESA1 `to_energy_flux()`

**Files:**
- Modify: `src/sopran/missions/kaguya/data.py`

- [ ] **Step 1: Add calibration error and helper method**

Implement `KaguyaPaceData.to_energy_flux()` so it returns a `SopranArray` named `energy_flux`. For ESA1 type `0x01` records, map flattened look index to `(polar, azimuth)` with `polar = look // 16`, `azimuth = look % 16`, and use `counts / (integ_t * gfactor_4x16[ram, energy, polar, azimuth] * eff)`. Use `ram=svs_tbl` from the header when present, otherwise `0`, `integ_t=16/sampl_time`, and default `eff=0.6`.

- [ ] **Step 2: Run helper test**

Run: `python -m pytest tests/test_kaguya_pace.py::test_kaguya_esa1_to_energy_flux_uses_synthetic_gfactor -q`

Expected: PASS.

## Task 3: Route `kg.esa1.energy_flux.load()` Through Calibration

**Files:**
- Modify: `tests/test_kaguya_loading.py`
- Modify: `src/sopran/missions/kaguya/mission.py`
- Modify: `src/sopran/missions/kaguya/data.py`

- [ ] **Step 1: Write failing endpoint tests**

Add tests that monkeypatch `kg.esa1.load_calibration()` to return synthetic calibration and assert:

```python
flux = kg.esa1.energy_flux.load(time, calibration="auto", download="never")
assert flux.name == "energy_flux"
assert flux.to_xarray().attrs["physical_validity"] == "calibrated"
```

Also assert `kg.esa1.energy_flux.load(time, calibration=None)` raises an actionable error when no calibration is loaded.

- [ ] **Step 2: Run endpoint tests to verify failure**

Run: `python -m pytest tests/test_kaguya_loading.py::test_kaguya_esa1_energy_flux_endpoint_loads_calibrated_flux -q`

Expected: FAIL because `VariableEndpoint.load()` does not accept `calibration`.

- [ ] **Step 3: Implement endpoint routing**

Add `calibration: PaceCalibration | Literal["auto"] | None = None` to `VariableEndpoint.load`, `plot`, `line`, and `spectrogram` where they call `_load_endpoint`. For `self.name == "energy_flux"`, pass calibration through to `PaceInstrument.load`; for other variables ignore the argument unless supplied with an invalid value.

- [ ] **Step 4: Run endpoint tests**

Run: `python -m pytest tests/test_kaguya_loading.py::test_kaguya_esa1_energy_flux_endpoint_loads_calibrated_flux tests/test_kaguya_loading.py::test_kaguya_esa1_energy_flux_requires_calibration -q`

Expected: PASS.

## Task 4: Add Pipeline Calibration Stage

**Files:**
- Modify: `src/sopran/core/pipeline.py`
- Modify: `src/sopran/missions/kaguya/mission.py`
- Modify: `tests/test_kaguya_loading.py`

- [ ] **Step 1: Write failing plan and run tests**

Add assertions that:

```python
pipe = kg.esa1.pipeline(time).decode().calibrate("energy_flux").select_variables("energy_flux")
assert pipe.plan().stage_names == ("decode", "calibrate", "select_variables")
assert pipe.plan().stages[1].parameters["name"] == "energy_flux"
```

Run: `python -m pytest tests/test_kaguya_loading.py::test_kaguya_esa1_pipeline_records_calibrate_stage -q`

Expected: FAIL because `Pipeline.calibrate` does not exist.

- [ ] **Step 2: Implement `Pipeline.calibrate()`**

Add:

```python
def calibrate(self, name: str, **parameters: Any) -> Pipeline:
    return self._with_stage("calibrate", name=name, **parameters)
```

- [ ] **Step 3: Make KAGUYA pipeline use calibration**

In `_run_pipeline`, detect `calibrate` stage for `energy_flux` and load data with `calibration="auto"` before `write_parquet(variable="energy_flux")`.

- [ ] **Step 4: Run pipeline tests**

Run: `python -m pytest tests/test_kaguya_loading.py::test_kaguya_esa1_pipeline_records_calibrate_stage tests/test_kaguya_pace.py::test_kaguya_esa1_pipeline_writes_energy_flux_dataset -q`

Expected: PASS.

## Task 5: Update Docs and Status

**Files:**
- Modify: `docs/missions/kaguya/esa1.md`
- Modify: `docs/reference/status.md`

- [ ] **Step 1: Replace placeholder language**

State that `energy_flux` is calibrated when calibration tables are available and that missing calibration raises an actionable error unless placeholder mode is explicitly requested.

- [ ] **Step 2: Run docs and focused tests**

Run:

```powershell
python -m pytest tests/test_kaguya_pace.py tests/test_kaguya_loading.py -q
python -m compileall src
```

Expected: both commands pass.

## Task 6: Final Verification

**Files:**
- Inspect: `git status --short`

- [ ] **Step 1: Run project checks**

Run:

```powershell
python -m pytest -q
python -m compileall src
```

Expected: both commands pass.

- [ ] **Step 2: Commit implementation**

Commit only the feature files:

```powershell
git add src/sopran/missions/kaguya/data.py src/sopran/missions/kaguya/mission.py src/sopran/core/pipeline.py tests/test_kaguya_pace.py tests/test_kaguya_loading.py docs/missions/kaguya/esa1.md docs/reference/status.md docs/superpowers/plans/2026-07-05-kaguya-pace-energy-flux.md
git commit -m "Add KAGUYA PACE energy flux calibration"
```
