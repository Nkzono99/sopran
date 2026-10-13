# Writing Documentation

How the public documentation is organized and the rules for writing it. When adding or changing a page, decide where it belongs here first.

## Readers and structure

The documentation serves three kinds of readers.

| Reader | Needs | Mainly reads |
|---|---|---|
| Analysts (primary readers) | How to load data and make figures; what the data means and its caveats | Getting Started, User Guide, Data |
| Researchers using experiments | Definitions of research models; how to run full-period computations | Experimental |
| Contributors | Design criteria, extension steps, checks, and releases | Development |

Each section has a defined scope.

| Section | Contains | Does not contain |
|---|---|---|
| Getting Started | Four pages read in order by newcomers, showing the minimal steps of one workflow | Exhaustive options (link to the User Guide) |
| User Guide | How each feature works and how to use it, one topic per page | Instrument-specific details (go to Data) |
| Data | Variables, units, frames, sources, calibration, quality, and limitations per data source | Instrument-independent features (go to the User Guide) |
| Experimental | Usage, model definitions, and limits of experiments | Results of specific runs, comparison figures, interpretations (go to `working/`) |
| Reference | Tables to look up: API, schemas, file formats, CLI, terms | Procedures or history |
| Development | Design criteria and procedures for extending, checking, and releasing | User-facing usage |

## One topic, one page

When the same explanation appears on several pages, one gets updated and the others drift. Decide one page that owns each topic,
and link to it from elsewhere. For example, Store layers are described only in [Storing Data](../guide/store.md),
and configuration precedence only in [Configuration](../guide/configuration.md).
Getting Started repeats a little to show the flow, but leaves details to the User Guide.

Implementation status follows the same rule and sits next to the feature: support per data source is in the table of the [data overview](../data/index.md),
unimplemented points in each page's "Limitations" section, and plans and ideas in [Design Principles](design.md#planned-work). There is no separate "status" page.

## Page templates

**Data pages** follow this order so readers find the same information in the same place across instruments:

1. What was measured and which data it is (one or two sentences), with the shortest code example
2. Variables (entry point, dimensions, units, frame, meaning)
3. Loading and plotting examples
4. Retrieving and placing source files
5. Calibration, missing values, and quality
6. Limitations (unimplemented or unverified points)
7. Sources

**User Guide pages** state the question they answer in the first one or two sentences, then alternate explanation and procedure.
Argument lists go in tables.

## Style

- The Japanese pages use the polite form (です・ます) and lead with the conclusion. Headings are short sentences or noun phrases that tell what follows.
- Terms follow the [Glossary](../reference/glossary.md). API names, external specification names, and file names stay in their original form in `code`;
  in Japanese text, no space is inserted around them.
- Math uses `$...$` and `$$...$$`; units use the same notation as the schemas, such as `nT` and `eV/(cm^2 s sr eV)`.
- Do not repeat generic caveats; state limitations and unverified points that affect decisions, concretely and next to the explanation they concern.
- Only include code examples checked against the implementation. Define illustrative variables such as `time` once per page.
- Embed figures with Markdown, made from real data and stored under `docs/assets/`.

## Japanese and English

The Japanese pages (`docs/ja/`) are primary, and the English pages (`docs/en/`) mirror them at the same paths.
The build uses `mkdocs-static-i18n`, writing Japanese at the site root and English under `/en/`.
Navigation titles are written in Japanese in the `nav` of `mkdocs.yml`, and their English titles in `nav_translations`.
A missing English page falls back to the Japanese one, but `tests/test_docs_build.py` checks that every page has an English version.

The `Lang: 日本語/English` switch at the top right is `docs/overrides/partials/alternate.html`, which moves to the page at the same path in the other language.

## Generated pages

| Page | Generated from | Update |
|---|---|---|
| [Schemas](../reference/schemas.md) | `InstrumentSchema` in code | `python -m sopran.schema_docs docs/ja/reference/schemas.md` (English with `--language en`) |
| [Python API](../reference/api.md) | Docstrings (mkdocstrings) | Automatic at build time; the page lists the classes and functions to include |

## URLs referenced from code

Descriptions returned by `guide()` contain public documentation URLs. `sopran.core.pages.public_doc_urls("data/kaguya/")`
builds both the Japanese and English URLs from a page path.
When moving pages, update these constants and tests such as `tests/test_docs_build.py`.

| Constant | Location |
|---|---|
| `_PUBLIC_DOC_PATHS` | `src/sopran/missions/kaguya/mission.py` |
| `_PUBLIC_DOC_URLS` | `src/sopran/missions/artemis/mission.py` |
| `PUBLIC_DOC_URLS` | `src/sopran/bodies/moon/guides.py` |

## Adding a page

1. Decide where it belongs using the tables above, and check that no page already covers the topic.
2. Create the page at the same path under `docs/ja/` and `docs/en/`.
3. Add the Japanese title to `nav` in `mkdocs.yml` and the English title to `nav_translations`.
4. Link to it from related pages.
5. Confirm with `python -m mkdocs build --strict` that there are no broken links or anchors.
   `mkdocs serve` previews the site (requires `pip install -e ".[docs]"`).
