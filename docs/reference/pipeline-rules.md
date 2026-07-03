# Pipeline rules（実行規則）

Pipeline は副作用のある処理なので、実行規則を明示します。

## 実行 mode

| mode | 規則 |
| --- | --- |
| default | 既存 dataset を不用意に壊さない |
| `append` | shard を追加する |
| `replace` | 明示的に既存出力を置き換える |
| `resume=True` | 完了済み出力を再利用する |
| `only_failed=True` | 失敗 shard の再実行を意図する |

## download policy

| policy | 意味 |
| --- | --- |
| `never` | local file だけを使う |
| `missing` | 見つからない file だけ取得する |
| `always` | 毎回取得を試みる |

既定 policy は `missing` です。`SOPRAN_OFFLINE` が truthy の場合、既定 policy は
`never` です。`SOPRAN_DOWNLOAD_MODE` を設定すると既定 policy を上書きできます。

## provenance

Pipeline が Store に書く dataset は、少なくとも次を manifest に残します。

```json
{
  "provenance": {
    "source": "kaguya.esa1",
    "stages": ["decode", "select", "write"],
    "time_range": {"start": "...", "stop": "..."},
    "download": "missing"
  }
}
```

Backend ごとの対応状況は [実装状況](status.md) を参照してください。
