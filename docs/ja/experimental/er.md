# 電子反射法（ER）

電子反射法（Electron Reflectometry）は、探査機で測った電子のエネルギー・ピッチ角分布から、
月面へ向かった電子がどこで跳ね返されたか（反射の障壁）を推定する手法です。
SOPRANの試作は、ピッチ角分布の「ロスコーン」の境界から磁気ミラー比$R_m$と電位差$\Delta U$を当てはめます。

!!! warning "解釈の限界"
    当てはめが数値的に収束したことは、月面の磁場を測れたことを意味しません。
    $B_\mathrm{eff} = R_m B_\mathrm{sc}$（nT）は反射の境界を表す実効的な磁場で、地殻磁場のベクトルではありません。
    $\Delta U$は「月面の電位 − 探査機の電位」（eV）で、月面の絶対電位でもありません。
    磁場として採用するかは、下の品質フラグとプロファイル区間で判断します。

## 手法の選び方

推定器は**finite-bin**と**Halekas**の2つです。

| 用途 | 手法と設定 |
|---|---|
| 主解析 | finite-bin、beta-binomialのカウント尤度（既定）。角度方向の拡散$D_\mathrm{out}$は必要に応じて有効にする |
| 磁場として採用するかの判断 | `profile_mirror_ratio`の区間と`field_flags` |
| フラックスしか無い入力、以前の解析との比較 | finite-bin、`loss="huber"`（0.1 dex） |
| 固定した反射率0.1・外側1のモデルとの比較 | Halekas |

モデルの式、目的関数、フラグの定義は[ERモデルの定義](er-models.md)にあります。

## KAGUYAのデータから推定する

```python
import sopran as spn
from sopran.experimental.kaguya.er import KaguyaErInstrument
from sopran.experimental.electron_reflection import (
    FiniteBinFitSettings, FiniteBinObservation, HalekasFitSettings,
)

er = KaguyaErInstrument(spn.Kaguya())
pitch_counts = er.pitch_angle_spectrum(spn.day("2008-04-26"))

# magnetic_field と position は同じ座標系の配列、または SopranArray
counts = er.paired_counts(
    pitch_counts, index=0, magnetic_field=magnetic_field, position=position,
)

observation = FiniteBinObservation.from_counts(
    counts, energy_edges_eV=energy_edges, pitch_edges_deg=folded_pitch_edges,
)
result = er.effective_field.fit_finite_bin(
    observation, settings=FiniteBinFitSettings(angular_transport="out"),
)
profile = er.effective_field.profile_finite_bin(observation, result)

comparison = er.effective_field.fit_halekas(counts, settings=HalekasFitSettings())
```

### 入力の準備

`KaguyaErInstrument`は、ESAの読み込みと校正、余白を付けたLMAGの読み込み、SPICEの準備を2つの入口で共有します。
`pitch_angle_spectra(..., align=False)`はセンサーごとに元の時刻を保ったピッチ角スペクトルを返します。

`paired_counts`は、指定した1サンプルの0〜90度と90〜180度を対にした`ElectronReflectionCounts`
（エネルギー×折り返したピッチ角）を作ります。

- 月面から戻ってくる向き（反射を経た電子）の半球を「affected」、月面へ向かう向き（入射電子）を「reference」とします。
  +Bが月から外向きなら低ピッチ角側をaffectedにし、それ以外は高ピッチ角側にします。
  `affected_side="low"`または`"high"`で明示もできます。
- finite-binには、校正済みの実際のビン境界を`energy_edges_eV`と`pitch_edges_deg`で渡します。中心値から境界を推定しません。
- 露出時間は、明示した値、スペクトルの座標、等しい露出の順で決めます。明示する値は、選んだサンプルの
  エネルギー×ピッチ角に放送（broadcast）できる配列です。等しい露出を仮定したときは入力のメタデータに記録します。

取得・校正には`kaguya`、推定には`experimental`、作図には`viz`のextraを使います。

## 結果を読む

```python
result.effective_field_nT       # B_eff
result.field_flags              # 磁場を決められない理由
result.field_unconstrained      # field_flags のどれかが立っていれば True
profile.interval_nT             # R_m を固定して再最適化した95%区間
```

フラグが立っていなくても、磁場が一意に決まったとは限りません。採用の判断にはプロファイル区間を使い、
区間が探索範囲の端に届いた（`interval_bounded=False`）ものや、より良い解が見つかった（`improved_minimum=True`）ものは
個別に確かめます。カウント損失とHuber損失で別の解に落ちる窓では、カウント損失のプロファイル区間が両方を含むことがあります。
この場合は点推定の差ではなく、区間の幅で識別できたかを判断します。

## 結果の保存

推定結果は手法ごとの型付きdataclassで返し、Storeへ自動では保存しません。
呼び出し側で、設定・入力・マスク・ビン・コードのハッシュと一緒に保存してください。
全期間をまとめて処理し、設定とコードを固定して保存する仕組みは[ER全期間バッチ](er-batch.md)にあります。

## モジュール構成

| 場所 | 役割 |
|---|---|
| `electron_reflection/common.py` | 共通の入力型`ElectronReflectionCounts`、露出の検証、境界の式`mirror_boundary_sin2` |
| `electron_reflection/finite_bin.py` | finite-binモデル、損失、ロスコーンの検定、プロファイル |
| `electron_reflection/halekas.py` | Halekasモデル |
| `experimental/kaguya/er.py` | ESA1/ESA2・LMAG・SPICEの準備、ピッチ角スペクトル、`paired_counts`、推定器の呼び出し |
| `experimental/kaguya/er_batch.py` | 全期間の日別シャード化、設定の固定、並列の当てはめ、Storeへの登録 |
| `crates/sopran-native/src/finite_bin.rs` | finite-binの応答・$D_\mathrm{out}$・損失・最適化（Rust） |

## 廃止した推定器

paired-countのbeta-binomial推定器（カウント尤度は2026-10-10にfinite-binの`loss`へ統合）、binary surface、joint、
global-joint、incident・integratedの各推定器と、それら専用のwarm start・尤度スキャン・時系列・カタログ・スキーマ・評価補助は削除しました。
旧`fit`、`fit_joint`、`fit_global_joint`、`fit_timeseries`、`build`の代わりに`fit_finite_bin`・`fit_halekas`を使います。
旧`sopran-er-finite-bin`のJSONL CLIも廃止し、PyO3のAPIに一本化しました。互換の別名や旧推定器への切り替えはありません。
過去に保存したデータはStoreに残り、通常のデータセットとして読めます。

## 検証

| 対象 | テスト |
|---|---|
| finite-bin、$D_\mathrm{out}$、損失（scipyの二項・beta-binomialと照合）、カウントの選別、ロスコーンの検定、オフセットと事前分布、プロファイル区間、欠測、固定$B_\mathrm{eff}$ | `tests/test_er_finite_bin.py` |
| Halekasのhard/probitでの回復、$R_m<1$、探索の一致 | `test_electron_reflection.py`、`test_electron_reflection_subunity.py`、`test_halekas_search.py` |
| KAGUYAの入力、露出、幾何、読み込み | `test_kaguya_er.py`、`test_kaguya_er_geometry.py`、`test_kaguya_pace.py` |
| 通常APIが試作を読み込まないこと | `test_experimental_boundary.py` |
