# 試作API

`sopran.experimental`は、研究中のモデルや解析手順のうち、別のデータでも試せる程度に整理したものを置く名前空間です。
通常の機器APIと違い、名前・既定値・保存形式は予告なく変わったり削除されたりします。結果の物理的な正しさも保証しません。

```bash
python -m pip install -e ".[kaguya,viz,experimental]"
```

`import sopran`だけでは試作を読み込みません。使うモジュールを明示してimportします。

## 一覧

| 対象 | モジュール | ページ |
|---|---|---|
| 電子反射法（ER）の推定モデル | `sopran.experimental.electron_reflection` | [電子反射法](er.md)、[ERモデルの定義](er-models.md) |
| KAGUYAのER入力の準備と推定の呼び出し | `sopran.experimental.kaguya.er.KaguyaErInstrument` | [電子反射法](er.md) |
| ER入力の部品（16秒窓、ペア分布、SVM3Dによる接続判定） | `sopran.experimental.kaguya.er_windows`、`electron_reflection.maps`、`moon.connection` | [ER全期間バッチ](er-batch.md) |
| ERの全期間バッチ（日別シャード、Slurm） | `python -m sopran.experimental.kaguya.er_batch` | [ER全期間バッチ](er-batch.md) |
| Tsunakawa SVM3Dの殻格子と磁力線追跡 | `sopran.experimental.moon.svm3d` | — |
| 波動候補の検出・リッジ追跡・クラスタリング | `sopran.experimental.waves` | [波動候補の抽出](waves.md) |
| KAGUYA WFCの検出プリセットと品質マスク | `sopran.experimental.kaguya.waves` | [波動候補の抽出](waves.md) |
| dHT座標系へ移したピッチ角分布 | `sopran.experimental.kaguya.dht` | [dHT座標系](dht.md) |
| 衛星電位の代理量、PACE低レベル表 | `sopran.experimental.kaguya.spacecraft_potential`、`kaguya.pace_lowlevel` | [衛星電位の代理量](spacecraft-potential.md) |
| 比較用のmirror transmission推定器 | `sopran.experimental.electron_reflection.mirror_transmission` | [ERモデルの定義](er-models.md) |
| テスト粒子軌道、閉じた磁力線の島、磁場残差、環境応答の回帰 | `sopran.experimental.moon.test_particle`、`moon.closure`、`kaguya.field_residual`、`statistics.ridge` | [磁場モデルと軌道](field-models.md) |

## 通常APIとの境界

PACE・LMAG・LRSの取得、校正、元の観測ビン、座標変換、Store、PlotStack、月面マップは通常の入口に残します。
ERの推定結果は機器の観測量ではないため、`spn.kaguya.er`のような入口は作りません。ERの型や関数を`spn`の直下にも出しません。

依存の向きは試作から通常APIへの一方向です。通常APIは試作をimportせず、この境界はテスト
（`tests/test_experimental_boundary.py`）で確かめています。試作の結果をStoreに保存するときは、
`experimental.`で始まるデータセットIDを使い、通常のプロダクトと混ぜません。

以前`sopran.analysis.electron_reflection`、`sopran.analysis.waves`、`sopran.missions.kaguya.er*`、
`sopran.bodies.moon.svm3d`にあった試作は上の場所へ移しました。古い名前の別名は残していません。

## 正式化・継続・廃止の判断

各試作の目的、未確定の点、正式なAPIへ移す条件、最後に確認した日付は、ソースの
`src/sopran/experimental/README.md`で管理しています。リリースの前に棚卸しし、正式化するものは
型・単位・出典・回帰テスト・検証の範囲をそろえて通常APIへ移します。

特定の期間を対象にした計算、比較の図、結果の考察、文献調査は、公開ドキュメントではなく各研究の作業ディレクトリ
（`working/`）に記録します。このセクションは試作APIの使い方と限界だけを扱います。
