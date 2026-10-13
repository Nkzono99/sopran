# Command Line

Installing SOPRAN provides the following commands. Each can also be called as `python -m <module>`.

| Command | Module | Purpose |
|---|---|---|
| `sopran-store` | `sopran.core.sync` | Synchronize, verify, and rebuild Store indexes |
| `sopran-env-check` | `sopran.env_check` | Check the environment for building from source and the connection to remote data archives |
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
sopran-env-check [--native] [--sources] [--timeout SECONDS]
```

Checks the prerequisites for installing from source. `--native` checks the Rust toolchain for building the extension `sopran._native`
and, on Windows, the MSVC build tools.

`--sources` asks each remote archive SOPRAN downloads from (JAXA DARTS, the Kyoto University PACE calibration tables, NASA NAIF, NASA SPDF, USGS)
for one known file. URLs are built by the same functions the loaders use, and only headers are requested, so nothing is downloaded or written to the Store.
Archives are checked in parallel, and server errors and timeouts are retried twice, 5 seconds apart. `--timeout` is the number of seconds to wait for each request (default 60).

| Label | Meaning | Next step |
|---|---|---|
| `OK` | The file was reached. A redirect also shows the new location | None |
| `MISSING` | The archive answered but the file is gone (404, 410) | The archive has most likely moved or reorganized. Check the provider's site and fix the URL in SOPRAN |
| `UNAVAILABLE` | Server error (5xx, 429), timeout, or failed connection | Usually temporary. Retry later; if it persists, check this machine's network |
| `ERROR` | Access was refused (403 and similar) | Check access restrictions and proxies |

The command exits non-zero unless every archive is `OK`. On machines that may not reach the internet, such as compute nodes,
run it before starting a long retrieval. If there is no connection, set `SOPRAN_OFFLINE=1` ([Configuration](../guide/configuration.md)).

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
