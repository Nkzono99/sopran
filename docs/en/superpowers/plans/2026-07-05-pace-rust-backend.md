# PACE Rust Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional Rust backend for KAGUYA PACE PBF decode without changing the public Python API.

**Architecture:** Keep Python as the public API and reference implementation. Add a Rust CLI backend that decodes one or more PBF files in one process invocation and writes a compact decoded bundle (`headers.json` plus `.npy` arrays) to a temporary directory; Python reconstructs the existing `PaceData` model from that bundle. The backend is opt-in via `backend="rust"` or `SOPRAN_PACE_BACKEND=rust`, with `backend="auto"` falling back to Python when the CLI is unavailable.

**Tech Stack:** Python dataclasses, numpy, pytest, Rust 2021, cargo, clap, flate2, serde_json, byteorder.

---

### Task 1: Public Backend Selection

**Files:**
- Modify: `src/sopran/missions/kaguya/pace.py`
- Test: `tests/test_kaguya_pace.py`

- [ ] **Step 1: Write failing tests**

Add tests that `read_pace_pbf(..., backend="python")` preserves the current result, `backend="missing"` is rejected, and `SOPRAN_PACE_BACKEND=python` is honored.

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest tests/test_kaguya_pace.py::test_read_pace_pbf_accepts_python_backend tests/test_kaguya_pace.py::test_read_pace_pbf_rejects_unknown_backend tests/test_kaguya_pace.py::test_read_pace_pbf_uses_backend_environment_default -q`

Expected: FAIL because the `backend` argument is not implemented.

- [ ] **Step 3: Implement minimal backend selection**

Add `backend: Literal["auto", "python", "rust"] | None = None` to `read_pace_pbf()`. Resolve `None` from `SOPRAN_PACE_BACKEND` with default `"auto"`, reject unknown values, and route `"python"` plus `"auto"` to the existing Python decoder for now.

- [ ] **Step 4: Run tests to verify GREEN**

Run the same pytest command. Expected: PASS.

### Task 2: Rust CLI Decoder

**Files:**
- Create: `Cargo.toml`
- Create: `crates/sopran-backend/Cargo.toml`
- Create: `crates/sopran-backend/src/main.rs`
- Create: `crates/sopran-backend/src/pace.rs`

- [ ] **Step 1: Write Rust tests first**

Add unit tests for endian selection, payload size, and decoding a synthetic type `0x01` record into one record with `cnt` shape `[32, 4, 16]`.

- [ ] **Step 2: Run tests to verify RED**

Run: `cargo test -p sopran-backend pace`

Expected: FAIL before implementation compiles.

- [ ] **Step 3: Implement Rust decoder**

Implement a CLI command:

```text
sopran-backend pace-decode --output <dir> <file>...
```

It must read `.dat` and `.dat.gz`, decode the same PBF record types as Python `PBF_SPECS`, write `headers.json`, and write each decoded array as a `.npy` file named `record_<index>_<name>.npy`.

- [ ] **Step 4: Run Rust tests**

Run: `cargo test -p sopran-backend`

Expected: PASS.

### Task 3: Python Rust Bridge

**Files:**
- Modify: `src/sopran/missions/kaguya/pace.py`
- Test: `tests/test_kaguya_pace.py`

- [ ] **Step 1: Write failing bridge test**

Add a test that builds or locates the Rust CLI, calls `read_pace_pbf(path, backend="rust")`, and compares `sensor`, headers, record types, and `cnt` arrays with `backend="python"`. Skip only when the executable is unavailable.

- [ ] **Step 2: Run test to verify RED**

Run: `python -m pytest tests/test_kaguya_pace.py::test_read_pace_pbf_rust_backend_matches_python -q`

Expected: FAIL because the Rust bridge is not implemented.

- [ ] **Step 3: Implement bridge**

Resolve the CLI from `SOPRAN_BACKEND_EXE`, `target/debug/sopran-backend(.exe)`, or `target/release/sopran-backend(.exe)`. Invoke it once per `read_pace_pbf()` call, load `headers.json` and `.npy` arrays, and reconstruct `PaceData`.

- [ ] **Step 4: Run bridge test**

Run the same pytest command. Expected: PASS when the Rust CLI is built; otherwise SKIP only for unavailable executable.

### Task 4: Auto Fallback and Documentation

**Files:**
- Modify: `src/sopran/missions/kaguya/pace.py`
- Modify: `docs/reference/status.md`
- Modify: `docs/en/reference/status.md`

- [ ] **Step 1: Write fallback test**

Add a test that `backend="auto"` returns Python decode results when no Rust executable is configured.

- [ ] **Step 2: Run fallback test to verify behavior**

Run: `python -m pytest tests/test_kaguya_pace.py::test_read_pace_pbf_auto_falls_back_to_python -q`

Expected: PASS after Task 1, still PASS after bridge implementation.

- [ ] **Step 3: Update docs**

Document that Rust backend is optional, coarse-grained, and invoked once per decode call to avoid per-record overhead.

- [ ] **Step 4: Final verification**

Run:

```powershell
python -m pytest -q
python -m ruff check .
python -m mypy src
python -m compileall src
cargo test
```

Expected: all commands exit 0.
