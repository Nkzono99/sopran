# Installation

SOPRAN is currently intended to be used from a source checkout.

```bash
git clone https://github.com/Nkzono99/sopran.git
cd sopran
pip install -e .
```

For documentation work, install only the docs toolchain when heavy scientific
runtime dependencies are not needed:

```bash
pip install mkdocs mkdocs-material "mkdocstrings[python]" pymdown-extensions numpy
set PYTHONPATH=src
mkdocs serve
```

The package also defines a `docs` extra:

```bash
pip install -e ".[docs]"
```

On Windows this can still try to build runtime scientific packages when normal
package dependencies are not already installed. The direct docs-toolchain install
above is the lighter local path for editing pages.
