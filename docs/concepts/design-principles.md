# データの意味が分かるAPI

SOPRANは、データに詳しくない人でも使ううちに構造と意味を理解でき、可視化まで進め、
必要になれば元データへ直接戻れる構成を目指します。

## 名前と階層を観測に対応させる

`spn.kaguya.esa1.energy_flux`はミッション、機器、物理量を表します。
型・補完・`info()`、単位、座標系、時間・energy・lookビンもこの構造に揃えます。
ファイル形式やRustの都合を、物理量の名前に混ぜません。

## 標準の入口から可視化まで進む

```python
import sopran as spn

time = spn.day("2008-04-26")
plot = spn.kaguya.esa1.energy_flux.plot(time, calibration="auto")
```

設定に従って取得・校正・保存・再読込を行い、軸・色・単位のある図へつなぎます。
期間や座標系を共通にする場合は`spn.view(...)`を使います。
自動化しても補正条件・出典・欠測は隠さず、ゼロ計数と未観測を区別します。

## 元ファイルとnative観測を残す

```python
mission = spn.Kaguya()
data = mission.esa1.load(time)
source_files = data.files
native = data.pace
```

`files`は出典ファイル、`pace`は元のheaders・record配列を持つ読込結果です。
`pace`は入力がない場合には`None`です。再ビン・時間積分・校正後の配列と区別します。
直接ファイルを指定する場合は`missions.kaguya.read_pace_pbf(files)`も使えます。

## 実装は隠し、試作は明示する

重い処理は配列単位でPyO3/Rustへ渡し、通常のPythonデータ型で返します。
日常APIでFFIを意識させず、backendの選択情報は再現性のために保持します。

未確定モデルは[experimental](../experimental/index.md)へ隔離し、通常APIから依存しません。
個別のrunや研究報告は`working/`に分け、公開APIの説明とは切り離します。
