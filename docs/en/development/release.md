# Release

SOPRAN is published to PyPI from GitHub Actions with Trusted Publishing; no long-lived API tokens are used.

| Item | Value |
|---|---|
| Workflow | `.github/workflows/publish.yml` |
| Trigger | Pushing a `v*` tag |
| PyPI project | `sopran` |
| GitHub environment | `pypi` |
| Authentication | GitHub OIDC and PyPI Trusted Publisher |

## What the workflow does

1. Checks that `version` in `pyproject.toml`, `__version__` in `src/sopran/__init__.py`, and the tag without `v` agree.
2. Builds the source distribution with `python -m build --sdist`.
3. Builds CPython 3.11–3.14 wheels for Linux, Windows, and macOS with `cibuildwheel`.
4. Checks that `sopran._native` imports from each wheel.
5. Checks metadata and README with `python -m twine check dist/*`.
6. Uploads to PyPI with `pypa/gh-action-pypi-publish@release/v1`.

## Procedure

```powershell
# 1. set version in pyproject.toml and __version__ in src/sopran/__init__.py to the same value (e.g. 0.1.0)

# 2. commit and tag
git add pyproject.toml src/sopran/__init__.py
git commit -m "Release v0.1.0"
git tag v0.1.0

# 3. pushing the tag starts the publish workflow
git push origin main
git push origin v0.1.0
```

If the three versions disagree, the build job fails.
Before each release, review the experiments as described in [Experimental](../experimental/index.md#promote-keep-or-retire).

## Checks beforehand

```powershell
python -m build --sdist --wheel
python -m twine check dist/*

# try building a wheel for the current OS
python -m pip install "cibuildwheel>=2.23,<3"
python -m cibuildwheel --output-dir wheelhouse
```

## First-time PyPI setup

If the `sopran` project does not exist on PyPI yet, create a pending publisher under Publishing in your PyPI account.

| PyPI field | Value |
|---|---|
| Project name | `sopran` |
| Owner | `Nkzono99` |
| Repository name | `sopran` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` |

A pending publisher does not reserve the name. If a project with the same name is registered before the first upload, it becomes invalid.
