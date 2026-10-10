# ER手法とコードの一覧

推定器は **finite-binとHalekasの2つ**に整理しました。
主解析にはfinite-binのbeta-binomial count尤度（既定）を使い、D_outをoptionで有効にします。
磁場の採択には`profile_mirror_ratio`の区間と`field_flags`を使います。
fluxだけの入力と旧解析との比較にはHuber 0.1 dex、固定0.1/1との比較にはHalekasを使います。

| 手法・入口 | 入力と目的関数 | モデルと探索 |
|---|---|---|
| `finite_bin.py` / `fit_finite_bin_distribution` | paired countのbeta-binomial（既定）・binomial尤度、またはlog10(a/r)のHuber・二乗損失 | 有限bin、自由bottom/scale、beam 4形状と連続振幅、任意のD_out、loss cone検定。RustのDE＋複数初期値の有界Nelder–Mead |
| `finite_bin.py` / `profile_mirror_ratio` | fit済みの観測 | Rm固定の再最適化。count損失では尤度区間 |
| `halekas.py` / `fit_halekas_distribution` | paired countsのexposure補正後の自然対数比。二乗損失 | 固定backscatter（既定0.1）・外側1。hardのgrid探索、任意のprobit幅とL-BFGS-B |

D_outは `FiniteBinFitSettings(angular_transport="out" / "none")` で選びます。
Halekasのprobitは境界幅のモデル、D_outは角度間の輸送モデルです。
RMSEの比較には単位とmaskを合わせます。HalekasのGaussian BICとHuber値を直接比べません。

## 共通処理と入口

| 場所 | 責務 |
|---|---|
| `electron_reflection/common.py` | `ElectronReflectionCounts`、exposureの検証、境界式 `mirror_boundary_sin2` |
| `electron_reflection/__init__.py` | 2手法と共有型を明示import用に公開 |
| `experimental/kaguya/er.py` | ESA1/ESA2とLMAG・SPICEの共通準備、pitch生成、`paired_counts`、2手法への呼出し |
| `crates/sopran-native/src/finite_bin.rs` | 有限bin応答・D_out・損失・beam振幅・loss cone検定・最適化。PyO3のproblem単位で呼出し |

`er.paired_counts(pitch_counts, index=..., ...)` で共通入力を作ります。
fitは `er.effective_field.fit_finite_bin(observation, ...)` または
`er.effective_field.fit_halekas(counts, ...)` で手法を明示します。
結果はtyped dataclassで返し、設定とともに呼出し側で保存します。
通常のKAGUYA reader、校正、pitch生成、磁場補間、Storeは従来の入口を使います。

## 廃止したもの

旧paired-count beta-binomial推定器（count尤度は2026-10-10にfinite-binの`loss`へ統合）、
binary surface、joint、global-joint、incident/integrated推定器と、
専用のwarm start・尤度scan・beam診断を削除しました。
旧推定器専用の時系列fit・catalog・schema・archive/selection/profile/population評価も
現行パッケージから外しました。OMNIの読込は通常の `spn.omni` を使います。

旧 `sopran-er-finite-bin` JSONL CLIも廃止し、有限binの実装をPyO3 APIへ一本化しました。
過去の研究script・保存データは再現用記録として残ります。旧入口を使うscriptは
そのrunの保存ソースを使うか、2手法へ明示的に移行します。互換aliasや旧推定器へのfallbackはありません。

## 検証

- 有限bin・D_out・損失（scipyのbinomial/beta-binomialと照合）・count選別・loss cone検定・
  offset/事前分布・profile区間・欠測・固定Beff：`tests/test_er_finite_bin.py`
- Halekas hard/probitの回復・Rm<1・探索一致：`test_electron_reflection.py`、
  `test_electron_reflection_subunity.py`、`test_halekas_search.py`
- KAGUYAの共通入力・exposure・geometry・読込：`test_kaguya_er.py`、
  `test_kaguya_er_geometry.py`、`test_kaguya_pace.py`
- 通常APIから試作を読み込まない境界：`test_experimental_boundary.py`

使い方とDの解釈は[ER APIの説明](electron-reflectometry.md)を参照してください。
