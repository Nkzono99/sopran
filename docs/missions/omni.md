# OMNI

NASA OMNI2の**1時間値**を読み込み、共通の `SopranArray` で可視化・加工できます。
年別ASCIIファイルを不足時にStoreへ自動取得します。既存ERバッチの
`raw/omni/omni2_YYYY.dat` キャッシュもそのまま使用します。

`load()`には`xarray`、可視化には`matplotlib`が必要です。
未導入の場合は `pip install xarray matplotlib` で追加できます。

```python
import sopran as spn

spn.config.use(store="F:/sopran_data", download="missing")
time = spn.day("2008-05-01")

data = spn.omni.load(time)
frame = data.to_dataframe()  # UTC index、scalar変数のpandas DataFrame
dataset = data.to_xarray()   # GSE磁場ベクトルも含むxarray Dataset

result = spn.omni.pressure.plot(time)
result = spn.omni.magnetic_field.plot(time)

# 通常のSOPRAN viewとStore設定を利用
v = spn.view(time=time)
result = v.omni.pressure.plot()

# 設定を独立させる場合
omni = spn.Omni(store=spn.Store("F:/sopran_data"), download="never")
```

## 変数

| 名前 | 単位 | 内容 |
|---|---|---|
| `pressure` | nPa | 公開済み太陽風動圧。密度・速度から再計算しない |
| `speed` | km/s | 太陽風の速さ（scalar） |
| `density`, `temperature` | cm^-3, K | 陽子密度・温度 |
| `magnetic_field` | nT | 平均磁場ベクトル、GSEのx/y/z |
| `b_magnitude` | nT | 磁場強度の平均。平均ベクトルのノルムとは異なる |
| `bx_gse`, `by_gse`, `bz_gse` | nT | GSE成分 |
| `by_gsm`, `bz_gsm` | nT | GSM成分 |
| `beta`, `alfven_mach`, `magnetosonic_mach` | 1 | プラズマbeta、Mach数 |
| `alpha_proton_ratio` | 1 | alpha粒子/陽子の数密度比 |
| `electric_field` | mV/m | 公開の対流電場指標（速度とGSM Bzから計算された値） |
| `kp` | 1 | Kp。原ファイルのKp×10を0.1倍に変換 |
| `dst`, `ae`, `al`, `au` | nT | 地磁気活動指数 |
| `imf_spacecraft_id`, `plasma_spacecraft_id` | 1 | 出典衛星ID |
| `imf_sample_count`, `plasma_sample_count` | 1 | 時間平均の元サンプル数 |

代表的な変数には型付きendpointがあります。すべてのscalar変数に次の形でアクセスできます。

```python
bz = data["bz_gsm"]  # SopranArray
result = spn.omni.variable("alpha_proton_ratio").plot(time)
```

## 観測時刻への対応付け

```python
context = spn.omni.at([
    "2008-05-01T00:10:00Z",
    "2008-05-01T00:59:59Z",
    "2008-05-01T01:00:00Z",
])
```

最初の2時刻は00:00--01:00、最後は01:00--02:00の値に対応します。
順序・重複時刻を保持し、補間・欠損の前方埋めはしません。
`source_time` は対応した元の時間ラベルです。時間レコード自体がなければ `NaT`、
レコードはあっても変数のfill値ならその変数が `NaN` です。
日時にtimezoneがなければUTCとして扱い、`NaT` 入力は拒否します。

`load(start, stop)` は時間ラベルについて半開区間 `[start, stop)` を選択します。
例えば00:30開始なら00:00ラベルは含みません。00:30の上流条件が欲しいときは `at()` を使います。
欠測値は公式の変数別fill値で判別し、欠測時間レコードを勝手に追加しません。

## 取得と制約

- `download="missing"`: 未取得の年だけ取得（既定）。
- `download="never"`: 通信せず、不足時は `FileNotFoundError`。
- `download="always"`: 再取得して更新。進行中の年を更新するときにも使用。
- ダウンロードはtimeout付き・一時ファイル経由。内容と対象年を検証してから置換し、
  失敗時には以前のキャッシュを保持します。新規取得時はStoreのchecksum manifestを記録します。
- 1分・5分OMNI、CDF、全57変数の網羅は未対応です。
- GSE/GSMを明示し、Viewのframe指定だけで他座標へ自動回転しません。
- OMNIは地球近傍の上流条件を表す資料であり、月位置の局所太陽風の直接測定ではありません。
  月への追加時間シフト・磁気圏内外の判定はこのAPIでは行いません。
- 実行中ERバッチの再現性を保つため、既存のER用reader・照合関数・runnerは変更していません。

出典: [NASA OMNI仕様](https://omniweb.gsfc.nasa.gov/html/ow_data.html)、
[NASA SPDF公開ファイル](https://spdf.gsfc.nasa.gov/pub/data/omni/low_res_omni/)。
