# 電子反射法の試作API

ERは電子のenergy-pitch分布から反射障壁を推定する試作です。
数値的なfit成功を、月面磁場の測定成功と同一視しません。
現在のモデルを正式な磁場推定法として保証するものではありません。

手法ごとの入力、目的関数、実行入口は[ER手法とコードの一覧](er-methods.md)にまとめています。

## 有限binのbottom・scale可変モデルとD_out

fold分布の解析には次のAPIを使います。`angular_transport="out"`でD_outを有効にし、
`"none"`（既定）でDiagonalを使います。同じ有限binモデルのoptionです。

```python
from sopran.experimental.electron_reflection import (
    FiniteBinFitSettings, FiniteBinObservation, fit_finite_bin_distribution,
)

# 各配列は同じenergy×pitchビン。比は自然対数ではなくlog10（dex）。
observation = FiniteBinObservation(
    energy_edges_eV=energy_edges,
    pitch_edges_deg=pitch_edges,  # 0〜90度のfold後のedge
    incident_flux=reference_flux,
    observed_log_ratio_dex=log10_ratio,
    b_sc_nT=b_sc,
    fit_valid=valid,
)
settings = FiniteBinFitSettings(angular_transport="out", loss="huber", huber_delta_dex=0.1)
result = fit_finite_bin_distribution(observation, settings=settings)
print(result.effective_field_nT, result.parameters.delta_u_eV, result.parameters.sigma_deg)
```

`er.effective_field.fit_finite_bin(observation, settings=settings)`からも同じ処理を呼べます。
`ElectronReflectionCounts`を持つ場合は、実際のedgeを渡す
`FiniteBinObservation.from_counts(counts, energy_edges_eV=..., pitch_edges_deg=...)`を使います。
これは0.5のpseudocountでexposure補正したlog10比を作り、両側5 count以上、各energyで
3 pitch以上、exposure比0.01〜100をfit対象にします。入力側のcutは引数で明示します。
既に作った比にpseudocountを重ねて加えないよう、直接入力とcount入力を選び分けます。
機器の校正・電位補正はこのfitの前に行い、incident fluxは各energy内でpitch間の相対値を保ちます。

モデルは、solid angleで積分したincident強度に反射率とbeamを適用し、D_outで移してから
uniform log-energy/pitchの理想的bin応答で観測比へ戻します。

$$
N_{out}=D_{out}\{s[\rho+(1-\rho)P_0]N_{in}+N_{beam}\},
\qquad \sin^2\alpha_c=(1+\Delta U/E)/R_m.
$$

`bottom_ratio`が$\rho$、`scale`が$s$です。内側のレベルは$s\rho$、外側は$s$です。
beamは既定で保持し、`beam_enabled=False`でoffにできます。候補はなし＋
log-energy幅0.15/0.30、pitch幅10/20度、振幅0.5/1/2/4の計17個です。
`beam_template=0`はなし、それ以外は`1 + 8*energy_index + 4*pitch_index + amplitude_index`です。

反射境界・beamを分割17点Gauss積分し、各pitch binを既定8分割します。
探索はseed付きDE（35候補、180世代、2 seed）と有界Nelder–Mead（最大650反復）で、
応答から最適化までRustで実行します。Pythonへのcallbackや暗黙のPython fallbackはありません。

Huberの目的関数は残差$r$に対し$r^2$（$|r|\le0.1$）、
それ以外で$0.2|r|-0.01$です。`objective_sum`とセル数で割った`objective_mean`を返します。
`root_mean_square_error_dex`は二乗残差から別途計算し、Huber値と区別します。

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
`field_unconstrained`はcontrast消失・境界が見えない・Rmが探索端にある兆候をまとめます。
このフラグがfalseでも識別性の証明にはならず、磁場の採択にはprofileや回復試験が必要です。
`evaluate`で固定パラメータを評価した結果の`local_converged`はfalseです。
新APIはStoreへ自動保存せず、結果に設定を保持します。

## Halekasの固定0.1/1モデル

`fit_halekas_distribution(counts, settings=HalekasFitSettings(...))`を使います。
両手法で共有する `ElectronReflectionCounts` はenergy×folded pitchの入力型です。
Halekasはexposure補正後の自然対数比の二乗残差を最小化します。
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
