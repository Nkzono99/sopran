# Release

SOPRAN publishes to PyPI through PyPI Trusted Publishing. It does not use a
long-lived API token.

## Workflow

| Item | Value |
| --- | --- |
| GitHub workflow | `.github/workflows/publish.yml` |
| Trigger | `v*` tag push |
| PyPI project | `sopran` |
| GitHub environment | `pypi` |
| Authentication | GitHub OIDC / PyPI Trusted Publisher |

The `publish` workflow does the following.

1. Checks that `pyproject.toml` project version,
   `src/sopran/__init__.py` `__version__`, and the tag without the leading `v`
   all match.
2. Builds the source distribution with `python -m build --sdist`.
3. Builds Linux, Windows, and macOS CPython 3.11-3.14 wheels with
   `cibuildwheel`.
4. Runs an import smoke test for `sopran._native` in each wheel.
5. Checks metadata and README rendering with `python -m twine check dist/*`.
6. Passes the build artifacts to the PyPI publish job.
7. Uploads to PyPI with `pypa/gh-action-pypi-publish@release/v1`.

## One-time PyPI Setup

If the `sopran` project does not exist on PyPI yet, create a pending publisher
from the Publishing page in your PyPI account.

| PyPI form | Value |
| --- | --- |
| Project name | `sopran` |
| Owner | `Nkzono99` |
| Repository name | `sopran` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` |

A pending publisher does not reserve the project name. If another user registers
the same project name before the first publish, the pending publisher becomes
invalid.

## Release Steps

```powershell
# 1. Bump the version
# Set pyproject.toml version and src/sopran/__init__.py __version__
# to the same value, such as 0.1.0

# 2. Commit and tag
git add pyproject.toml src/sopran/__init__.py
git commit -m "Release v0.1.0"
git tag v0.1.0

# 3. Push the tag to start the PyPI publish workflow
git push origin main
git push origin v0.1.0
```

If `version = "0.1.0"` in `pyproject.toml`, `__version__ = "0.1.0"`, and tag
`v0.1.0` do not match, the build job fails.

## Local Checks

Before tagging, run:

```powershell
python -m build --sdist --wheel
python -m twine check dist/*
```

To check platform wheel building locally for the current OS, run:

```powershell
python -m pip install "cibuildwheel>=2.23,<3"
python -m cibuildwheel --output-dir wheelhouse
```

For details, refer to the PyPI Trusted Publishing docs and the Python Packaging
User Guide.
