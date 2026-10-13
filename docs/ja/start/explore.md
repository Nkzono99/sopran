# データの構造をたどる

前のページでは`spn.kaguya.esa1.energy_flux`を直接呼びました。このページでは、知らないデータに出会ったときに
どの変数があり、読むと何が返るかを、データを読む前に確かめる方法を扱います。

## 属性をたどってもファイルは読まない

`spn.kaguya`、`spn.kaguya.esa1`、`spn.kaguya.esa1.energy_flux`は、どれもデータの場所を表すオブジェクトです。
属性を取り出しただけでは、ダウンロード・デコード・計算は起きません。
実際の処理は`load()`、`plot()`、`compute()`などのメソッドを呼んだときに始まります。

```python
import sopran as spn

kg = spn.kaguya          # ミッション
kg.esa1                  # 機器
kg.esa1.energy_flux      # 物理量（エンドポイント）
```

変数を表す末端のオブジェクトを、このドキュメントでは**エンドポイント**と呼びます。

## 読む前に確かめる

どの階層でも`info()`で短い説明を表示できます。エンドポイントでは、さらに次のメソッドが使えます。

```python
ep = spn.kaguya.esa1.energy_flux
time = spn.day("2008-02-01")

ep.info()       # 説明、次元、単位、別名
ep.schema()     # 次元・単位・座標系の機械可読な定義
ep.plan(time)   # 読み込みに必要な元ファイルの一覧
ep.guide()      # 機器の詳しい説明（Markdown）。英語版は guide(language="en")
ep.example()    # その場で試せるコード例
```

`info()`の出力は次のようになります。

```text
KAGUYA.ESA1.energy_flux
description: KAGUYA PACE ESA1 differential electron energy flux derived from counts with PACE INFO calibration tables.
dims: ('time', 'energy', 'look')
units: eV/(cm^2 s sr eV)
aliases: eflux, differential_energy_flux
example: kg.esa1.energy_flux.load(time)
```

`dims`は配列の次元です。PACEの`look`は検出器の視線方向の番号で、方向そのものではありません。
`aliases`は同じ変数の別名で、`kg.esa1.eflux`でも同じエンドポイントに届きます。
全変数の次元と単位は[スキーマ](../reference/schemas.md)に一覧があります。

## 読み込むと何が返るか

エンドポイントの`load()`は、変数1つ分の`SopranArray`を返します。
機器の`load()`は、同じ時刻に測った複数の変数をまとめたオブジェクトを返します。

```python
flux = spn.kaguya.esa1.energy_flux.load(time)   # SopranArray
esa1 = spn.kaguya.esa1.load(time)               # 機器単位の読み込み結果

esa1.counts          # SopranArray
esa1.energy_flux     # SopranArray
esa1.to_xarray()     # 全変数を持つ xarray.Dataset
```

`SopranArray`は、用途に合わせて別のライブラリの型へ変換できます。

| 使いたいもの | 呼び出し |
|---|---|
| xarray | `flux.to_xarray()`、または`flux.xr`で中身の`DataArray`を直接 |
| Polars | `flux.to_polars()` |
| pandas | `flux.to_pandas()` |

3次元以上の配列をPolarsへ変換すると、既定では時刻ごとに1行を作り、残りの次元を配列型の列に入れます。
全次元を展開した縦長の表が必要なときは`layout="long"`を指定します。
詳しくは[読み込んだ配列を扱う](../guide/arrays.md)を参照してください。

## 元ファイルと元の観測ビンへ戻る

校正やビンの組み直しを経た値だけでは、解析の妥当性を確かめられないことがあります。
SOPRANの読み込み結果は、出典の元ファイルと、デコード直後の記録を保持しています。

```python
esa1.files           # 読み込んだ元ファイルのパス
esa1.pace            # デコード直後のヘッダーと記録の配列（ファイルが無ければ None）
```

元ファイルを直接デコードしたいときは、`sopran.missions.kaguya.read_pace_pbf(files)`を使います。

## 文字列のIDから読む

スクリプトやバッチ処理では、属性のパスを文字列で渡すこともできます。

```python
counts = spn.load("kaguya.esa1.counts", time)   # spn.kaguya.esa1.counts.load(time) と同じ
```

IDの先頭には登録済みのデータ源（`kaguya`、`artemis`、`omni`、`moon`）を書きます。

## 次に読む

同じ期間を何度も指定するのが面倒になったら、[解析条件を残す](reproducible.md)へ進んでください。
