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

1. Checks that `src/sopran/__init__.py` `__version__` matches the tag without
   the leading `v`.
2. Builds the sdist and wheel with `python -m build`.
3. Checks metadata and README rendering with `python -m twine check dist/*`.
4. Passes the build artifact to the PyPI publish job.
5. Uploads to PyPI with `pypa/gh-action-pypi-publish@release/v1`.

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
# Set __version__ in src/sopran/__init__.py to a value such as 0.1.0

# 2. Commit and tag
git add src/sopran/__init__.py
git commit -m "Release v0.1.0"
git tag v0.1.0

# 3. Push the tag to start the PyPI publish workflow
git push origin main
git push origin v0.1.0
```

If `__version__ = "0.1.0"` does not match tag `v0.1.0`, the build job fails.

## Local Checks

Before tagging, run:

```powershell
python -m build
python -m twine check dist/*
```

For details, refer to the PyPI Trusted Publishing docs and the Python Packaging
User Guide.
