# Plot Labels And API Typing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make SOPRAN spectrogram plots label axes and colorbars intuitively, and add concrete public API return types for the main plotting/data endpoints.

**Architecture:** Keep `PlotItem.name` as the plotted value name, but add explicit x/y/value label metadata so a spectrogram can show `energy` on the vertical axis and `energy_flux [unit]` on the colorbar. Preserve the existing `plot()` / `spectrogram()` public API while making return annotations concrete on `SopranArray`, KAGUYA endpoints, and ARTEMIS endpoints.

**Tech Stack:** Python dataclasses, Matplotlib, xarray metadata, mypy, pytest.

---

### Task 1: Spectrogram Axis And Colorbar Labels

**Files:**
- Modify: `tests/test_plotting.py`
- Modify: `src/sopran/core/plotting.py`
- Modify: `src/sopran/core/data.py`

- [x] **Step 1: Write failing tests**

Add tests that a spectrogram uses the y coordinate for the y-axis label and the plotted value plus units for the colorbar label.

- [x] **Step 2: Run RED test**

Run: `python -m pytest tests/test_plotting.py::test_spectrogram_labels_y_axis_and_colorbar_from_data_metadata -q`
Expected: FAIL because the y-axis label is currently `energy_flux` and no colorbar label exists.

- [x] **Step 3: Implement labels**

Add `value_label`, `x_label`, and `y_label` fields to `PlotItem`; infer labels from xarray coordinate attrs and array attrs; draw a Matplotlib colorbar for spectrogram panels.

- [x] **Step 4: Run GREEN test**

Run: `python -m pytest tests/test_plotting.py::test_spectrogram_labels_y_axis_and_colorbar_from_data_metadata -q`
Expected: PASS.

### Task 2: `SopranArray.plot()` Defaults For 2D Products

**Files:**
- Modify: `tests/test_plotting.py`
- Modify: `src/sopran/core/data.py`

- [x] **Step 1: Write failing test**

Add a test that `SopranArray.plot()` on `energy_flux(time, energy)` produces one spectrogram panel with intuitive labels and colorbar.

- [x] **Step 2: Run RED test**

Run: `python -m pytest tests/test_plotting.py::test_loaded_array_plot_uses_energy_spectrogram_labels_by_default -q`
Expected: FAIL until Task 1 implementation is applied.

- [x] **Step 3: Implement minimal propagation**

Ensure `SopranArray.spectrogram()` passes the reduced xarray object to `spn.spectrogram()` without losing attrs, and `plot(mode="auto")` keeps the inferred y coordinate.

- [x] **Step 4: Run GREEN test**

Run: `python -m pytest tests/test_plotting.py::test_loaded_array_plot_uses_energy_spectrogram_labels_by_default -q`
Expected: PASS.

### Task 3: Public Return Types For Main Plotting APIs

**Files:**
- Modify: `tests/test_typing.py`
- Modify: `src/sopran/core/data.py`
- Modify: `src/sopran/missions/kaguya/mission.py`
- Modify: `src/sopran/missions/artemis/mission.py`

- [x] **Step 1: Write failing typing test**

Add a source-inspection test that the main public plotting methods no longer expose `Any` return annotations.

- [x] **Step 2: Run RED test**

Run: `python -m pytest tests/test_typing.py::test_main_plotting_api_return_annotations_are_concrete -q`
Expected: FAIL because several methods currently return `Any`.

- [x] **Step 3: Add concrete annotations**

Use `PlotItem`, `PlotResult`, `QuicklookResult`, and `SopranArray` annotations where the implementation already guarantees those types. Keep genuinely dynamic backend hooks internal.

- [x] **Step 4: Run GREEN test**

Run: `python -m pytest tests/test_typing.py::test_main_plotting_api_return_annotations_are_concrete -q`
Expected: PASS.

### Task 4: Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/getting-started/first-analysis.md`
- Modify: `docs/missions/kaguya/esa1.md`

- [x] **Step 1: Update examples**

Show `spn.kaguya.esa1.energy_flux.plot(time, calibration="auto", log_color=True)` as the intuitive quick path, and note that spectrograms use time on x, energy/pitch on y, and the product value on color.

- [x] **Step 2: Verify docs are consistent**

Run: `rg -n "energy_flux\\.plot|spectrogram\\(.*y=\"energy\"|colorbar" README.md docs`
Expected: The main examples use the new quick plotting wording and existing explicit spectrogram examples remain valid.

### Task 5: Verification

**Files:**
- No new files.

- [x] **Step 1: Run focused tests**

Run: `python -m pytest tests/test_plotting.py tests/test_typing.py tests/test_kaguya_pace.py::test_kaguya_esa1_variable_endpoint_can_plot_with_time tests/test_artemis.py::test_artemis_esa_endpoint_builds_spectrogram_plot_item -q`
Expected: PASS.

- [x] **Step 2: Run project checks**

Run:

```powershell
python -m pytest -q
python -m compileall src
python -m ruff check src tests
python -m mypy src
git diff --check
```

Expected: all exit 0.
