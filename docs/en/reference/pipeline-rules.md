# Pipeline Rules

Pipeline calls have side effects, so execution rules are explicit.

## Execution Mode

| Mode | Rule |
| --- | --- |
| default | Avoid accidental overwrite |
| `append` | Add shards |
| `replace` | Explicitly replace existing output |
| `resume=True` | Reuse completed output |
| `only_failed=True` | Replay failed shards |

## Download Policy

| Policy | Meaning |
| --- | --- |
| `never` | Use local files only |
| `missing` | Fetch missing files |
| `always` | Try fetching every time |

When `SOPRAN_OFFLINE` is truthy, the default policy is `never`.

## Provenance

Pipeline datasets preserve at least this provenance shape.

```json
{
  "provenance": {
    "source": "kaguya.esa1",
    "stages": ["decode", "select", "write"],
    "time_range": {"start": "...", "stop": "..."},
    "download": "never"
  }
}
```

Backend coverage is tracked in [Status](status.md).
