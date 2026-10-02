# Experimental APIs

`sopran.experimental`は、別のデータでも試せる研究用モデル・APIを置く名前空間です。
通常の機器APIと異なり、名前・既定値・保存形式の変更や削除に互換性を保証しません。
`import sopran`だけでは試作を読み込みません。

```shell
python -m pip install "sopran[kaguya,viz,experimental]"
```

| 対象 | 入口 |
|---|---|
| ERの推定モデル | `sopran.experimental.electron_reflection` |
| KAGUYAのER入力・2手法への呼出し | `sopran.experimental.kaguya.er.KaguyaErInstrument` |
| 波動候補・ridge・clustering | `sopran.experimental.waves` |
| KAGUYA WFCの候補抽出preset・品質処理 | `sopran.experimental.kaguya.waves` |

- [ERの利用方法と限界](electron-reflectometry.md)
- [ER手法とコードの一覧](er-methods.md)
- [波動候補の利用方法と限界](waves.md)

## 通常APIとの境界

PACE・LMAG・LRSの取得、校正、nativeビン、座標変換、Store、PlotStack、月面productは
従来の入口に残ります。ER候補は観測機器そのものではないため、`spn.kaguya.er`は提供しません。
ERの型やfit関数も`spn`直下には再公開しません。

旧`sopran.analysis.electron_reflection`、`sopran.analysis.waves`、
`sopran.missions.kaguya.er*`の試作は上記へ移動しました。互換aliasはありません。
共有の磁場補間は通常側の`missions.kaguya.magnetic_geometry`にあります。

ERの推定器はfinite-binとHalekasです。結果は型付きのfit結果として返し、
設定とともに呼出し側で保存します。古いStore保存物は通常のdataset読込で参照できます。

## 定期的に正式化・継続・廃止を判断する

各試作の目的、未確定点、正式化条件、最終確認は、ソースの
`src/sopran/experimental/README.md`で管理します。リリース前に棚卸しし、
通常APIへ昇格する場合は型・単位・出典・回帰テスト・検証範囲を揃えます。

個別研究の期間指定run、比較図、結果の考察、文献調査は`working/`に置きます。
試作APIの説明と、研究成果の評価を混ぜません。
