# KAGUYA ESA1 を読む

## 前提

- `Store` root が決まっている
- KAGUYA PDS3 raw file がある、または download policy を許可している
- 時刻範囲は半開区間 `[start, stop)` で考える

```python
import sopran as spn

store = spn.Store("F:/sopran_data")
kg = spn.Kaguya(store=store)
time = spn.day("2008-01-01")
```

## 1. 予定を確認

```python
kg.esa1.counts.plan(time)
kg.esa1.select("2008-01-01").remote_files()
```

## 2. 読み込む

```python
counts = kg.esa1.counts.load(time)
array = counts.to_xarray()
table = counts.to_polars()
```

## 3. 図にする

```python
counts.quicklook("kaguya_esa1_counts", root="reports", y="energy", log_color=True)
```

## download policy

```python
kg = spn.Kaguya(store=store, download="missing")
kg.esa1.counts.load(time)
```

`download="never"` は offline 解析向けです。raw file がない場合の詳細な挙動は
[実装状況](../reference/status.md) を参照してください。
