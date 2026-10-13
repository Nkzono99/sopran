# Command Line

Installing SOPRAN provides the following commands. Each can also be called as `python -m <module>`.

| Command | Module | Purpose |
|---|---|---|
| `sopran-store` | `sopran.core.sync` | Synchronize, verify, and rebuild Store indexes |
| `sopran-env-check` | `sopran.env_check` | Check the environment for building from source |
| `sopran-schema-docs` | `sopran.schema_docs` | Generate the schema reference |
| — | `sopran.experimental.kaguya.er_batch` | ER full-period batch ([ER Full-Period Batch](../experimental/er-batch.md)) |

## sopran-store

```text
sopran-store [--data-root DATA_ROOT] {sync-list,verify,rebuild,excludes} ...
```

Without `--data-root`, the Store from [Configuration](../guide/configuration.md) is used.

| Subcommand | Action | Options |
|---|---|---|
| `sync-list` | Print files for `rsync --files-from`; by default only `managed` datasets | `--dataset ID` (ID or prefix), `--layer`, `--variant`, `--all` (include unmanaged), `--raw PREFIX` (add a `raw/` subpath) |
| `verify` | Check shards against catalogs and sidecars | `--dataset`, `--layer`, `--variant`, `--all` |
| `rebuild` | Rebuild catalogs and indexes from sidecars; creates sidecars for older datasets | `--layer` |
| `excludes` | Print patterns of files that are not synchronized (for `rsync --exclude-from`) | |

See [Moving A Store](../guide/store-sync.md) for an example procedure.

## sopran-env-check

```text
sopran-env-check [--native]
```

Checks the prerequisites for installing from source. `--native` checks the Rust toolchain for building the extension `sopran._native`
and, on Windows, the MSVC build tools.

## sopran-schema-docs

```text
sopran-schema-docs [--check] [--language {ja,en}] [path]
```

Generates the [Schemas](schemas.md) page from the schema definitions in code. `path` defaults to `docs/ja/reference/schemas.md`.
`--check` writes nothing and exits non-zero when the file is out of date (used in CI).

```bash
python -m sopran.schema_docs docs/ja/reference/schemas.md
python -m sopran.schema_docs --language en docs/en/reference/schemas.md
```
