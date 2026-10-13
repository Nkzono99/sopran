# ERモデルの定義

[電子反射法](er.md)で使う2つの推定器の、モデル・目的関数・数値計算・品質の判定を定義します。
入力はどちらも、エネルギー×折り返したピッチ角の`ElectronReflectionCounts`（affectedとreferenceのカウントと露出）です。

## finite-binモデル

```python
from sopran.experimental.electron_reflection import (
    FiniteBinFitSettings, FiniteBinObservation, fit_finite_bin_distribution, profile_mirror_ratio,
)

observation = FiniteBinObservation.from_counts(
    counts, energy_edges_eV=energy_edges, pitch_edges_deg=folded_pitch_edges,
)
result = fit_finite_bin_distribution(observation, settings=FiniteBinFitSettings())
profile = profile_mirror_ratio(observation, result)
```

### モデルの式

入射フラックスを立体角で積分した強度に反射率とビームを掛け、角度方向の輸送$D_\mathrm{out}$で移したうえで、
エネルギーの対数・ピッチ角について一様な理想的ビン応答で観測の比に戻します。

$$
N_\mathrm{out} = D_\mathrm{out}\left\{ s\left[\rho + (1-\rho)P_0\right] N_\mathrm{in} + N_\mathrm{beam} \right\},
\qquad
\sin^2\alpha_c = \frac{1 + \Delta U / E}{R_m}.
$$

| 記号 | `result.parameters`の名前 | 意味 |
|---|---|---|
| $R_m$ | `mirror_ratio` | 磁気ミラー比。$B_\mathrm{eff} = R_m B_\mathrm{sc}$（`result.effective_field_nT`） |
| $\Delta U$ | `delta_u_eV` | 月面と探査機の電位差（月面 − 探査機、eV） |
| $\rho$ | `bottom_ratio` | ロスコーンの内側の相対レベル。内側は$s\rho$、外側は$s$ |
| $s$ | `scale` | 全体の倍率 |
| | `sigma_deg` | $D_\mathrm{out}$の拡散の大きさ |
| $\phi$ | `concentration` | beta-binomialの集中度 |
| $\alpha_c$ | | ロスコーンの境界のピッチ角 |
| $P_0$ | | 境界の外側で1、内側で0になる反射の指示関数 |

探索範囲は`FiniteBinFitSettings`の`mirror_ratio_bounds`、`delta_u_bounds_eV`、`bottom_ratio_bounds`、
`scale_bounds`、`sigma_bounds_deg`、`concentration_bounds`で指定します。

**ビーム**は既定で有効で、`beam_enabled=False`で無効にできます。形はエネルギーの対数幅0.15・0.30と
ピッチ角幅10・20度を組み合わせた4つです。振幅は`beam_amplitude_bounds`（既定0.25〜8）の範囲で、
評価のたびに形ごとの1次元の黄金分割探索で連続的に決めます。結果の`beam_template`は、0がビーム無し、
それ以外が`1 + 2*energy_index + pitch_index`で、振幅は`beam_amplitude`です。

**既知の効率比**は、観測の`model_offset_dex`（affected/referenceの効率比のlog10）としてモデルの比に加えます。
`scale_prior_sigma_dex`は$\log_{10}s$に中心0のガウス事前分布を置きます（カウント損失のみ）。
オフセットと併用すると、事前分布の中心を校正値へ移せます。

### 角度方向の輸送$D_\mathrm{out}$

`FiniteBinFitSettings(angular_transport="out")`で有効にし、既定の`"none"`では対角（輸送なし）です。

`result.d_out[j_out, j_in]`は出発ビンから到着ビンへ移る確率で、各列の和は1です。軸の境界は
`result.transport_pitch_edges_deg`にあり、百分率で表示するには`100 * result.d_out`を使います。
反射とビームの後に作用し、エネルギーの間は混ぜません。折り返した半球の0度と90度に流れの無い境界を置いた軸対称の拡散で、
等方なフラックスを定常に保ちます。`sigma_deg`は小角の極限で方向の変化のRMSに対応する拡散のパラメーターで、
大きな値ではピッチ角の差の単純なガウス標準偏差ではありません。0で対角に一致します。

### 目的関数

| `loss` | 観測量 | 用途 |
|---|---|---|
| `"beta_binomial"`（既定） | affectedのカウント（試行数はaffected＋reference） | 系統的な過分散を集中度$\phi$で吸収する主解析 |
| `"binomial"` | 同上 | 統計誤差だけを仮定する比較 |
| `"huber"`（既定0.1 dex） | $\log_{10}(a/r)$ | フラックスだけの入力、以前の解析との比較 |
| `"squared"` | $\log_{10}(a/r)$ | 比較 |

カウント損失では、affectedのカウント$a$を、試行数$n = a + r$の二項分布として扱います。
affected側の確率は$q = \lambda/(1+\lambda)$、$\lambda = x\,10^{c}R$です。$R$はモデルの比、$x$はaffected/referenceの露出比、
$c$は`model_offset_dex`です。beta-binomialは平均$q$・集中度$\phi$の分布で、$\phi$も他のパラメーターと同時に推定します。
`objective_sum`は飽和した二項尤度に対する$-2\log L$の差（逸脱度）なので、2つの当てはめの差をχ²の尺度で読めます。
カウント損失には、カウントを持つ観測（`from_counts`で作ったもの）が必要です。

Huberの目的関数は、残差$r$に対して$|r| \le 0.1$で$r^2$、それ以外で$0.2|r| - 0.01$です。
`objective_sum`と、セル数で割った`objective_mean`を返します。`root_mean_square_error_dex`は二乗残差から別に計算し、
目的関数の値とは区別します。

### 当てはめに使うセル

`from_counts`の既定は`selection="total"`、`min_counts=1`で、$a + r \ge 1$のセルを残します。
$a = 0$のセルもロスコーンの内側の情報として目的関数に入ります。
`selection="paired", min_counts=5`は、両側に5カウント以上を要求する以前の選別です。affectedのカウントで選ぶため、
ロスコーンの深い所のセルが欠けて$\rho$が上に偏ります。真値$\rho = 0.15$の合成カウントでは、
paired＋Huberが0.18〜0.6、total＋beta-binomialが0.15でした。

どちらの選別でも、各エネルギーで3ピッチ角以上、露出比0.01〜100のセルだけを当てはめます。
対数比は0.5の擬似カウントで作り、RMSEと図に使います。機器の校正と電位の補正はこの当てはめの前に行い、
入射フラックスは各エネルギーの中でピッチ角間の相対値を保ちます。

入射側のビンが欠けているときは、同じエネルギーの中で対数フラックスを補間し、端は最も近い値を使います。
補間したビンは`interpolated_incident_bins`に返し、欠けたセル自体は目的関数に加えません。
補間した入射は$D_\mathrm{out}$を通じて観測セルへ流れ込むため、欠けが多いと入力の仮定が結果に効きます。
使わないエネルギー行の再構成はNaNのまま残します。

### 数値計算

反射の境界とビームを分割17点のガウス積分で評価し、各ピッチ角ビンを既定で8分割します。
探索は、seed付きの差分進化（35候補、180世代、2 seed）と、範囲付きのNelder–Mead（最大650反復）です。
`starts`を省くと、$R_m$ = 1.2、2、5、20と$\Delta U$ = −50、0、+50 eVの12点からもNelder–Meadを始めます。
差分進化だけでは、KAGUYAの7窓のうち2窓で最良の谷を逃したためです。
応答の計算から最適化まではRustで実行し、Pythonへのコールバックや暗黙のPython版への切り替えはありません。

### 品質の判定

`local_converged`は局所探索の終了判定、`at_bounds`は可変のパラメーターが探索範囲の端にあることを示します。
`field_unconstrained`は、次の`field_flags`のどれかが立つとTrueです。

| フラグ | 条件 |
|---|---|
| `no_contrast` | $\rho \ge 0.99$ |
| `barrier_unobserved` | 当てはめたセルがすべて境界の片側 |
| `field_at_search_bound` | $R_m$が探索範囲の端 |
| `boundary_rows_insufficient` | 境界の両側にセルを持つエネルギー行が`min_boundary_rows`（既定3）未満 |
| `loss_cone_unsupported` | カウント損失で`loss_cone_delta_bic` ≤ 0 |

`loss_cone_delta_objective`は、エネルギー行ごとに自由なレベルを許した2つのモデル、つまりロスコーン無し（$\rho = 1$）と
当てはめたロスコーンを、同じビームで比べた目的関数の差です。エネルギー方向だけの段差はどちらでも説明できるため、
この差はピッチ角方向の構造が必要かを表します。`loss_cone_delta_bic`は、$R_m$・$\rho$・$\Delta U$のうち
可変なものの数$k$について$k\ln N$を引いた値です。実データでも一定の割合の窓が`loss_cone_unsupported`になり、
その割合は$R_m \le 1$の解で高くなります。

### プロファイル区間

フラグが立たなくても識別できた証明にはならないため、磁場の採用には`profile_mirror_ratio`を使います。
$R_m$を格子（既定は±1 dex、21点）に固定し、他のパラメーターを近くの解から再最適化します。
カウント損失では$\Delta$`objective` ≤ 3.84を95%区間とし、端は格子の間で補間します。

| 結果 | 意味 |
|---|---|
| `interval_nT` | $B_\mathrm{eff}$の95%区間 |
| `interval_bounded=False` | 区間が格子の端に届いた |
| `improved_minimum=True` | 当てはめが良い谷を逃していた。その解を`minimum_fit`に返す |

`evaluate`で固定したパラメーターを評価した結果の`local_converged`はFalseです。

### パラメーターを固定する

上限と下限を等しくすると、そのパラメーターを固定します。たとえば領域平均の磁場を$B_\mathrm{eff}$に固定して$\Delta U$などを当てはめ直すには
`mirror_ratio_bounds=(area_mean_nT / b_sc, area_mean_nT / b_sc)`を指定します。
`bottom_ratio_bounds=(0.1, 0.1)`、`scale_bounds=(1, 1)`とすれば、固定した0.1/1のレベルでfinite-binと比べられます。

## Halekasモデル

```python
from sopran.experimental.electron_reflection import HalekasFitSettings, fit_halekas_distribution

result = fit_halekas_distribution(counts, settings=HalekasFitSettings())
```

Halekasは、露出で補正した自然対数の比の二乗残差を最小にします。$a + r$が`min_cell_total_counts`（既定1）未満のセルは除きます。
空のセルは擬似カウントで比が1になり、ロスコーンが無いように見えてしまうためです。
`root_mean_square_error`は自然対数の単位なので、同じ入力・マスクでdexのRMSEと比べるときは`np.log(10)`で割ります。

| `edge_transition` | モデルと探索 |
|---|---|
| `"hard"`（既定） | 固定した後方散乱（既定0.1）と外側1の二値の分布をビン中心で評価し、$R_m$・$\Delta U$の格子探索と格子の細分化を行う |
| `"probit"` | 同じレベルに境界の幅を加え、hardの解などからL-BFGS-Bで探索する |

自由な`bottom`・`scale`・ビーム・$D_\mathrm{out}$はfinite-bin側の機能です。probitの幅（境界のなまり）と
$D_\mathrm{out}$（角度の間の輸送）は別のパラメーターです。RMSEを比べるときは単位とマスクをそろえ、
HalekasのガウスBICとHuberの値は直接比べません。
