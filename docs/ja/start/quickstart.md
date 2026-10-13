# 最初の図を描く

KAGUYAのPACE ESA1が2008年2月29日に測った電子のエネルギーフラックスを、取得から作図まで通して扱います。
ネットワークに接続できる環境と、[インストール](install.md)で`[kaguya,viz]`以上を入れたPython環境を前提にします。

## 1. 保存先を決める

SOPRANは、取得した元ファイルや作った中間データを**Store**と呼ぶ1つのディレクトリにまとめます。
まずセッションの既定のStoreを決めます。

```python
import sopran as spn

spn.config.use(store="/path/to/sopran_data")
```

この設定はPythonプロセスの中だけで有効です。毎回書かずに済ませる方法は[設定](../guide/configuration.md)にあります。

## 2. 期間を作る

```python
time = spn.day("2008-02-29")
```

`spn.day`は2008-02-29 00:00から翌日00:00までの期間を返します。終わりの時刻は含みません（半開区間）。
`spn.period(start, stop)`、`spn.month("2008-02")`、`spn.year("2008")`でも期間を作れます。

## 3. 図にする

```python
result = spn.kaguya.esa1.energy_flux.plot(time)
result.fig
```

このとき、SOPRANは次の処理を順に行います。

1. その日のPACE ESA1の元ファイルがStoreに無ければ、JAXA DARTSの公開アーカイブから取得して`raw/`に保存する。
2. ファイルをデコードし、カウントを`time × energy × look`の配列にする。
3. PACEの校正テーブル（INFO）を取得し、カウントをエネルギーフラックスへ換算する。
4. 時刻を横軸、エネルギーを縦軸、フラックスを色にしたスペクトログラムを描く。

![2008年2月29日のKAGUYA PACE ESA1の電子エネルギーフラックス。約2時間の周回ごとに昼側と夜側で強度が変わり、観測の無い時間は白く抜けている](../../assets/images/quickstart-esa1-energy-flux.png)

縦軸とカラーバーは対数表示が既定で、カラーバーには`energy_flux [eV/(cm^2 s sr eV)]`のように
変数名と単位が出ます。表示範囲は`ylim=(10, 10000)`、`vmin=1e6`、`vmax=1e9`のように指定できます。
2回目からは元ファイルと校正テーブルをStoreから読むので、ネットワークには接続しません。

## 4. 配列として読む

解析では`load()`で配列を受け取ります。

```python
flux = spn.kaguya.esa1.energy_flux.load(time)
flux.info()          # 次元・単位・出典ファイルの要約
flux.to_xarray()     # xarray.DataArray
flux.files           # 読み込んだ元ファイル
```

返り値の`SopranArray`は、xarrayの配列に単位・座標系・出典・処理履歴を付けたものです。
`flux.plot()`で同じ図を描けるほか、`sel`や`mean`で切り出した結果も同じ型のまま扱えます。

## 5. 図を保存する

```python
flux.quicklook("esa1_energy_flux_20080229", root="reports")
```

`reports/`にPNGと、期間・パネルの種類・軸とカラーバーのラベル（単位を含む）を記録したJSONが保存されます。
`formats=("png", "html")`を渡すと、画像と記録を1枚にまとめたHTMLも作ります。

## 次に読む

- 他にどんな変数があり、読む前に何を確認できるかは[データの構造をたどる](explore.md)へ。
- 期間や領域を固定して繰り返し解析するなら[解析条件を残す](reproducible.md)へ。
- PACEの校正方法と注意点は[PACE](../data/kaguya/pace.md)にあります。
