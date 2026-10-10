# 電子反射法の試作API

ERは電子のenergy-pitch分布から反射障壁を推定する試作です。
数値的なfit成功を、月面磁場の測定成功と同一視しません。
現在のモデルを正式な磁場推定法として保証するものではありません。

手法ごとの入力、目的関数、実行入口は[ER手法とコードの一覧](er-methods.md)にまとめています。

## 有限binのbottom・scale可変モデルとD_out

fold分布の解析には次のAPIを使います。既定の目的関数はpaired countの
beta-binomial尤度です。`angular_transport="out"`でD_outを有効にし、
`"none"`（既定）でDiagonalを使います。

```python
from sopran.experimental.electron_reflection import (
    FiniteBinFitSettings, FiniteBinObservation, fit_finite_bin_distribution,
    profile_mirror_ratio,
)

# countsはElectronReflectionCounts。edgeは校正済みの実際のbin境界。
observation = FiniteBinObservation.from_counts(
    counts, energy_edges_eV=energy_edges, pitch_edges_deg=folded_pitch_edges,
)
result = fit_finite_bin_distribution(observation, settings=FiniteBinFitSettings())
profile = profile_mirror_ratio(observation, result)
print(result.effective_field_nT, profile.interval_nT, result.field_flags)
```

`er.effective_field.fit_finite_bin(observation, settings=settings)`と
`er.effective_field.profile_finite_bin(observation, result)`からも同じ処理を呼べます。

### 目的関数とcountの選別

`loss`は次の4つです。count損失はcountを持つ観測（`from_counts`）が必要です。

| `loss` | 観測量 | 用途 |
|---|---|---|
| `"beta_binomial"`（既定） | affected count \| affected＋reference | 系統的な過分散を集中度$\phi$で吸収する主解析 |
| `"binomial"` | 同上 | 統計誤差だけを仮定する比較 |
| `"huber"`（既定0.1 dex） | log10(a/r) | fluxだけの入力、旧解析との比較 |
| `"squared"` | log10(a/r) | 比較 |

count損失では、affected countを試行数$n=a+r$の二項分布として扱います。
affected側の確率は$q=\lambda/(1+\lambda)$、$\lambda=x\,10^{c}R$です。
$R$はモデル比、$x$はaffected/referenceのexposure比、$c$は`model_offset_dex`です。
beta-binomialは平均$q$、集中度$\phi$の分布で、$\phi$を他のパラメータと同時に推定します。
`objective_sum`は飽和二項尤度に対する$-2\log L$の差（deviance）です。
そのため、2つのfitの差はχ²の尺度で読めます。

`from_counts`は既定で`selection="total"`、`min_counts=1`を使い、$a+r\ge1$のcellを残します。
$a=0$のcellもloss cone内の情報として目的関数へ入ります。
`selection="paired", min_counts=5`は両側5 count以上を要求する旧D-gallery cutです。
affected countで選別するため、loss cone深部のcellが欠け、$\rho$が上へ偏ります。
合成countの試験（真値$\rho=0.15$）では、paired cut＋Huberが0.18〜0.6、
total＋beta-binomialが0.15でした。どちらのselectionでも、
各energyで3 pitch以上、exposure比0.01〜100をfit対象にします。
log10比は0.5のpseudocountで作り、RMSEと図に使います。
機器の校正・電位補正はこのfitの前に行い、incident fluxは各energy内でpitch間の相対値を保ちます。

### モデル

モデルは、solid angleで積分したincident強度に反射率とbeamを適用し、D_outで移してから
uniform log-energy/pitchの理想的bin応答で観測比へ戻します。

$$
N_{out}=D_{out}\{s[\rho+(1-\rho)P_0]N_{in}+N_{beam}\},
\qquad \sin^2\alpha_c=(1+\Delta U/E)/R_m.
$$

`bottom_ratio`が$\rho$、`scale`が$s$です。内側のレベルは$s\rho$、外側は$s$です。
beamは既定で保持し、`beam_enabled=False`でoffにできます。形状はlog-energy幅0.15/0.30と
pitch幅10/20度の4つです。振幅は`beam_amplitude_bounds`（既定0.25〜8）の範囲で、
評価ごとに形状別の1次元golden-section探索で連続的に決めます。
`beam_template=0`はなし、それ以外は`1 + 2*energy_index + pitch_index`で、
振幅は`beam_amplitude`に返します。

`model_offset_dex`は既知のaffected/reference効率比（log10）で、モデル比に加えます。
`scale_prior_sigma_dex`はlog10 $s$に中心0のGaussian事前分布を置きます（count損失のみ）。
offsetと併用すれば、事前分布の中心を校正値へ移せます。

反射境界・beamを分割17点Gauss積分し、各pitch binを既定8分割します。
探索はseed付きDE（35候補、180世代、2 seed）と有界Nelder–Mead（最大650反復）です。
`starts`を省略すると、Rm 1.2/2/5/20とΔU −50/0/+50 eVの12点からもNelder–Meadを始めます。
DEだけでは、KAGUYAの7窓中2窓で最良の谷を逃したためです。応答から最適化までRustで実行し、
Pythonへのcallbackや暗黙のPython fallbackはありません。

Huberの目的関数は残差$r$に対し$r^2$（$|r|\le0.1$）、
それ以外で$0.2|r|-0.01$です。`objective_sum`とセル数で割った`objective_mean`を返します。
`root_mean_square_error_dex`は二乗残差から別途計算し、目的関数の値と区別します。

## 固定Beff、Dと品質の読み方

例えばArea meanをBeffに固定してΔU等を再fitする場合は、
`mirror_ratio_bounds=(area_mean_nT / b_sc, area_mean_nT / b_sc)`を指定します。
等しい上下限は固定を意味し、`bottom_ratio_bounds=(0.1, 0.1)`、
`scale_bounds=(1, 1)`にすれば固定0.1/1の有限bin比較もできます。

`result.d_out[j_out, j_in]`は出発binから到着binへの確率で、各列の和は1です。
0〜30%で表示する場合は`100 * result.d_out`を使います。軸のedgeは
`result.transport_pitch_edges_deg`です。反射・beamの後に作用し、energy間は混ぜません。
fold半球の0/90度にno-flux境界を置く軸対称diffusionで、等方fluxを定常に保ちます。
`sigma_deg`は小角極限のRMS方向変化に対応する拡散パラメータで、大きな値では
pitch差の単純なGaussian標準偏差ではありません。ゼロでDiagonalへ一致します。

欠測incident binは同じenergy内でlog-fluxを補間し、端は最寄り値を使います。
`interpolated_incident_bins`を返し、欠測cellをfitへ加えません。
補間されたincidentはD経由で観測cellへ流入するため、欠測が多い場合は入力仮定が効きます。
inactive energy行の再構成はNaNで残します。

`local_converged`は局所solverの終了判定、`at_bounds`は可変パラメータの探索端です。
`field_unconstrained`は`field_flags`のいずれかが立つとtrueです。

| flag | 条件 |
|---|---|
| `no_contrast` | $\rho\ge0.99$ |
| `barrier_unobserved` | fit cellがすべて境界の片側 |
| `field_at_search_bound` | Rmが探索端 |
| `boundary_rows_insufficient` | 境界の両側にcellを持つenergy行が`min_boundary_rows`（既定3）未満 |
| `loss_cone_unsupported` | count損失で`loss_cone_delta_bic`$\le0$ |

`loss_cone_delta_objective`は、energy行ごとに自由なレベルを許した2つのモデルの目的関数差です。
loss coneなし（$\rho=1$）とfit値のloss coneを、同じbeamで比べます。
energyだけの段差はどちらでも説明できるため、この差はpitch方向の構造が必要かを表します。
`loss_cone_delta_bic`はRm・$\rho$・ΔUのうち可変な数$k$について$k\ln N$を引いた値です。
KAGUYAの288窓では21%が`loss_cone_unsupported`で、その割合はRm≤1で33%、Rm>1で11%でした。

フラグがfalseでも識別性の証明にはならないため、磁場の採択には`profile_mirror_ratio`を使います。
Rmを格子（既定は±1 dex、21点）に固定し、他のパラメータを近傍から再最適化します。
count損失では$\Delta$`objective`$\le3.84$を95%区間とし、端は格子間で補間します。
`interval_bounded=False`は区間が格子の端に届いたことを示します。
`improved_minimum=True`はfitが良い谷を逃したことを示し、`minimum_fit`にその解を返します。
例えば2008-02-10 03:03:36 UTCの窓では、beta-binomialの解は124.7 nTです。
その95%区間は15.7〜124.7 nTで、Huberで見つかった約17 nTの解も含みます。

`evaluate`で固定パラメータを評価した結果の`local_converged`はfalseです。
新APIはStoreへ自動保存せず、結果に設定を保持します。

## Halekasの固定0.1/1モデル

`fit_halekas_distribution(counts, settings=HalekasFitSettings(...))`を使います。
両手法で共有する `ElectronReflectionCounts` はenergy×folded pitchの入力型です。
Halekasはexposure補正後の自然対数比の二乗残差を最小化します。
$a+r$が`min_cell_total_counts`（既定1）未満のcellは除きます。
空のcellはpseudocountで比1となり、loss coneがないように見えるためです。
`root_mean_square_error`は自然対数の単位なので、同じ入力・maskでdexのRMSEと
比較する場合は `np.log(10)` で割ります。

既定の `edge_transition="hard"` は固定backscatter（既定0.1）と外側1の二値分布を
bin中心で評価し、Rm・ΔUのgrid探索とgrid精細化を行います。
`"probit"` は同じレベルに境界幅を加え、hard解等からL-BFGS-Bで探索します。
自由bottom・scale・beam・D_outはfinite-binの機能です。
probit幅とD_outの角度輸送は別のパラメータです。

## KAGUYAの共通入力

```python
import sopran as spn
from sopran.experimental.kaguya.er import KaguyaErInstrument
from sopran.experimental.electron_reflection import (
    FiniteBinObservation, FiniteBinFitSettings, HalekasFitSettings,
)

er = KaguyaErInstrument(spn.Kaguya())
pitch_counts = er.pitch_angle_spectrum(spn.day("2008-04-26"))
# magnetic_fieldとpositionは同じ座標系の配列またはSopranArray。
counts = er.paired_counts(
    pitch_counts, index=0, magnetic_field=magnetic_field, position=position,
)
comparison = er.effective_field.fit_halekas(counts, settings=HalekasFitSettings())
observation = FiniteBinObservation.from_counts(
    counts, energy_edges_eV=energy_edges, pitch_edges_deg=folded_pitch_edges,
)
result = er.effective_field.fit_finite_bin(
    observation, settings=FiniteBinFitSettings(angular_transport="out"),
)
```

`paired_counts` は指定した1サンプルの0–90°と90–180°を対にします。
+Bが外向きならlow pitchをaffected側、それ以外ならhigh pitchをaffected側に選びます。
`affected_side="low" / "high"` の明示指定も可能です。
有限binには校正済みの実際のedgeを渡し、中心値からedgeを仮定しません。
exposureは明示値、スペクトルの座標、等しいexposureの順で解決します。
明示値は選んだサンプルのenergy×pitchにbroadcastできる配列です。
等しいexposureを仮定した場合は入力のmetadataに記録します。

`pitch_angle_spectra(..., align=False)` はsensor別のnative時刻を保ちます。
ESA読込・校正、LMAGの余白付き読込、SPICE準備を2つの読込入口で共有します。
取得・校正には `kaguya` extra、推定には `experimental`、可視化には `viz` を使います。

## 結果と移行

結果は各手法のtyped dataclassで返し、Storeへ自動保存しません。
呼出し側で設定・入力・mask・bin・コードhashとともに保存します。
B_effは `Rm * Bsc` [nT]、ΔUはsurface minus spacecraft [eV]です。
境界のパラメータを地殻磁場ベクトルや絶対月面電位と同一視しません。

旧paired-count・binary・joint・global-joint推定器と、その専用の時系列・catalog・schema・
尤度scan・評価補助は廃止しました。旧 `fit`、`fit_joint`、`fit_global_joint`、
`fit_timeseries`、`build` の代わりに `fit_finite_bin` / `fit_halekas` を使います。
既存の保存データは残り、Storeの通常のdataset読込で参照できます。

::: sopran.experimental.kaguya.er.KaguyaErInstrument
