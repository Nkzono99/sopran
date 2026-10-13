# Moving A Store

Sending inputs from a workstation to a supercomputer, or bringing results back, only takes copying Store files with `rsync`
and rebuilding the indexes. This page gives the procedure and the rules that make it work.

## Procedure

```bash
# on the source: list the files to send
sopran-store --data-root /path/to/sopran_data sync-list > files.txt

# transfer
rsync -av --delay-updates --files-from=files.txt /path/to/sopran_data/ host:/data/sopran_data/

# on the destination: rebuild indexes and check for missing or corrupt files
ssh host sopran-store --data-root /data/sopran_data rebuild
ssh host sopran-store --data-root /data/sopran_data verify
```

`--delay-updates` makes rsync put all transferred files in place at the end,
so another job reading the Store during the transfer never sees half-written files.

## Choosing what to send

By default `sync-list` lists only datasets that SOPRAN creates and reuses by itself (`managed=True`):
caches of orbit geometry, field-line connection, LRS, and pitch-angle spectra, and data availability summaries.

```bash
# select dataset IDs or ID prefixes (included even when not managed)
sopran-store --data-root /path/to/sopran_data sync-list \
  --dataset experimental.kaguya.er.paired_distributions > files.txt

# add part of the raw files
sopran-store --data-root /path/to/sopran_data sync-list --raw spice > files.txt
```

`--layer` and `--variant` narrow by layer and conditions. `--all` includes every dataset, including work in progress.

## Why it works

The Store keeps the following rules, so it works as the same datasets even under a different root path.

- **References are relative to the root.** Manifests and catalogs never contain absolute paths. Files outside the Store are recorded
  only as a checksum and a hint of where they came from; they are never used for lookup.
- **Cache IDs come from content.** `variant_id` is derived from settings and inputs (source file checksums, SPICE kernel names, hashes, and sizes).
  The same processing gets the same ID on every machine, so transferred results are reused as is.
- **Shard sidecars are the source of truth.** Each shard is written to a temporary file and renamed, with `<shard>.sopran.json` next to it.
  `catalog.parquet` is an index that can be rebuilt from the sidecars. When other machines or jobs write different shards of the same dataset,
  a `rebuild` after the transfer merges them.
- **Machine-local files stay local.** `registry/`, `cache/`, dataset `work/` directories, `*.sopran-tmp*`, and `*.sopran-bak*` are never synchronized.
  `registry/` is rebuilt automatically when manifests change.
  `sopran-store excludes` prints the patterns for `rsync --exclude-from`.

`rebuild` also creates sidecars for older datasets that lack them (migration).

## From Python

| Command | Python |
|---|---|
| `rebuild` | `store.rebuild()`, `record.rebuild_catalog()` |
| `verify` | `record.verify_shards()` |
| Reference a file outside the Store | `store.file_reference(path)` |

Command options are listed in [Command Line](../reference/cli.md).
