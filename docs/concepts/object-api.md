# オブジェクト API

SOPRAN はグローバル状態ではなく、オブジェクトをたどってデータに到達します。

```python
kg = spn.Kaguya()
kg.esa1.counts
kg.lmag.magnetic_field

art = spn.Artemis()
art.p1.fgm.magnetic_field
```

属性アクセスだけでは download、decode、scan、plot は行いません。実行は明示的な
メソッドで始まります。

| メソッド | 役割 |
| --- | --- |
| `info()` | 変数名、単位、次に試す呼び出しを短く表示する |
| `plan(time)` | 必要なファイル、dataset ID、実行意図を確認する |
| `load(time)` | typed data object を読み込む |
| `plot(time)` | 単純な load-and-plot を行う |
| `schema()` | dimensions、units、aliases を見る |
| `guide(language=...)` | notebook や terminal で読める Markdown guide を返す |
| `example()` | その場で試せる短いコード例を返す |

## 読み込んだ後

`load()` が返す `SopranArray` は、xarray と table の両方へ渡せます。

```python
counts = kg.esa1.counts.load(time)
counts.info()
counts.to_xarray()
counts.to_polars()
counts.to_pandas()
```

3 次元以上の dense array は、既定では `time` ごとに 1 行を作り、値を `pl.Array`
列として保持します。完全に展開した table が必要な場合は `layout="long"` を明示します。

簡単な xarray 操作は `SopranArray` として戻るため、schema と provenance を保てます。

```python
channel_band = counts.isel(energy=slice(4, 12)).mean("energy")
channel_band.quicklook("counts_channel_band")
channel_band.metadata["operations"]
```

## 言語

Guide は日本語を既定にし、必要なときだけ English を選びます。

```python
kg.guide()
kg.guide(language="en")
kg.esa1.counts.guide().language_switcher()
```

公開ドキュメントも同じラベル `Lang: 日本語/English` を使います。
