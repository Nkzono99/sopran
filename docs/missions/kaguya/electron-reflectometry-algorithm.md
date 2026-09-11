# 電子反射法の推定アルゴリズム

この文書は、SOPRAN が KAGUYA/PACE の電子 count から
`mirror_ratio` と `effective_field` を推定する手順を、必要な物理から順に説明します。
実装の入口は `spn.kaguya.er.effective_field.fit(...)` です。

!!! warning "現在は candidate product"
    推定値は loss-cone に似た境界を count 統計から検出した**観測時点の実効量**です。
    月面磁場ベクトルや、月面上の一点を直接測った値ではありません。全期間で何が検証でき、
    何が未検証かは[全期間検証](electron-reflectometry-validation.md)を参照してください。

## 境界中心モデルの比較API

fold前のS1/S2 native countをfitする `global_joint` には、従来モデルと比較するための
固定・共通レベル版があります。以下の `observations` は
`Mapping[str, GlobalPitchCountObservation]` です。

```python
from sopran.analysis.electron_reflection import (
    GlobalJointFitSettings,
    fit_global_joint_effective_field,
    plot_global_joint_effective_field_fit,
)

settings = GlobalJointFitSettings(
    loss_cone_model="fixed",  # "shared": C,fを全energy共通でfit
    edge_transition="hard",
    secondary_beam="auto",
)
result = fit_global_joint_effective_field(observations, settings=settings)
figure = plot_global_joint_effective_field_fit(result)
```

affected側のrate比は $q=C[f+(1-f)T]+A_{beam}g$、reference側は $q=1$ です。
`fixed` は $C=1,f=0.1$、`shared` は $C,f$ を推定します。従来のエネルギー依存baseline・
band contrastは `loss_cone_model="flexible"` で、既定値はまだこちらです。
固定・共通版はbaseline knot数とcontrast family設定を上書きし、自由なenergy別レベルを持ちません。
no-edge候補は全energy共通の半球レベルを1個推定し、edgeを強制しない比較基準にします。

hard境界はpitchビン内で解析積分し、energyビン内ではincident spectrumとともにquadratureで
積分します。これは指定ビン内の一様応答近似であり、実機の全応答を測定したものではありません。
既知のdetector response matrixがあれば、さらに適用します。したがって測定セル上の予測は
厳密な0.1/1二値ではありません。`smooth` は共通の固有幅を持つ $T$ を使い、rateの線形混合を
積分します。hardの目的関数・gradientはRust、smoothはPythonです。

制約付きhard・beamなし候補では、局所最適化後に25点のlog磁場格子と31点の電位格子を
探索し、改善点から全自由パラメータを再最適化します（最大2回）。既存の収束解は保持し、
収束して目的関数が改善した解だけに更新します。各窓内の処理であり、隣接窓の推定値をpriorに
しません。`boundary_grid_refinement=False` で比較用に無効化できます。beamのscreenで
一部パラメータを固定する経路には適用しません。この有限格子で大域最適性は保証しません。

同じ観測セルのcount尤度で比較し、固定値はBICの自由パラメータ数に数えません。
beam中心は電位に固定せず同時推定します。詳細と未検証項目は
[改良方針](electron-reflectometry-method-survey.md#72-2026-09)を参照してください。

## まず全体像

推定器は画像から磁場を直接読み取る処理ではありません。入力から出力までは次の一本道です。

```text
PACE raw count + calibration + LMAG + spacecraft position
  -> energy/pitch/exposure 配列
  -> 月面向きと反対向きの対称 count pair
  -> no-edge / mirror / electrostatic の count 尤度 fit
  -> BIC による edge model 比較
  -> 支持範囲・境界・残差の gate
  -> good / review / poor / reject
  -> mirror ratio R_m と B_eff = R_m B_sc
  -> profile-likelihood 95%区間（検証用の別 artifact）
```

前半は「何を比較可能な count にするか」、中央は「edge を入れると尤度が十分改善するか」、
後半は「改善した fit を物理候補として残してよいか」を担当します。最適化が収束したこと、
edge model が選ばれたこと、`good`/`review` になったことは、それぞれ別の判定です。

## 読み方

初めて電子反射法に触れる場合は、次の順で読むと全体像を追えます。

1. 「観測しているもの」で energy、pitch angle、count を確認する。
2. 「磁気 mirror と loss cone」で推定式の由来を理解する。
3. 「count の統計モデル」で、画像の境界をどのように数値へ変えるかを確認する。
4. 「採択条件と品質 grade」で、fit 成功と物理候補の採択が別である理由を確認する。
5. 最後に「解釈の境界」を読み、結果に付けてよい物理的な意味を確認する。

## 1. 観測しているもの

### Energy と pitch angle

電子の運動は磁場に平行な成分と垂直な成分に分けられます。pitch angle
$\alpha$ は電子速度と磁場 $+\mathbf{B}$ のなす角です。

- $\alpha \simeq 0^\circ$: $+\mathbf{B}$ に沿う電子
- $\alpha \simeq 90^\circ$: 磁場にほぼ垂直な電子
- $\alpha \simeq 180^\circ$: $-\mathbf{B}$ に沿う電子

PACE は energy channel と look direction ごとの count を記録します。SOPRAN は各 look
direction を同時刻の LMAG 磁場へ射影し、`time x energy x pitch_angle` の count 配列を
作ります。fit に入る主な記号は次の通りです。

| 記号 | package 上の量 | 意味 |
| --- | --- | --- |
| $E_i$ | `energy_eV` | energy bin の代表値 [eV] |
| $\alpha_j$ | `pitch_deg` | 0--90 degree に折り畳んだ pitch angle |
| $a_{ij}$ | `affected_counts` | 月面から外向きで loss-cone の影響を受ける側の count |
| $r_{ij}$ | `reference_counts` | 対称な反対 hemisphere の count |
| $e^a_{ij},e^r_{ij}$ | exposure | 積分時間と検出応答を含む有効 exposure |
| $B_{sc}$ | `b_sc_nT` | 衛星位置で LMAG が測った磁場強度 [nT] |

ここで「affected」は fit がよくなる側を後から選ぶのではありません。pitch 0 degree が
$+\mathbf B$ なので、位置ベクトルを $\mathbf r$ とすると、既定の `auto` は
$\mathbf B\cdot\mathbf r>0$ なら low-pitch 側、負なら high-pitch 側を月面から外向きの
電子として選びます。$\mathbf B\cdot\mathbf r=0$ や非有限値は曖昧なので error です。

### なぜ energy flux ではなく count を使うか

energy flux は見やすい可視化量ですが、較正係数を掛けた連続値です。count の揺らぎを
直接表す確率分布ではありません。この estimator は整数 count と exposure を分離し、
ゼロ count も残して尤度を計算します。そのため入力は `value="counts"`、単位は `count`
でなければなりません。

## 2. 磁気 mirror と loss cone

### 最小限の物理

磁場が電子の gyro scale より十分ゆっくり変化し、衝突や急激な時間変化を無視できると、
第一断熱不変量

$$
\mu = \frac{m v_\perp^2}{2B}
$$

がほぼ保存されます。静電場をいったん無視して運動エネルギーも保存されると、磁場が強く
なるにつれて垂直速度成分が増え、平行速度成分がゼロになった場所で電子は mirror 反射します。
衛星位置の pitch angle を $\alpha$、反射点の磁場を $B_m$ とすると、

$$
\frac{\sin^2\alpha}{B_{sc}} = \frac{1}{B_m}.
$$

月面へ到達する電子と、その前に反射される電子の境界を $\alpha_c$ と置けば、

$$
\sin^2\alpha_c = \frac{B_{sc}}{B_m} = \frac{1}{R_m},
\qquad
R_m = \frac{B_m}{B_{sc}}.
$$

月面へ向かう磁力線方向からの角度が小さい電子は月面まで到達して失われるため、衛星へ戻る
外向き分布では対応する成分が欠けます。元の pitch angle は常に $+\mathbf B$ 基準なので、
この月面向き中心は幾何によって0 degreeまたは180 degreeです。SOPRAN は反対向きの外向き半球を
affected とし、その中心からの角距離を0--90 degreeへ折り畳んだ量を以降の $\alpha$ とします。
この欠損領域が loss cone です。境界 $\alpha_c$ がわかれば $R_m$ を推定できる、というのが
電子反射法の中心です。

!!! example "数値で読む"
    衛星位置で $B_{sc}=5\ \mathrm{nT}$、境界が $\alpha_c=30^\circ$ なら、
    $\sin^2 30^\circ=0.25$ なので $R_m=1/0.25=4$、
    $B_{eff}=4\times5=20\ \mathrm{nT}$ です。ただし30 degree は有限幅の count
    pattern から統計的に推定した境界です。20 nT は仮定した mirror 式の実効量であり、
    月面の一点を磁力計で測った値ではありません。

### 静電的な曲率

衛星と反射領域の間に電位差があると、電子の平行・垂直エネルギーの対応が energy に依存します。
SOPRAN は次の実効境界を使います。

$$
s_i \equiv \sin^2\alpha_c(E_i)
= \frac{1}{R_m}
\left(1+\frac{\Delta U_{eff}}{E_i-U_{sc}}\right).
$$

`spacecraft_potential_eV` が $U_{sc}$、`delta_u_eff_eV` が $\Delta U_{eff}$ です。
物理式と対応させる場合の符号は
$\Delta U_{eff}=U_{surface}-U_{spacecraft}$です。正なら月面側が衛星より正で、電子を月面方向へ
加速して低energyのloss coneを広げます。負なら月面側がより負で、低energy電子を静電的に反射し、
loss coneを狭めます。

重要なのは、$\Delta U_{eff}$ が**曲率を吸収する nuisance parameter**だという点です。
spacecraft potential の既定値は 0 eV であり、独立な電位測定も使っていません。
したがって、fit した値をそのまま月面電位と解釈しません。`electrostatic` という model 名は
energy-dependent な境界を表す仮説名です。

parameterが探索端へ張り付いた場合、この物理解釈は行いません。例えばPE007のprobit解は
$\Delta U_{eff}=+1000$ eVかつ$\sigma_{\ln\sin^2\alpha}=1.5$で両方とも上限です。これは
「月面が+1000 V」とする測定ではなく、未モデル化のbeam、背景、sensor間較正差を正曲率と
広い遷移が吸収した失敗解です。

### SOPRAN が返す推定量

SOPRAN は採択した $R_m$ と衛星位置の $B_{sc}$ から

$$
B_{eff}=R_m B_{sc}
$$

を返します。`B_eff` は mirror 条件が示す反射点側の**実効的な磁場強度**です。

- scalar であり、磁場ベクトルではない
- 反射点や field-line footpoint の座標を同時には決めない
- 有限 gyroradius、非断熱運動、電位、時間変動、観測応答の影響を含み得る
- Tsunakawa SVM の月面値と同じ estimand だとは、現段階では確認されていない

## 3. KAGUYA 入力を作る手順

全期間 catalog では日ごとに次を行います。

1. PACE ESA1 の raw count と angle/INFO calibration を読む。
2. LMAG の磁場ベクトルと軌道位置を同じ時刻へ補間する。
3. 各10分 bucket について、その中心に最も近い native PACE record を一つ選ぶ。
4. look direction と磁場から pitch angle を計算し、0--180 degree を16 bin に集約する。
5. $\alpha$ と $180^\circ-\alpha$ の対称 bin を組にして0--90 degreeへ折り畳む。
6. $\mathbf B\cdot\mathbf r$ から affected/reference hemisphere を決める。
7. 各時刻を独立に count model へ fit する。
8. SZA を SPICE から計算し、日別 Parquet shard と provenance を Store へ書く。

10分 cadence は10分平均ではありません。各 bucket の代表 record を一つ取る系統標本です。
空の bucket や、pitch/energy 支持が不足する record は解析行または採択候補になりません。

exposure は pitch bin に入った look cell の有効 exposure を合計したものです。PACE reader は
積分時間、geometric factor、および現行 calibration の duty factor を使います。ただし尤度で
識別できるのは対になった $e^a/e^r$ の比であり、絶対 flux ではありません。catalog には
`exposure_mode="calibrated"` を保存します。

PACE telemetry の event count / trash count 補正は `count_correction` で選べます。
`"trash"` は各 energy/polar cell で azimuth count と二つの trash counter の比を取り、
`"event"` は隣接する二 energy channel の全 angular count を対応する event counter に合わせます。
`"event_trash"` は SPEDAS の `/cntcorr` と同じく trash、event の順で両方を適用します。
ER 用の `spn.kaguya.er.pitch_angle_spectrum()` と `pitch_angle_spectra()` は
`"event_trash"` が既定です。低レベルの raw-data API
`spn.kaguya.esa1.counts.pitch_angle_spectrum()` は、補正の有無を利用者が明示できるよう
後方互換の `"none"` を既定に保ちます。

```python
pitch_counts = spn.kaguya.er.pitch_angle_spectra(
    time,
    count_correction="event_trash",
)
```

count 尤度では補正後の小数 count を観測値にしません。raw count $n$ と補正倍率 $m$ を分離し、
有効 exposure を $e/m$ とすることで、$m>0$ のセルでは rate $n/(e/m)=nm/e$ を SPEDAS の
補正 rate に一致させます。event count が0で $m=0$ となるセルはこの表現では有限 exposure と
両立しないため fit から除外し、ER 観測 metadata の `invalid_exposure_count_cells` に記録します。
この表現は event/trash telemetry を既知の保持率として扱うため、telemetry 自体の統計誤差は
現在の尤度に含まれません。`value="energy_flux"` では同じ倍率を値へ直接適用します。

!!! note "ESA1 だけを使うことの制約"
    PACE は三軸安定衛星であり、完全な3次元電子分布には ESA-S1 と ESA-S2 の組が必要です。
    現在の catalog は利用可能な ESA1 look direction を pitch bin へ集約したものです。
    固定18日の相互検証では edge evidence の強弱は連動しましたが、共通1,772時刻のうち両方で
    `good/review` になったのは1件だけでした。ESA2 の座標・半球対応・sensor 応答を監査し、
    sensor 固有 nuisance parameter を持つ joint likelihood を作るまでは単純結合できません。

## 4. Count の統計モデル

### 対称な二つの count を条件付きで比べる

energy $i$、折り畳み pitch $j$ ごとに

$$
n_{ij}=a_{ij}+r_{ij}
$$

を固定して、合計のうち affected 側へ入る確率 $p_{ij}$ を model 化します。真の
exposure 補正済み rate 比を $q_{ij}=\lambda^a_{ij}/\lambda^r_{ij}$ とすると、

$$
\operatorname{logit}(p_{ij})
=\log q_{ij}+\log\frac{e^a_{ij}}{e^r_{ij}}.
$$

この条件付けにより、その cell 全体の明るさを nuisance parameter として一つずつ推定せずに、
hemisphere 間の差へ集中できます。exposure が同じなら $p=q/(1+q)$ です。

例えば exposure が等しい cell で `affected=20`、`reference=40` なら、観測された affected
割合は $20/(20+40)=1/3$ です。両側の exposure が2倍違えば raw count の比だけでは比較できず、
上式の $\log(e^a/e^r)$ で補正します。推定器が energy flux 画像ではなく count と exposure
を別々に要求するのはこのためです。

### Beta-binomial 尤度

単純な binomial だけでは、時間変動、未解像な角度構造、応答誤差による過分散を過小評価し得ます。
そこで

$$
a_{ij}\mid n_{ij},p_{ij},\kappa
\sim \operatorname{BetaBinomial}
\left(n_{ij},\ p_{ij}\kappa,\ (1-p_{ij})\kappa\right)
$$

を使います。$\kappa$ は全 cell で共有する concentration です。大きいほど binomial に近く、
小さいほど余分なばらつきを許します。最適化は元の整数 count に対するこの尤度で行います。
監査図に出す

$$
\log\frac{a_{ij}+0.5}{r_{ij}+0.5}
-\log\frac{e^a_{ij}}{e^r_{ij}}
$$

は可視化と残差診断用であり、擬似 count 比への最小二乗 fit ではありません。

## 5. 境界面のパラメータ化

### 滑らかな transition

有限の pitch bin、角度応答、時間変動のため、実データの境界は完全な step になりません。
SOPRAN は

$$
T_{ij}=\Phi\left(
\frac{\ln\sin^2\alpha_j-\ln s_i}{\sigma_{\ln B}}
\right)
$$

を使います。$\Phi$ は標準正規分布の累積分布関数、$s_i$ は上の loss-cone 境界です。
`sigma_ln_b` が小さいほど鋭い境界になります。

rate 比の面は

$$
\log q_{ij}=\beta_i+A(E_i)T_{ij}
$$

です。$\beta_i$ は energy ごとの baseline で、電子 spectrum 自体の energy 依存を吸収します。
振幅 $A(E_i)\ge 0$ は loss cone の内外で ratio がどれだけ変わるかを表します。

### Contrast model

| `contrast_model` | $A(E)$ | 用途 |
| --- | --- | --- |
| `constant` | 全 energy で一つ | 最も単純で安定 |
| `band` | log-energy 上の Gaussian band + floor | 一部 energy 帯だけ境界が見える場合 |
| `free` | energy ごとに一つ | 柔軟だが parameter が多い感度解析用 |
| `auto` | `constant` と `band` を BIC で比較 | 既定値 |

band model は

$$
A(E)=A_{floor}+(A_{peak}-A_{floor})
\exp\left[-\frac{(\ln E-\ln E_c)^2}{2w^2}\right]
$$

です。$E_c$ は「境界が見えやすい energy 帯」の nuisance parameter です。絶対 spectrum の
cutoff、spacecraft potential、energy calibration shift とは解釈しません。

### Halekas 2008型の全分布fit

#### 正の磁場比と探索範囲

`HalekasFitSettings`、`EffectiveFieldFitSettings`、`BinaryLossConeFitSettings` は
正の $R_m$ を扱い、既定の数値探索範囲は `mirror_ratio_bounds=(0.001, 1000.0)` です。
0・負値・無限大は指定できませんが、任意の有限な正の上下限を設定できます。
たとえば `(0.1, 0.95)` のように全域が1未満の指定も可能です。
従来の制約を使う場合は `(1.001, 1000.0)` を明示してください。
保存済みJSONなどから旧上下限を明示的に読み込む場合、その値は自動変更しません。

ここでの $B_{eff}=R_mB_{sc}$ は境界式の磁場パラメータです。衛星位置を含む経路の
最大磁場や地殻磁場成分そのものとは限りません。$\Delta U=0$、$R_m<1$ では
磁気ミラー境界はありませんが、$\Delta U<0$ なら電位による境界を表現できます。
1未満を許すことは、そこに得られた値を物理的に確定した表面磁場と認定することではありません。
`no_edge` 比較、境界support、品質判定は残します。

Halekasのhard経路は $\log R_m$ の格子512点と電位601点を既定とし、電位候補を
まとめて計算します。最良の格子点の近傍を17 x 17点で2回再探索します。
`hard_refinement_steps=0` で近傍再探索を無効化できます。これは離散格子と局所探索であり、
大域最適性や信頼区間を保証しません。同じ二値マップになるパラメータは区別できません。
probit経路も $\log(R_m-1)$ ではなく $\log R_m$ で最適化します。

global jointでも各観測の $B_{eff}/B_{sc}$ が指定範囲内になるように共通 $B_{eff}$ の上下限を
作り、従来の暗黙の $R_m>1$ 判定を撤去しました。低い $R_m$ と負の電位差の初期値も使います。
S1/S2時系列キャッシュは `global_joint_timeseries_v7` に更新し、旧結果とは分離します。

#### 正規化分布と目的関数

`fit_halekas_distribution()` は、incident側で正規化したreflected/incident比の全2次元分布へ
synthetic distributionを直接当てます。energyごとのedge検出結果は入力に使いません。観測面は

$$
y_{ij}=log\frac{a_{ij}+0.5}{r_{ij}+0.5}
-\log\frac{t^{(a)}_{ij}}{t^{(r)}_{ij}}
$$

です。既定のsharp modelは、物理境界$s(E_i)$に対して

$$
\hat q_{ij}=
\begin{cases}
f_{back} & \sin^2\alpha_j < s(E_i),\\
1 & \sin^2\alpha_j \ge s(E_i),
\end{cases}
\qquad f_{back}=0.1
$$

とします。energy別baseline、共通pitch profile、energy局在Gaussian contrastは持ちません。
$(R_m,\Delta U_{eff})$のgrid全体について

$$
\mathrm{RSS}=\sum_{ij}\left(y_{ij}-\log\hat q_{ij}\right)^2
$$

を計算し、最小のsynthetic distributionを採用します。これはHalekas et al. (2008)の
「正規化した観測・synthetic fluxの対数を全分布で最小二乗比較する」loss-cone部分に対応します。

`HalekasFitSettings(edge_transition="probit")`では、同じ$0.1$--$1$分布の境界だけを

$$
T_{ij}=\Phi\left(
\frac{\ln\sin^2\alpha_j-\ln s(E_i)}{\sigma_{\ln\sin^2\alpha}}
\right),
\qquad
\hat q_{ij}=f_{back}+(1-f_{back})T_{ij}
$$

へ置換します。hard解を初期値として$R_m$、$\Delta U_{eff}$、
$\sigma_{\ln\sin^2\alpha}$を同時最適化します。従ってhardとsmoothの差は境界幅だけです。
`hard_to_smooth_delta_bic`は、同じcell・同じGaussian RSSについて、幅1 parameterの追加に
見合う改善かを$\mathrm{BIC}_{hard}-\mathrm{BIC}_{smooth}$で表します。幅を採用するには
既定の目安として6以上、かつ`at_bounds`が空であることを要求します。特に幅上限への張り付きは、
sharp edgeの有限幅ではなく、synthetic distributionが説明できない広いpitch勾配を吸収した可能性を
示します。

Halekas et al. (2008)の最終synthetic distributionは上向きsecondary-electron beamも加えます。
論文本文だけではbeamの角度幅・energy幅・振幅の一意なパラメータ化を再現できないため、現在の
`fit_halekas_distribution()`はloss-cone成分のみです。beamを無理に自由Gaussianとして加えると
$\Delta U$との同定性を壊すため、KAGUYAで方向・energy responseを検証してから別成分として追加します。

### 旧binary surface prototype

`fit_binary_loss_cone()` は、Halekas et al. (2008) の全energy--pitch面を使う方法に対応した
初期prototypeです。energyごとにedgeと幅を独立fitするのではなく、物理式から作る一つのbinary mask

$$
H_{ij}=
\begin{cases}
0 & \sin^2\alpha_j < s(E_i),\\
1 & \sin^2\alpha_j \ge s(E_i)
\end{cases}
$$

を面全体へ同時に当てます。KAGUYAのpaired ratioには全energyでほぼ共通するpitch勾配が残るため、

$$
\log q_{ij}=\beta_i+\gamma_j+A_{band}(E_i)H_{ij}
$$

とし、energy offset $\beta_i$ と共通pitch profile $\gamma_j$ をnuisance parameterとして先に
profileします。$A_{band}(E)$ はlog-energy上のGaussian bandです。これにより、広い共通pitch勾配と、
一部energyだけに現れる鋭いloss coneを分離します。

目的関数は0.5 count補正とexposure補正を施したlog rate ratio面の最小二乗で、`no_edge`、
`mirror_only`、`electrostatic`をBICで比較します。境界幅$\sigma_{\ln B}$は持たず、有限pitch bin上の
hard maskとして評価します。従って現在のbeta-binomial smooth fitとは推定対象と尤度が異なり、
自動置換せず独立した感度解析として返します。二次電子beam成分はまだ実装していません。
binaryなのは$H_{ij}$と各energy行のedge成分$A_{band}(E_i)H_{ij}$です。返される
`fitted_log_ratio`は$\beta_i$と$\gamma_j$を戻した総再構成面なので、それ自体は二値ではありません。
論文型の基準fitには自由背景を持たない`fit_halekas_distribution()`を使い、このprototypeは背景感度を
調べる比較対象として残します。

## 6. Nested model と BIC

この節の段階選択は、対称 pitch bin を先に組にする `fit_effective_field()` の規則です。
S1/S2 raw count を分離したまま扱う production の `fit_global_joint_effective_field()` では、
`mirror_only` と `electrostatic` をそれぞれ `no_edge` と直接比較します。mirror が支持された場合だけ、
electrostatic はさらに mirror に対する BIC 改善も必要です。electrostatic が品質 gate に失敗し、
mirror が支持されていれば mirror へ戻ります。

同じ有効 cell に三つの model を当てます。

| model | pitch 依存 | free な物理 parameter |
| --- | --- | --- |
| `no_edge` | なし | なし |
| `mirror_only` | あり | $R_m,\sigma_{\ln B}$ |
| `electrostatic` | あり | $R_m,\sigma_{\ln B},\Delta U_{eff}$ |

各 model には energy ごとの $\beta_i$ と concentration もあります。edge model には選択した
contrast parameter が加わります。最適化は bound 付き L-BFGS-B、既定3 start、最大4000 iteration
で、最大尤度の解を採用します。

model complexity は

$$
\mathrm{BIC}=k\ln N-2\ln\hat L
$$

で罰します。$k$ は parameter 数、$N$ は有効 count-pair cell 数です。単純 model からの
改善を `BIC_simple - BIC_complex` と定義します。edge 自体、transition width、contrast band
には既定で6以上、mirror-only から electrostatic curvature への選択には1以上を要求します。

1. `mirror_only` が `no_edge` より6以上改善しなければ `no_edge`。
2. 改善すれば edge 候補にする。
3. `electrostatic` が `mirror_only` よりさらに1以上改善した場合に electrostatic を選ぶ。
4. `contrast_model="auto"` では、band が constant より6以上改善した場合だけ band を選ぶ。

BIC は真の物理 model の証明ではありません。同じ候補集合の中で、改善が追加 parameter に
見合うかを判定する規則です。

`spectrum_smoothness>0`ではincident spectrumの平滑化penalty付き解を使うため、返すBICは厳密な
非正則化MLEのBICではありません。production population評価は`0.0`を使います。平滑化を有効にした
感度解析ではBIC差を近似診断として扱い、held-out likelihoodを併記します。

## 7. 採択 gate

optimizer が数値的に終了しても、そのまま `B_eff` を返しません。既定の gate は次の通りです。

| gate | 既定値 | 失敗時の主な `reason` |
| --- | --- | --- |
| retained energy | 3 bin 以上 | `insufficient_energy_support` |
| pitch support | sensorごとに窓全体で、各 retained energy に6 bin 以上 | energy bin を除外 |
| total count | 100以上 | `insufficient_total_counts` |
| edge evidence | no-edge に対する BIC 改善6以上 | `no_edge_evidence` |
| parameter bounds | $R_m,\Delta U,\sigma$ が端でない | `edge_parameter_at_bound` |
| band bounds | excess、center、width が端でない | `contrast_band_parameter_at_bound` |
| boundary bracket | energy の80%以上で境界両側に1 bin以上 | `insufficient_boundary_bracketing` |
| strict bracket | energy の50%以上で境界両側に2 bin以上 | 同上 |

boundary bracketing は、推定境界が実測 pitch 範囲の外側へ逃げた解を除くために重要です。
同じpitch binを複数recordで観測してもbin数は水増しせず、窓内の固有binとして数えます。
electrostatic 候補が gate に失敗しても、mirror-only 候補が通れば mirror-only へ戻します。

`success=True` は optimizer/model fit が計算できたこと、`edge_supported=True` は物理 edge の
採択 gate を通ったことです。解析で使うときは `success` だけではなく `edge_supported` と
`quality_grade` を確認してください。

## 8. Predictive quality grade

edge を採択した後、観測した二次元 count-ratio 面をどの程度再現するかで grade を付けます。

| metric | `good` | `review` | 見ているもの |
| --- | ---: | ---: | --- |
| log-ratio residual の絶対値 p90 | 2.0以下 | 2.5以下 | 大きな残差の裾 |
| pitch pattern correlation | 0.75以上 | 0.50以上 | energy ごとの baseline を除いた形 |
| pitch pattern NRMSE | 0.75以下 | 1.00以下 | pitch 構造の相対誤差 |
| 3-sigma standardized residual 内の割合 | 0.90以上 | 0.75以上 | count 尤度に対する外れ値 |

全条件を `good` 閾値で満たせば `good`、全条件を `review` 閾値で満たせば `review`、edge は
採択されたがそれ以外なら `poor` です。edge 自体を採択しなかった行は `reject` です。

- `good`: 主解析。`good` のみの感度図も作る。
- `review`: 主解析では `good` と合わせるが、結果差を確認する。
- `poor`: 監査・感度解析用。既定の地図へ混ぜない。
- `reject`: `mirror_ratio` と `effective_field` は null。

これらの閾値は現在の監査 panel に合わせた運用値であり、独立な ground truth から学習した
確率 calibration ではありません。

## 9. Profile-likelihood 区間

通常の `fit(...)` は採択した $\log R_m$ を固定した grid 上で、他 parameter を再最適化します。
最尤点からの deviance

$$
2\{\ln\hat L-\ln L(R_m)\}=3.84146
$$

との交点を1自由度の95% profile-likelihood interval とします。探索範囲や global bound までに
交点がない場合は `profile_truncated=True` です。

!!! warning "全期間 catalog の例外"
    `EffectiveFieldFitSettings` の通常既定値は `profile_likelihood=True` ですが、日別 archive
    builder の既定値は計算量を抑えるため `False` です。そのため主 archive に interval は
    ありませんが、別 validation artifact では accepted 2,470件を全て再計算しています。
    807件 (32.67%) は探索範囲内で95%境界へ達せず `profile_truncated=True` でした。点推定の
    分布を不確かさの分布と取り違えないでください。

## 10. Energy-ratio step は別診断

全 pitch に共通する energy 方向の段差を mirror edge と分離するため、選択 model の baseline
$\beta(E)$ に事後的な change point を当てます。

$$
\beta(E)=c_0+c_1\ln E+s\,\mathbf 1(E\ge E_c).
$$

両側に3 energy bin 以上あり、step model の BIC が6以上改善した場合に
`energy_ratio_step_supported=True` です。この診断は edge の採否には使いません。
`energy_ratio_step_center` は affected/reference 比の段差であり、絶対 spectrum の cutoff や
電位の推定値ではありません。全期間では accepted 2,470件中1,847件に step があるため、
step を除いた623件との比較が必須です。

## 11. API と処理の擬似コード

### Global FOV と folded 診断面

productionのglobal joint fitでは、S1/S2をfit前に平均しません。fit後の診断面だけ、次の順序で
構築します。

1. sensor固有のenergy/pitch binを、bin overlapで共通の0--180 degree global FOVへ移す。
2. raw count、background/dead-time補正count、通常のexposure、gainとincident spectrumを含む
   normalized exposureを別々に加算する。
3. global FOVの$α$と$180^\circ-α$をaffected/referenceとして対応付け、0--90 degreeへfoldする。
4. 低countでも捨てず、Jeffreys Poisson-rate posteriorからlog rate ratioと標準偏差を計算する。

affected/referenceの補正countの非負部分を$N_A,N_R$、normalized exposureを$Q_A,Q_R$、prior countを
$a=1/2$とすると、表示する観測面は

$$
L_{obs}=\psi(N_A+a)-\log Q_A-\psi(N_R+a)+\log Q_R
$$

です。標準偏差は

$$
\sigma_L=\sqrt{\psi_1(N_A+a)+\psi_1(N_R+a)}
$$

です。`GlobalNormalizedFlux.reliable`は既定で合計5 raw count以上かつposterior標準偏差0.5 dex以下を
示しますが、それ以外のcellもposterior値と不確かさを保持します。この閾値はfitへの採否条件では
ありません。

有限binをoverlap比で小数配分する場合と、background/dead-time補正を行う場合、これは表示用の
quasi-posteriorです。標準偏差はPoisson samplingのみを含み、negative-binomial overdispersionや
分割先cell間の共分散は含みません。符号付きの補正countは`GlobalFullFOV.corrected_counts`にも別途
保存します。

```python
import sopran as spn

time = spn.period("2008-08-02T00:00:00Z", "2008-08-02T00:10:00Z")
magnetic_field = spn.kaguya.lmag.magnetic_field.load(time)
position = spn.kaguya.orbit.position.load(time)
pitch_counts = spn.kaguya.esa1.counts.pitch_angle_spectrum(
    time,
    magnetic_field=magnetic_field,
    pitch_bins=16,
)

settings = spn.EffectiveFieldFitSettings(
    contrast_model="auto",
    spacecraft_potential_eV=0.0,
    profile_likelihood=True,
)
fits = spn.kaguya.er.effective_field.fit(
    pitch_counts,
    magnetic_field=magnetic_field,
    position=position,
    affected_side="auto",
    settings=settings,
)

accepted = fits.to_pandas().query("quality_grade in ['good', 'review']")
```

概念的には次の処理です。

```text
for each timestamp:
    construct symmetric affected/reference count pairs
    discard unsupported energy rows
    fit no_edge
    fit hard mirror/electrostatic candidates first
    screen contrast-band and beam additions with nuisance parameters fixed
    refine only screened candidates that can improve BIC
    select by nested BIC improvements
    reject critical bound hits and unbracketed boundaries
    compute predictive diagnostics and quality grade
    optionally profile mirror_ratio
    diagnose a separate energy-ratio step
    emit B_eff only when an edge model survives the gates
```

production の既定は Rust backend を使える `edge_transition="hard"` です。境界幅を含む
smooth fit は現在 Python 実装で大幅に重いため、感度解析を行う場合だけ
`edge_transition="auto"` または `"smooth"` を明示します。

全期間の日別 catalog は次で構築します。

```python
catalog = spn.kaguya.er.effective_field.build_archive(
    cadence="10min",
    pitch_bins=16,
    workers=8,
)
fits = catalog.scan()
```

### Global joint fit の帯域外コントラストと探索

`global_joint` の band contrast は、帯域外の減少量 `contrast_floor` と
エネルギー局在成分 `contrast_excess` を分けます。`contrast_floor=0` は
「帯域外では減少を要求しない」という有効な解です。既定の下限0への到達は
screen・contrast 選択・最終 quality 判定のすべてで許容します。
`at_bounds` には診断として残しますが、floor 上限、excess、center、width、
物理パラメータの bound 到達は引き続き棄却対象です。

constant 解が quality 判定を通らない場合、band の hard 候補の再探索は
`contrast_refine_optimizer_starts` と `effective_field.optimizer_starts` の
大きい方を使います。`edge_transition="auto"` で追加する smooth 候補は
引き続き `smooth_refine_optimizer_starts` などの専用設定を使います。
複数開始点を指定した seeded fit では、引き継いだ解に
加えて標準初期値を含め、残りの開始点も標準初期値から作ります。
1 start の高速探索では局所解の見落としが残るため、疑わしい境界は
複数開始点による再評価が必要です。

## 12. 解釈の境界

### 現在言えること

- ある時刻の二次元 paired-count 面に、選択した loss-cone-like boundary model が支持された。
- `mirror_ratio` はその境界位置を衛星磁場に対する比として表す。
- `B_eff` は同じ仮定の下で $R_mB_{sc}$ と計算した scalar effective field である。
- `quality_grade` は観測面の再現度に基づく候補選別である。

### まだ言えないこと

- `B_eff` が radial subpoint の月面磁場強度そのものである。
- `DeltaU_eff` や energy step が月面電位そのものである。
- accepted fraction が磁気 anomaly の発生率である。
- 境界表示付き旧監査の95%が precision、accuracy、または全時刻に対する recall である。
- 10分 catalog が native cadence の全観測を代表する。

同じ標本を境界なしで再監査すると二値一致は58.2%、Cohen's kappa は0.074でした。また、10分
accepted 40件のうち別の周辺2分 recordでも残ったのは15件です。主な未モデル化要因は、footpoint
と外部場の不確かさ、有限 gyroradius と非断熱運動、太陽風・wake・magnetotail の plasma regime、
ESA1/ESA2 の角度応答、spacecraft potential、時間相関です。
[Halekas et al. (2010)](https://doi.org/10.1029/2009JE003516) は、小空間スケールの磁化に
対する電子反射法の感度低下を particle tracing で示しています。このため断熱式だけで
「真の月面磁場」へ直結させないことが重要です。

## 参考文献

- Saito et al. (2009), [Low Energy Charged Particle Measurement by MAP-PACE Onboard KAGUYA](https://doi.org/10.2322/tstj.7.Tk_7)
- Halekas et al. (2008), [Lunar Prospector observations of the electrostatic potential of the lunar surface and its response to incident currents](https://doi.org/10.1029/2008JA013194)
- Halekas et al. (2010), [How strong are lunar crustal magnetic fields at the surface? Considerations from a reexamination of the electron reflectometry technique](https://doi.org/10.1029/2009JE003516)
- Kato et al. (2017), [Global mapping of the lunar magnetic anomalies by electron reflection method](https://www2.jpgu.org/meeting/2017/PDF2017/P-PS08_all_e.pdf)
