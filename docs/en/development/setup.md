# Setup And Checks

How to set up an environment for changing SOPRAN code or documentation, and which checks to run afterwards.
For installing as a user, see [Installation](../start/install.md).

## Create the environment

```bash
git clone https://github.com/Nkzono99/sopran.git
cd sopran
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev,full,docs]"     # on Windows use .venv\Scripts\python.exe
```

`pip install -e .` also builds the Rust extension `sopran._native` into the source tree.
After changing only Rust code, rebuild the extension with:

```bash
python -m maturin develop --release
python -c "import sopran._native as native; print(native.__file__)"
```

`sopran-env-check --native` checks the build tools.
`maturin develop` replaces the extension inside the source tree, so when long-running jobs use the same tree,
work in a separate copy with a separate virtual environment.

## Check commands

Run from the repository root with the virtual environment's `python`, choosing the checks relevant to your change.

| Target | Command |
|---|---|
| Related tests / all tests | `python -m pytest -q tests/test_omni.py` / `python -m pytest -q` |
| Syntax, lint, types | `python -m compileall -q src` / `python -m ruff check src tests` / `python -m mypy src` |
| Rust | `cargo test -p sopran-native` / `cargo fmt --all --check` |
| Schema changes | `python -m sopran.schema_docs --check docs/ja/reference/schemas.md` / `python -m sopran.schema_docs --language en --check docs/en/reference/schemas.md` |
| Documentation changes | `python -m mkdocs build --strict` |
| Connection to remote archives | `python -m pytest -m network` / `sopran-env-check --sources` |

Tests rely mostly on synthetic data and fixtures. They do not assume an IDL installation; comparisons with SPEDAS behavior use
reference specifications, synthetic data, and existing real data.

The regular tests never reach the network: `tests/conftest.py` blocks connections to anything but loopback, and download paths are tested by replacing `urlopen` and similar functions.
Tests that do reach remote servers are marked `@pytest.mark.network`. They are deselected by default and run only with `-m network`.

## CI

| Workflow | Contents |
|---|---|
| `.github/workflows/ci.yml` | Installs `[dev,kaguya,moon,viz,docs,experimental]` and runs pytest, compileall, the schema page check, ruff, and mypy |
| `.github/workflows/sources.yml` | Every Monday and on manual dispatch, checks the connection to the remote archives with `sopran-env-check --sources` |
| `.github/workflows/docs.yml` | Builds the documentation with `mkdocs build --strict` and publishes to GitHub Pages from the `main` branch |
| `.github/workflows/publish.yml` | On `v*` tags, builds the sdist and wheels for each OS and CPython 3.11–3.14 and publishes to PyPI ([Release](release.md)) |

## Supercomputers

Environment setup and job templates for the Kyoto University supercomputer are in `scripts/hpc/kyoto/`.
See [ER Full-Period Batch](../experimental/er-batch.md#running-on-the-kyoto-university-supercomputer) for their use.
