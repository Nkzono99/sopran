# 電子反射法の試作API

ERは電子のenergy-pitch分布から反射障壁を推定する試作です。
数値的なfit成功を、月面磁場の測定成功と同一視しません。
現在のモデルを正式な磁場推定法として保証するものではありません。

## 機器の読込と解析を分ける

```python
import sopran as spn
from sopran.experimental.kaguya.er import KaguyaErInstrument

mission = spn.Kaguya()
er = KaguyaErInstrument(mission)
result = er.effective_field.fit_timeseries(
    spn.day("2008-04-26"),
    integration="16s",
    workers=3,
)
result.plot(y="effective_field")
```

この例は16秒窓のglobal-jointモデルを使います。Halekasの二値分布fitとは別モデルです。
取得・校正には`kaguya` extra、表示には`viz`、推定には`experimental`を入れてください。
計算時間と必要な入力は観測期間によって変わります。

入力のpitchスペクトルを既に持っている場合は、同じadapterの
`effective_field.fit(pitch_counts, b_sc_nT=..., affected_side=...)`で直接推定できます。
独立した配列を使う場合はモデルを明示importします。

```python
from sopran.experimental.electron_reflection import (
    ElectronReflectionCounts,
    HalekasFitSettings,
    fit_halekas_distribution,
)
```

## 出力の意味

| 量 | 意味 |
|---|---|
| `mirror_ratio` | $R_m=B_{\mathrm{eff}}/B_{sc}$ |
| `effective_field` | モデル上の実効反射磁場。単位nT。月面磁場ベクトルではない |
| `delta_u_eff` | モデル上の有効電位エネルギー項。単位eV。独立検証なしに絶対月面電位と呼ばない |
| モデル・品質・境界フラグ | モデル選択、support、制約端など。推定値と併せて読む |

$R_m\le1$や制約端の解を、地殻磁場の直接測定値として使わないでください。
モデルごとに目的関数、beam、有限応答、品質判定が異なります。設定と入力を保存し、
異なるモデルの「成功」を同じ判定として集計しないことが必要です。

既定キーは`experimental.kaguya.er.effective_field`と
`experimental.kaguya.er.global_joint_effective_field`です。
通常のschema一覧には含めず、試作schemaは`experimental.kaguya.schema`に置きます。

::: sopran.experimental.kaguya.er.KaguyaErInstrument
