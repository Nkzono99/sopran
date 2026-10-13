# SOPRAN

SOPRAN（Satellite Observation Package for Retrieval, Analysis, and Navigation）は、
月周辺の衛星観測データを取得・保存・解析・可視化するPythonパッケージです。
KAGUYA/SELENE、ARTEMIS、OMNIの観測値と、月面の地形・磁場・日照マップを同じ書き方で扱えます。

```python
import sopran as spn

spn.config.use(store="/path/to/sopran_data")   # データの保存先
time = spn.day("2008-02-01")

spn.kaguya.esa1.energy_flux.plot(time)          # 取得・校正・作図までを1行で
flux = spn.kaguya.esa1.energy_flux.load(time)   # 解析用の配列として読む
```

`spn.kaguya.esa1.energy_flux`は「KAGUYAのPACE ESA1が測った電子のエネルギーフラックス」を指します。
ミッション、機器、物理量の順に属性をたどると、データの意味と構造が分かるように名前を付けています。
読み込んだ値には単位・座標系・時間とエネルギーのビン・出典ファイルが付いており、
図の軸やカラーバーにもそのまま表示されます。

!!! note "開発段階"
    SOPRANは開発初期（Pre-Alpha）です。公開APIは変わることがあります。
    実装済みの範囲は[データ一覧](data/index.md)の対応表で確認できます。

## 読み方

初めて使う場合は「はじめる」の4ページを順に読んでください。データの取得から、
解析条件を残した図の保存までを一通り試せます。それ以降のページは、必要になったときに引く参照用です。

| 知りたいこと | 読むページ |
|---|---|
| 入れて動かしたい | [インストール](start/install.md) → [最初の図を描く](start/quickstart.md) |
| どんなデータがあり、単位や注意点は何か | [データ一覧](data/index.md)と各ミッションのページ |
| 読み込んだ配列を切り出す・集約する・表に変換する | [読み込んだ配列を扱う](guide/arrays.md) |
| 複数の機器を時間軸をそろえて並べる | [可視化](guide/plotting.md) |
| 同じ期間・領域で何度も解析する、条件を残す | [期間・領域・解析条件](guide/views-cases.md) |
| データの保存先、オフライン利用 | [設定](guide/configuration.md)、[Storeにデータを保存する](guide/store.md) |
| 機械学習や統計のために時刻をそろえる | [時刻をそろえる](guide/alignment.md) |
| 長期間を日別に処理してParquetに保存する | [バッチ処理](guide/pipeline.md) |
| 関数の引数や型 | [Python API](reference/api.md)、[用語集](reference/glossary.md) |
| 電子反射法（ER）や波動候補の試作API | [試作API](experimental/index.md) |
| SOPRANの開発に加わる | [設計方針](development/design.md)、[開発環境と検証](development/setup.md) |

## 対象データ

| 入口 | 主なデータ | 詳細 |
|---|---|---|
| `spn.kaguya` | PACE（電子・イオン）、LMAG（磁場）、LRS（電波・プラズマ波動）、軌道幾何 | [KAGUYA](data/kaguya/index.md) |
| `spn.artemis` | P1/P2のFGM磁場、ESAイオン | [ARTEMIS](data/artemis.md) |
| `spn.omni` | 太陽風・地磁気指数の1時間値と、1分・5分値（HRO・HRO2） | [OMNI](data/omni.md) |
| `spn.moon` | DEM、表面磁場（SVM）、太陽天頂角、影、磁気異常カタログ | [月面マップ](data/moon/index.md) |

## 質問と不具合の報告

使い方の疑問、ドキュメントの誤り、不具合は
[GitHub Issues](https://github.com/Nkzono99/sopran/issues)へ送ってください。
ページ右上の`Lang`で英語版に切り替えられます。
