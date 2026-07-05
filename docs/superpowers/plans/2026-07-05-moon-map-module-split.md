# Moon Map Module Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `sopran.bodies.moon` をサブパッケージへ分割し、Tsunakawa SVM reader を Moon 固有 module に移す。

**Architecture:** Public API は `spn.Moon`, `sopran.bodies.Moon`, `sopran.bodies.moon.Moon`, `spn.RasterLayer`, `spn.Region` を維持する。Moon 固有の endpoint/source/schema/guide/loader を `sopran.bodies.moon.*` に分け、汎用 raster 型と GeoTIFF reader は `sopran.maps.raster` に残す。

**Tech Stack:** Python dataclasses, pathlib, numpy, rasterio optional backend, pytest, ruff, mypy.

---

### Task 1: Import Boundary Tests

**Files:**
- Modify: `tests/test_moon_surface.py`

- [ ] Add tests that import `Moon`, `SurfaceEndpoint`, and `SurfacePlan` from `sopran.bodies.moon`.
- [ ] Add tests that import `MOON_SURFACE_SCHEMA` from `sopran.bodies.moon.schema`.
- [ ] Add tests that import `read_tsunakawa_svm_text` from `sopran.bodies.moon.svm`.
- [ ] Run `python -m pytest tests/test_moon_surface.py -q` and confirm the new imports fail before implementation.

### Task 2: Package Split

**Files:**
- Create: `src/sopran/bodies/moon/__init__.py`
- Create: `src/sopran/bodies/moon/api.py`
- Create: `src/sopran/bodies/moon/models.py`
- Create: `src/sopran/bodies/moon/schema.py`
- Create: `src/sopran/bodies/moon/sources.py`
- Create: `src/sopran/bodies/moon/parameters.py`
- Create: `src/sopran/bodies/moon/guides.py`
- Create: `src/sopran/bodies/moon/loaders.py`
- Create: `src/sopran/bodies/moon/svm.py`
- Delete: `src/sopran/bodies/moon.py`

- [ ] Move `Moon` and `SurfaceEndpoint` to `api.py`.
- [ ] Move `SurfacePlan` and `SurfaceSource` to `models.py`.
- [ ] Move source tables and source aliases to `sources.py`.
- [ ] Move schema to `schema.py`.
- [ ] Move parameter normalization to `parameters.py`.
- [ ] Move guide/example/acquisition markdown to `guides.py`.
- [ ] Move surface path/download helpers to `loaders.py`.
- [ ] Move Tsunakawa SVM readers to `svm.py`.
- [ ] Re-export public names from `moon/__init__.py`.

### Task 3: Raster Cleanup

**Files:**
- Modify: `src/sopran/maps/raster.py`

- [ ] Remove Tsunakawa-specific readers from generic raster module.
- [ ] Keep `RasterLayer`, `RasterSpec`, and `read_geotiff` in `sopran.maps.raster`.
- [ ] Keep `spn.RasterLayer`, `spn.RasterSpec`, and `spn.Region` unchanged.

### Task 4: Verification

**Files:**
- Modify only if needed: docs and tests that reference old internal paths.

- [ ] Run `python -m pytest tests/test_moon_surface.py tests/test_maps.py -q`.
- [ ] Run `python -m pytest -q`.
- [ ] Run `python -m ruff check .`.
- [ ] Run `python -m mypy src`.
- [ ] Run `python -m compileall src`.
