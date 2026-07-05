# Variable Endpoint Pipeline API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `kg.esa1.<variable>.pipeline(time)` as the main batch API while keeping `pipeline()` explicit.

**Architecture:** Store an optional `default_variable` on `Pipeline`. Variable endpoints create a pipeline with `source=<dataset_id>`, `context=<instrument>`, and `default_variable=<endpoint name>`. `Pipeline.calibrate()` can omit `name` and resolve it from `default_variable`; KAGUYA pipeline execution uses the default variable when no `select_variables(...)` stage is present.

**Tech Stack:** Python dataclasses, existing SOPRAN `Pipeline`, KAGUYA `VariableEndpoint`, pytest.

---

## Task 1: Endpoint Pipeline Tests

**Files:**
- Modify: `tests/test_kaguya_pace.py`
- Modify: `tests/test_kaguya_loading.py`

- [x] Write a RED test that `kg.esa1.energy_flux.pipeline(time).calibrate(calibration="auto").write(...).run()` writes calibrated energy flux.
- [x] Write a RED test that `kg.esa1.counts.pipeline(time).write(...).run()` writes counts without `select_variables("counts")`.
- [x] Write a RED test that `plan.source == "kaguya.esa1.energy_flux"` and `calibrate()` records `name == "energy_flux"`.

## Task 2: Pipeline Defaults

**Files:**
- Modify: `src/sopran/core/pipeline.py`
- Modify: `src/sopran/missions/kaguya/mission.py`

- [x] Add `default_variable: str | None = None` to `Pipeline`.
- [x] Preserve `default_variable` in `_with_stage()` and `write()`.
- [x] Add `VariableEndpoint.pipeline(time)`.
- [x] Let `Pipeline.calibrate(name=None, **parameters)` use `default_variable`.
- [x] Let `_pipeline_variable()` fall back to `pipeline.default_variable`.

## Task 3: Docs and Verification

**Files:**
- Modify: `docs/missions/kaguya/esa1.md`
- Modify: `docs/en/missions/kaguya/esa1.md`

- [x] Update pipeline examples to use `kg.esa1.energy_flux.pipeline(time)` and `kg.esa1.counts.pipeline(time)`.
- [x] Run `python -m pytest -q`.
- [x] Run `python -m compileall src`.
- [x] Run `python -m ruff check .`.
- [x] Run `python -m mypy src`.
