# PACE PyO3 Native Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the optional PACE subprocess decoder with an in-process PyO3 native module.

**Architecture:** Keep Python as the public API and reference implementation. Build the `crates/sopran-native` PyO3 extension into the main `sopran` wheel as `sopran._native`; Python calls it once per `read_pace_pbf()` invocation and reconstructs the existing `PaceData` model from `bytes + dtype + shape` array payloads. `backend="rust"` requires the module, while `backend="auto"` falls back to Python when it is not installed.

**Tech Stack:** Python dataclasses, numpy, pytest, Rust 2021, PyO3, maturin, flate2, byteorder.

---

### Task 1: Python Native Bridge

**Files:**
- Modify: `src/sopran/missions/kaguya/pace.py`
- Test: `tests/test_kaguya_pace.py`

- [x] Write a failing test that inserts a fake `sopran._native` module and expects `read_pace_pbf(..., backend="rust")` to use it.
- [x] Implement `_read_pace_pbf_native()` using `importlib.import_module("sopran._native")`.
- [x] Convert native array payloads from `{"dtype", "shape", "data"}` to NumPy arrays with `np.frombuffer`.
- [x] Keep `backend="auto"` falling back to Python only when the native module is missing.

### Task 2: PyO3 Crate

**Files:**
- Create: `crates/sopran-native/Cargo.toml`
- Create: `crates/sopran-native/pyproject.toml`
- Create: `crates/sopran-native/src/lib.rs`
- Modify: `Cargo.toml`

- [x] Create a `sopran._native` PyO3 extension module.
- [x] Port the PACE PBF decoder into Rust without CLI parsing or temporary files.
- [x] Return one structured Python dict per decode call, with headers and record arrays.
- [x] Add Rust unit tests for endian detection, payload sizing, and synthetic type `0x01` decode.

### Task 3: Validation

**Files:**
- Modify: `pyproject.toml`
- Modify: `docs/reference/status.md`
- Modify: `docs/en/reference/status.md`
- Modify: `docs/design/spec.md`

- [x] Add `maturin` to dev dependencies.
- [x] Install the native module with `python -m pip install -e .` or `python -m maturin develop --release` from the repository root.
- [x] Run Python parity tests comparing `backend="python"` and `backend="rust"`.
- [x] Run the full repository verification suite.
