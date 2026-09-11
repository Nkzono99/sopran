# 電子反射法と loss cone 推定手法の外部調査

この文書は、月面 electron reflectometry (ER) の loss cone から磁場と電位差を推定する方法を
見直し、SOPRAN の次期推定器を設計するための外部調査です。2026-08-25 時点で確認できた
一次論文と公式データ文書を対象にしています。

!!! abstract "先に結論"
    SOPRAN の第一候補は、energy ごとの edge を先に検出する二段階法ではなく、
    **pitch--energy の全 count 面を、装置応答込みの低次元 forward model で直接推定する方法**です。
    Halekas et al. (2008) の hard binary loss cone + secondary beam を再現可能な基準にし、
    production model では count 尤度、有限遷移、ESA-S1/S2 固有応答、外れ値成分を加えます。
    時系列は分布を単純平均せず、隣接 record の $R_m$ を部分共有する階層モデルとして使います。

## 1. 調査した問い

1. loss cone 境界は過去にどのように推定されてきたか。
2. Halekas et al. (2008) の全分布 fit 以外に、どのような forward model があるか。
3. hard step ではない遷移幅や loss cone 内の残存 flux に物理的意味があるか。
4. KAGUYA/PACE で $B_{eff}$ と $\Delta U$ をよりロバストに同定するには何が必要か。
5. 時系列と ESA-S1/S2 をどう統合すべきか。

## 2. 文献で使われてきた推定方法

### 2.1 energy ごとの step-function fit

Lunar Prospector の標準 derived product は、energy channel ごとの pitch-angle distribution に
step function を fit し、cutoff angle $\alpha_c$ と統計誤差を保存しています。200、220、340、
520、590 eV の各 file が独立です。cutoff が不安定な場合に使える補助量として、反射 flux と
入射 flux の比である effective reflection coefficient も保存されています。

この方法は単純で監査しやすい一方、次の情報を捨てます。

- energy 間で共有される $R_m$ と $\Delta U$ の制約
- count の大小と exposure の違い
- secondary beam、backscatter、連続的な遷移
- edge が弱い energy bin から得られる弱い証拠

Halekas et al. (2003) は三つの energy で step edge を求めた後、断熱式へ fit しています。
非断熱性が強い simulation では cutoff 自体が不安定になり、複数 run の平均が必要になりました。
これは edge-first 法の誤差が後段へ伝播する具体例です。

### 2.2 reflection coefficient

角度分解能が不足する場合、入射分布がほぼ等方的という条件で、全反射 flux の比から
$R=|\cos\alpha_c|$ を推定できます。Apollo subsatellite では有効でしたが、solar-wind strahl、
beam、conic のある KAGUYA 分布へ無条件に適用できません。これは主推定器ではなく、
高角度分解能が得られない record の補助診断に適しています。

### 2.3 Halekas et al. (2008) の全2次元分布 fit

Halekas et al. (2008) は、reflected 側と incident 側を incident 分布で正規化し、
energy-dependent loss cone

$$
\sin^2\alpha_c(E)
=\frac{B_{sc}}{B_m}\left(1+\frac{eU_m}{E}\right)
$$

から hard synthetic distribution を作りました。さらに、surface potential に対応する energy
へ上向き secondary-electron beam を加え、観測と synthetic distribution の**全 energy--pitch
面の対数 flux**について最小二乗値を計算し、磁場比と電位を grid search しています。

重要なのは、これは energy ごとの edge 点を fit する方法ではないことです。境界が見えにくい
cell も含む全分布が、一組の物理 parameter を制約します。また同論文は、次を推定の一部として
明示しています。

- spacecraft potential の補正
- instrument energy resolution の convolution
- secondary beam と loss-cone curvature の整合
- positive potential、小さな potential、非単調 sheath に対する適用限界

論文の synthetic loss cone は sharp ですが、観測境界は modest slope を持ちます。著者らは
spacecraft sheath を通る際の nongyrotropy や波動による smoothing を候補に挙げています。

### 2.4 ARTEMIS と全分布の自己整合性

Halekas et al. (2011) の ARTEMIS 解析も、incident 分布で正規化した全分布に、
energy-dependent loss cone と上向き表面起源 beam を含む synthetic distribution を当て、
電位差と磁場比を同時に制約しています。beam energy は $\Delta U$ の独立に近い marker になるため、
loss-cone curvature だけより同定性が高くなります。

### 2.5 火星の kinetic transport forward model

火星では吸収面が固体表面ではなく、約150--300 kmの大気に分布します。Mitchell et al. (2007) と
Lillis et al. (2008) は、電子の螺旋軌道、磁気 mirror、静電加減速、neutral collision の
energy-dependent cross section、散乱・backscatter を追う kinetic transport model を使い、
PAD 全体から磁場を推定しました。

これは月面の binary model を単に滑らかにしたものではありません。遷移形状そのものが、
neutral density profile、field profile、potential profile に依存する forward response です。
Lillis et al. (2018) は backscatter を transport model で差し引き、複数 energy の loss cone を
同時 fit して磁場比と field-aligned potential を求めています。約1000万候補のうち reliable fit は
約40%で、低 count、pitch coverage 不足、nongyrotropy を明示的な失敗理由にしています。

月面に大気輸送を移植する必要はありませんが、**物理 parameter -> 2次元観測面**という forward
model の設計と、検出不能領域による selection bias を評価する考え方は直接参考になります。

### 2.6 particle tracing による response calibration

Halekas et al. (2010) は、複雑な短波長 magnetization から電子軌道を追跡し、実観測と同じ角度 bin
へ落として、同じ ER 解析を synthetic data に適用しました。その結果、ER はおよそ10 km以上の
coherent magnetization には応答する一方、それより細かい構造では surface field を大幅に
過小評価し得ることを示しました。

したがって $B_{eff}$ の統計誤差を小さくするだけでは、真の surface field への accuracy は保証
できません。SVM や仮想 magnetization から particle tracing した synthetic observation に
推定器を戻す end-to-end calibration が必要です。

## 3. loss-cone transition は何を意味するか

遷移幅は情報を持ち得ますが、単一の物理量ではありません。観測幅には少なくとも次が混在します。

| 成分 | 期待される特徴 |
| --- | --- |
| pitch/energy bin と detector response | calibration から既知の convolution として与えられる |
| 磁場方向誤差 | pitch 全体をずらし、ESA-S1/S2 で相関する |
| record 内の境界変動 | 全 energy に相関した broadening になりやすい |
| 空間平均 | 衛星移動と footprint 内の $R_m$ 分布を混合する |
| finite gyroradius / nonadiabaticity | energy、tip angle、磁場scale長へ系統依存する |
| wave-particle scattering | energy と pitch に選択的で、loss cone を部分的に埋める |
| surface backscatter / secondary electron | loss cone 内の floor や局在 beam を作る |
| incident anisotropy / moving-frame effect | hemisphere 比だけでは消えず、conic や曲率に見える |

Halekas et al. (2003) は、double-layer scale height が electron gyroradius と同程度以下になると、
tip angle と energy に依存する非断熱応答が生じることを particle tracing で示しています。
したがって、既知の装置幅を除いた transition の $E$ と tip angle 依存は、scale height や
magnetization scale の診断候補です。ただし単純な共通 $\sigma$ だけでは両者を分離できません。

Halekas et al. (2012) は、個々の loss cone は median 分布より鋭く、平均操作自体が境界を
smear すること、完全に鋭い境界は観測されないことを報告しています。また、非断熱反射、
moving-obstacle/Fermi effect、conic、beam、frame transformation の不確かさが同じ分布へ現れます。

地球磁気圏の loss-cone 研究では、inside/outside flux 比や遷移勾配は pitch-angle diffusion の
強さを表す量として使われます。弱拡散では loss cone が空に近く勾配が残り、強拡散では内部まで
分布が埋まります。Arase の観測でも、ECH wave に対応する energy--pitch 選択的な散乱が
quasi-linear diffusion の予測と一致しています。月面ERへ同じ拡散式をそのまま適用することは
できませんが、transition を「境界位置の誤差」だけでなく、別の物理診断として保持すべき根拠に
なります。

### 遷移幅を使うための条件

観測座標を

$$
x_{ijt}=\ln\sin^2\alpha_{jt}-\ln s(E_i;R_{m,t},\Delta U_t)
$$

とし、まず既知の angular/energy response を forward model 内で convolution します。その後に
残る幅を、例えば

$$
\sigma_{obs}^2(E,t)
\simeq \sigma_{inst}^2+\sigma_{Bdir}^2+\sigma_{jitter}^2+\sigma_{phys}^2(E,t)
$$

として診断できます。この二乗和は各成分を近似的に Gaussian とみなす場合の作業仮説であり、
最終物理式ではありません。特に temporal jitter は一つの自由な $\sigma$ へ押し込まず、時系列の
latent boundary として表す方が識別しやすくなります。

## 4. SOPRAN に推奨する production model

### 4.1 観測量は raw count と exposure

擬似 count を加えた log ratio の無重み最小二乗は、低 count cell と高 count cell を同じ重みで
扱います。production model は現在の beta-binomial の考え方を保ち、各 cell で

$$
a_{ijst}\mid n_{ijst},p_{ijst},\kappa
\sim \operatorname{BetaBinomial}
\left(n_{ijst},p_{ijst}\kappa,(1-p_{ijst})\kappa\right)
$$

とします。$s$ は sensor、$t$ は record です。exposure 比を offset として入れれば、incident
intensity を cell ごとに明示推定せず affected/reference の差を使えます。

### 4.2 2次元 forward surface

境界面は全 cell で共有する低次元物理式から作り、rate ratio は概念的に

$$
\log q_{ijst}
=b_{is}(t)+g_{js}
-A_i(t)\{1-T(x_{ijst})\}
+G_{beam}(E_i,\alpha_j;t,s)
$$

とします。

- $b_{is}(t)$: energy、sensor、時刻ごとの緩い baseline
- $g_{js}$: sensor 固有の残留 pitch response
- $A_i(t)$: loss-cone contrast。低次元 spline または強く正則化した band
- $T$: hard step または response-convolved finite transition
- $G_{beam}$: 独立な根拠がある場合だけ有効にする secondary beam

$A_i$ を energy ごとに完全自由にすると境界を消してしまい、$g_{js}$ を完全自由にすると pitch
edge を吸収します。nuisance surface は低rank・smooth・zero-sum 制約を持たせ、null model と
posterior predictive performance を比較する必要があります。

### 4.3 ESA-S1/S2 の joint likelihood

ESA-S1 と ESA-S2 を画像として先に結合せず、同じ $R_{m,t}$、$\Delta U_t$、transition physics を
共有しながら、sensor ごとに次を分けます。

- look direction と pitch response matrix
- exposure、gain、dead-time、background
- energy response と energy offset
- residual pitch baseline

これにより「両 sensor が同じ境界を支持するか」を parameter 一致ではなく、共通 latent state に
対する尤度として評価できます。一方の coverage がない cell は欠測として自然に除外します。

各 binned cell の期待 count は bin center だけで評価せず、有限 energy/pitch 幅にわたって

$$
\lambda_{sij}
=X_{sij}G_s
\int_{\Delta E_i}\int_{\Delta\alpha_j}
I(E)q(E,\alpha;R_m,\Delta U)R_{sij}(E,\alpha)
\,d\alpha\,dE
$$

と平均します。現実装の `finite_bin_quadrature` は $R_{sij}$ を $dE\,d\alpha$ に対するbin内top-hatとする
第一近似で、energy binは既定8点、smooth transitionのpitch binは既定64点のGauss--Legendre求積で
積分します。spacecraft potentialをまたぐenergy binは候補間で共通に除外します。hard transitionは
pitch binと透過領域の重なりを解析的に積分します。これはcenter評価より有限bin幅を正しく扱いますが、
detector lookごとの測定済みresponse matrixそのものではありません。

production forward model では離散化後の source count を

$$
\nu_{sij}=X_{sij}G_s
\sum_{kl}R^{(s)}_{ij,kl}I(E_k)
\left[q_{loss}(E_k,\alpha_l)+q_{beam}(E_k,\alpha_l)\right]
+B^{known}_{sij}+r^{bg}_sL_{sij}
$$

とし、非麻痺型 dead-time を

$$
\lambda_{sij}=\frac{\nu_{sij}}
{1+\tau_s\nu_{sij}/L_{sij}}
$$

で count 尤度の直前に適用します。$L_{sij}$ は積分時間と、その pitch cell に入った有効 detector
look 数の積です。明示的な `background_model="sensor_constant"` は sensor ごとの $r^{bg}_s$ を推定し、
既知の background 面がある場合は既定設定のまま $B^{known}_{sij}$ として別に渡せます。未知の定数
background は incident spectrum と同定しにくいため既定では推定しません。診断面を作る際は同じ式を逆変換し、
background を引いてから incident spectrum と gain を除きます。

affected/reference の絶対levelを1へ固定すると、両半球のpopulation差やphotoelectronにより
ratio全体が1を超えた分布上の相対的loss coneを表現できません。現実装は全候補に共通して

$$
q_{loss}(E,\alpha)=
\begin{cases}
\exp\left[b(E)-A(E)\{1-T(E,\alpha)\}\right], & \text{affected},\\
1, & \text{reference}
\end{cases}
$$

を使います。$b(E)$ は既定4 knotのlog-energy線形補間で、両半球にcount supportがあるenergy範囲へ
knotを置きます。`no_edge`にも同じ$b(E)$を持たせるため、edgeのBIC改善はbaselineでは説明できない
pitch依存境界だけを評価します。

secondary beam は affected 側だけに加える正の成分

$$
q_{beam}(E,\alpha)=A_b
\exp\left[-\frac{(\ln E-\ln E_b)^2}{2\sigma_E^2}
-\frac{\alpha^2}{2\sigma_\alpha^2}\right]
$$

です。既定の `secondary_beam="auto"` は beam 無し／有りを別々に fit し、
$\Delta\mathrm{BIC}\ge10$ かつ beam parameter が bound にない場合だけ採用します。beam の完全探索は
高コストですが、beam を強制せず候補として常に評価します。高速な screening で beam を評価しない
場合だけ `secondary_beam="off"` を明示します。したがって、loss cone の不足を常に beam で埋める
構成ではありません。

production の model 選択では、`mirror_only` と `electrostatic` をそれぞれ `no_edge` と
直接比較します。`mirror_only` が支持された場合、`electrostatic` はさらに mirror に対する既定6以上の
BIC 改善を必要とします。mirror が支持されない場合は electrostatic と no-edge の直接比較で判定します。
これにより、一定境界では表せない明瞭な energy-dependent loss cone を段階選択だけで棄却することを
避けます。constant/band contrast familyもmirrorの選択をelectrostaticへ流用せず、各境界model内で
quality gateを通った候補から独立に選びます。

KAGUYA PACE INFO に含まれる energy/look ごとの geometric factor と efficiency は $X_{sij}$ に
集約済みで、これは実測の対角 response です。公開されている現在の校正表には非対角の energy/pitch
redistribution matrix と dead-time 定数がないため、既定では前者を identity、後者を 0 とします。
`detector_response_matrix` と `dead_time_seconds` を与えれば同じ forward model にそのまま入ります。
不明な mission 定数を推定値として偽装しないことと、実装上扱えないことは区別しています。

### 4.4 hard model と smooth model の役割

推奨する model ladder は次です。

1. `null`: sensor baseline のみ。
2. `hard_loss_cone`: Halekas 型 binary boundary。
3. `hard_loss_cone_beam`: paper reproduction 用。
4. `response_convolved_loss_cone`: 既知の装置幅のみ。
5. `finite_transition`: 追加の residual width または filling fraction。
6. `nonadiabatic_forward`: particle-tracing emulator を使う研究 model。

最初から最も柔軟な model を使うと、磁場、電位、contrast、幅、beam の同定性を失います。
hard model は物理的真実と決めつけるためではなく、追加構造に必要な証拠を測る基準です。

現行の production global joint fit は高速な `edge_transition="hard"` を既定とします。
`edge_transition="auto"` を明示した感度解析では、`hard` と `smooth` を同じ raw-count 尤度で
別々に fit して BIC で選びます。`hard` は潜在分布でのみ二値であり、
ESA energy bin内のsample積分とpitch binとの解析的な重なり積分、detector response matrixを通してから期待countを
計算します。したがって、観測面では有限分解能に応じた部分透過になります。`smooth` だけが
追加の $\sigma_{\ln B}$ を持つため、分解能未満の幅を下限値として無理に推定せず、必要な証拠が
ある場合だけ有限transitionを採択します。選択結果は `transition_model` と
`smooth_transition_delta_bic` に残り、後者が正ならsmooth、負ならhardを支持します。hard採択時の
`sigma_ln_b` は未推定なので `None` です。folded診断面もbin centerでモデルを再評価せず、各sensorの
response畳み込み済みforward予測をexposure重みで集約します。

`edge_transition="auto"` の感度解析では、hardを4初期値で先にfitし、そのnuisance解を固定した
8点pitch求積のsmooth screenを行います。screenでsmoothがhardを上回る場合だけ、64点求積を
screen解から1初期値でrefineします。
contrast bandでは8点pitch求積でcontrastパラメータと境界の物理パラメータを同時にscreenします。
境界を固定すると既知のbandを見落とすケースがあるためです。secondary beamはbeamパラメータだけを
screenし、有望な候補だけ全パラメータをrefineします。screen BICと厳密BICは
`*_screen_delta_bic` と通常の `*_delta_bic` に分け、
`*_refined` で厳密refineの実施有無を記録します。

## 5. 時系列から情報を吸い上げる方法

### 5.1 単純平均を避ける

複数 record の count 面を先に平均すると、$R_m$ や $\Delta U$ が変化しただけでも人工的に広い
transition ができます。各 record の尤度は保持し、latent parameter を部分共有します。

### 5.2 dynamic hierarchical model

短い連続 window で、例えば

$$
\log R_{m,t}=\log R_{m,t-1}+\epsilon^{(R)}_t,
\qquad
\Delta U_t=\Delta U_{t-1}+\epsilon^{(U)}_t
$$

と置きます。両者の process scale は別に推定または calibration します。月面磁場に由来する
$R_m$ は footprint 距離に対して滑らか、plasma/sheath に由来する $\Delta U$ と beam はより速く
変化し得るため、時間だけでなく along-track distance と plasma regime を使う方が自然です。

推奨する構成は次です。

- $R_m$: along-track spatial GP、random walk、または piecewise smooth state
- $\Delta U$: 別 timescale の state
- beam amplitude と incident spectrum: record ごとの nuisance、弱い時間 regularization
- sensor gain: orbit/day 単位で共有
- outlier: contamination mixture または heavy-tailed random effect
- regime: solar wind、wake、magnetotail、plasma sheet を外部分類し、必要なら HMM で遷移

現在の10分 bucket の代表1 record は、持続性を使わず aliasing を起こします。まず native cadence
近傍の数 record を joint fit し、held-out record を予測できる window 長を選ぶべきです。
window 長は固定10分から始めず、footprint 移動距離、局所 field scale、観測 cadence の感度解析で
決めます。

先行解析で使われる約16秒積分は、空間的・時間的な境界変化を過度に平均しない初期基準として
妥当です。ただし16秒を全energy/pitch cellの最小count条件に置き換えてはいけません。単一cellの
0 countも尤度への情報であり、短い積分はcount posteriorまたは複数recordの階層尤度で不確かさを
大きく表現します。16、32、64秒を同じ軌道区間で比較し、held-out likelihoodと$R_m$の時間安定性で
最終積分時間を決めます。

`pitch_angle_spectra(..., cadence_seconds=...)`は各時間bucketから代表native recordを1件選ぶ
decimationであり、指定秒数のcount積算ではありません。論文型の短時間積分には
`effective_field.fit_timeseries(..., integration="16s")`を使います。この経路は各native recordを
独立した尤度項として保持し、energy sweepの半binずれを保持したままS1/S2 joint likelihoodを
評価します。現段階では窓内で$R_m$、$\Delta U$、incident spectrum、S1/S2別のsensor nuisanceが
一定という仮定です。

### 5.3 時系列を使う利点

- 単発の low-count edge を隣接 record の弱い証拠で安定化できる
- 一時的な beam/波動と持続する mirror boundary を分けられる
- transition のうち boundary jitter による成分を直接推定できる
- ESA-S1/S2 の片側 coverage 不足を前後時刻から補える
- accepted/rejected の二値 gate ではなく、連続した不確かさを保存できる

一方、過度な smoothing は実在する小規模磁場を消します。process scale は地図を滑らかに見せる
目的で決めず、synthetic injection と held-out predictive likelihood で選びます。

## 6. ロバストな磁場推定に必要な検証

### 6.1 paper reproduction

最初に Halekas et al. (2008) に近い hard binary + beam + response convolution を独立 backend として
固定します。これは production の最終形ではなく、既知手法を再現する benchmark です。

### 6.2 synthetic recovery

既知の $R_m$ と $\Delta U$ から、少なくとも次を変えた count data を生成します。

- count level、zero count、overdispersion
- pitch/energy response と欠測 coverage
- hard/smooth edge、backscatter、beam
- sensor gain mismatch と energy offset
- $R_m$/$\Delta U$ の時間変動
- incident anisotropy と共通 pitch gradient

parameter bias、interval coverage、false-positive rate、model selection を評価します。

### 6.3 particle-tracing recovery

SVM または既知の synthetic magnetization から電子軌道を追跡し、PACE response と orbit motion を
適用した count へ落とします。これにより統計 model の recovery と、ER estimand が真の surface
field をどの程度下回るかを分離して評価します。

### 6.4 observational validation

1. ESA-S1 でfitし、ESA-S2のcount面を予測する。逆方向も行う。
2. window内の一部recordをheld outし、時系列外挿ではなく補間予測を測る。
3. energy bandまたはpitch sectorをheld outし、境界式の2次元予測を測る。
4. native cadence、短window、長windowで $R_m$ の安定性を比較する。
5. WFC wave power、tip angle、gyroradius proxyとresidual width/fillingの関係を調べる。
6. Lunar Prospector PDS derived productと公開論文を外部再現対象にする。

BICだけでなく、held-out log predictive density、calibration、posterior predictive residual、
parameter bound率を主要 metric にします。地図との相関は重要ですが、同じ平滑化やselectionを共有
すると見かけの一致が出るため、最終段階の外部検証として扱います。

## 7. 実装の推奨順序

1. Halekas paper baselineへsecondary beamとinstrument response convolutionを追加する。
2. 同じforward surfaceをbeta-binomial count likelihoodへ移し、hard modelの回復性を確認する。
3. ESA-S1/S2をsensor固有response付きjoint likelihoodにする。
4. 3--数recordの短window joint fitを実装し、単発fitに対するheld-out改善を測る。
5. response-convolved hard modelと追加finite-width modelを比較する。
6. widthをenergy、tip angle、WFC wave power、time jitterへ分解する診断を追加する。
7. particle tracingによるend-to-end calibration後に、`candidate`からのstatus変更を判断する。

edge-first estimator は、初期値、監査点、比較用 derived quantity として残します。主推定値は
2次元 count model から得て、edge 点はその posterior boundary を要約した結果として出す方が、
情報の流れと不確かさの扱いが一貫します。

### 7.1 実装済みの第一段階

`fit_global_joint_effective_field()` は、ESA-S1/S2 の full-pitch count 面を加算せず、raw count の
negative-binomial 尤度を足し合わせます。共通 latent incident spectrum $I(E)$ と loss-cone
surface を持ち、$R_m$、$\Delta U$、$\sigma_{\ln B}$、contrast を共有します。sensor ごとには gain、
dispersion、native energy/pitch grid、欠測 mask を保持します。KAGUYA の時刻合わせは
`kg.er.pitch_angle_spectra(time)`、低水準 fit は
`kg.er.effective_field.fit_global_joint({"ESA-S1": raw_s1, "ESA-S2": raw_s2})` から利用できます。

fit 後には S1/S2 の count、exposure、gain と incident spectrum を使ったnormalized exposureを、
まず共通の0--180 degree global FOVへ有限binの重なりに比例して積算します。そのglobal FOVの
対称binを最後に対応付け、0--90 degreeへ折りたたんだ `GlobalNormalizedFlux` を作ります。
これは fitting 前にsensorを混合した入力ではなく、sensor identityを保持した尤度から得た監査用
derived productです。`GlobalJointModelFit.global_fov`にはfold前の十分統計量を保持するため、3段目と
最下段が別々のpitch対応を使うことはありません。

`kg.er.effective_field.fit_timeseries(time, integration="16s")`はこのglobal joint modelを固定UTC窓へ
適用します。空窓とPACE mode境界はskipしますが、観測不足、窓内gap、affected半球の反転は
hard filterにせず、各recordのcount、exposure、$B_\mathrm{sc}$、affected側を尤度へ渡します。
窓内では$B_\mathrm{eff}$を共有し、recordごとの
$R_{m,i}=B_\mathrm{eff}/B_{\mathrm{sc},i}$で境界を計算します。これは時系列priorを使う
state-space modelではなく、独立な16秒window fitです。
`plot_global_joint_effective_field_fit()` の上段は折りたたみ前のsensor面ですが、既定の
`pitch_orientation="physical"` はaffected半球を0--90 degreeの左側へ揃えます。したがって左が
Moon-outgoing/affected、右がMoon-incoming/referenceです。`pitch_orientation="native"` を指定すると
0 degreeを$+B$、180 degreeを$-B$とする元のpitch座標へ戻せます。最下段は
$\alpha_f=\min(\alpha,180^\circ-\alpha)$で両半球を0--90 degreeへ対応付けた後、
affected/reference ratioとして観測、model、残差を表示します。

fold後の観測rateは、background/dead-time補正後countの非負部分を$N_A,N_R$、gainとincident spectrumを
含むnormalized exposureを$Q_A,Q_R$として扱います。低countを一律NaNにせず、既定ではJeffreys prior
$a=1/2$によるposterior mean log ratio

$$
E[\log r_A-\log r_R\mid N]
=\psi(N_A+a)-\log Q_A-\psi(N_R+a)+\log Q_R
$$

を表示します。対応するposterior標準偏差は

$$
\sigma_{\log(A/R)}
=\sqrt{\psi_1(N_A+a)+\psi_1(N_R+a)}
$$

で、`observed_log_ratio_std`に保存します。ここで$\psi$はdigamma、$\psi_1$はtrigammaです。
片側0 countでも推定値を残せますが、不確かさは大きくなります。従来の
`normalized_min_counts=5`と`normalized_max_log10_std=0.5`は欠損化ではなく`reliable` maskを作り、
図ではlow-countまたは片側不足で不確かさが大きいcellを点で示します。
符号付き補正count自体は`affected_corrected_counts`と`reference_corrected_counts`に残します。
background差し引き、dead-time逆補正、または有限binのoverlap分割が有効な場合、この計算は厳密な
共役posteriorではなくquasi-posteriorです。`observed_log_ratio_std`はPoisson sampling分だけを表し、
negative-binomial overdispersionと分割cell間の共分散は含みません。fit本体はこの表示posteriorを使わず、
0 countを含むsensor別raw-count negative-binomial尤度を使い続けます。

以前の `fit_joint_effective_field()` は各 sensor 内で affected/reference の対称 pitch pair を
要求するため、両 sensor にまたがる相補視野を使えません。これは比較診断として残しますが、全球
production 経路の主 API ではありません。

`GlobalPitchCountObservation`はraw event count専用です。`from_spectrum()`は`value="counts"`、count
unit、非負整数countを検証し、energy fluxなどをcount尤度へ誤投入しません。dead-time補正を指定する
場合はpitch cellを構成したdetector sample数が必要で、単一integration timeから暗黙推定しません。

現段階は上記の順序の 1--3 に対する raw-count 実装です。native grid、count、PACE INFO の
geometric-factor を含む exposure、有限 bin 幅、任意の非対角 response matrix、既知・推定
background、非麻痺型 dead-time、BIC 選択付き secondary beam を forward model に実装しています。
校正資料に存在しない非対角 response と dead-time 値は利用者入力のままであり、KAGUYA 既定値を
捏造してはいません。

この段階の後に残る model 拡張は低rank residual pitch baseline と短時間 window state です。これらは
今回列挙した装置・beam 補正の未実装ではなく、時系列化と nuisance model の次フェーズとして扱います。

### 7.2 境界を主役にする改良方針（2026-09、比較実装済み）

2008-08-20の19:04:56と20:44:56の比較では、固定0.1/1.0のHalekas型が目視の減少境界を
現行jointの自由baseline・band contrastより直接捉えました。一方、全分布の誤差が常に小さいわけでは
なく、native-count尤度とfold後のlog比の二乗誤差は別の目的関数です。この2例だけで全期間に対する
優位性を結論しません。

当面は低rank residualの追加よりも、次の「境界中心の制約付きモデル」を優先して比較します。
**固定・共通レベル版を選択可能にしました。既定のjointモデルは置換していません。**

$$
q(E,\alpha)=C\left[f+(1-f)T(E,\alpha;R_m,\Delta U)\right]
+A_{beam}\,g(E,\alpha).
$$

- $T$ は最初はhard境界。正の $R_m$ を許し、観測のenergy・pitchビン応答を積分する。
- $C$ は外側レベル、$f$ は内外比。まず $C=1,f=0.1$ を基準とし、その後は全energy共通の
  少数パラメータとしてのみ緩める。energy別baselineや自由なband中心を同時に追加しない。
- $g$ は月面から出る側のbeam-like excess。まずbeamなしとありを同じセル・尤度で比較する。
  中心energy、電位差、宇宙機電位の関係を検証してから物理制約を導入し、未校正の段階で
  中心を単純に $|\Delta U|$ に固定したり、secondary由来と断定したりしない。
- 観測応答だけで不足する場合に限り、全energy共通の小さい固有幅を追加する。
  自由なenergy別遷移幅に戻さず、応答幅と固有幅の同定可能性を調べる。

fitはS1/S2別・fold前のraw countとexposureに対して行う既存の枠組みを維持します。
reference側では $q=1$ とし、incoming分布を装置応答・gainとともにforward modelへ入れます。
内外レベルの固定版でも、推定countは装置応答の積分後には厳密な二値にはなりません。
低countは尤度で扱い、存在する0 countを欠測に置き換えません。mapの等重みlog-SSEは論文型の
比較基準として残しますが、異なる目的関数間のBICは比較しません。

モデル間比較図では、観測側の正規化を候補ごとに動かさない共通表示も必須とします。
reference由来のincident分布とsensor gainの推定方法を明示し、その不確かさを無視して
fold後の各セルを独立データとみなさないようにします。

検証は以下の順に行います。

1. 同じforward responseと目的関数で、固定二値、共通 $C,f$、beam追加を比較する。
2. $R_m<1,=1,>1$、既知電位、ビーム重畳、片側低count、ビン幅を変えた合成データで
   境界とパラメータの回収を確認する。edgeなしの誤検出も測る。
3. 目視境界があるケースだけでなく、ないケースも含む未調整の別日データで、予測残差・
   境界位置誤差・棄却率・16秒窓の時間安定性を評価する。
4. 不確かさは生の観測レコードを単位にした再標本化などで確認する。二値格子の同点範囲を
   信頼区間と呼ばない。時系列priorは単一窓での境界biasを確認した後に追加する。

`GlobalJointFitSettings(loss_cone_model="fixed")` が固定 $C=1,f=0.1$、`"shared"` が
全energy共通の $C,f$ をfitする比較実装です。`"flexible"` は従来モデルで既定値のままです。
hard境界のpitchビン内解析積分、energyビン内quadrature、S1/S2別native-count尤度、
`secondary_beam="auto"` を共通に使用します。hard版はRust backendを使用します。
`edge_transition="smooth"` では同じ線形rate混合に共通幅を追加できますが、Python経路です。

固定版でもno-edge候補には全energy共通の半球レベルを1個許します。固定した $C,f$ はBICの
自由パラメータ数や境界到達フラグに数えません。共通版の $\log C$ は
`baseline_log_ratio_bounds`、$-\log f$ は `amplitude_log_ratio_bounds` を使用します。
`hemisphere_baseline_knots` と `effective_field.contrast_model` は固定・共通版では使用しません。

検証の成果物は `working/kaguya-er-fit-review/boundary-centered-validation-v2/` に保存します。
共通表示はfit由来gain・incident正規化を除いたcount/exposure比であり、校正済みの絶対的な
半球フラックス比ではありません。fit自体はgainを含むnative-count尤度です。
合成データによる回収と少数の実データ比較を実施し、別日への未調整検証、bootstrapによる
不確かさ、時系列priorの検証は今後の段階として残します。

### 7.3 入射角分布を含む全窓評価

`working/kaguya-er-fit-review/build_incident_week.py` は、shared 境界に低自由度の入射角分布を
加えた実験を全16秒窓へ適用する再開可能な runner です。通常のfit図と、予測beam・
beam差し引き後の分布を日別に保存します。主 package の既定モデルを置き換えるものではありません。

入射分布は $J_0(E)\exp[k(E)\cos^2\alpha]$、$k(E)$ は3 knots。
no-edge / mirror / electrostatic の各々についてbeam有無を比較し、複数初期値と
両方向のwarm-startで探索漏れを抑えます。count尤度はnegative binomial、有限ビン積分を
含む解析勾配のPython/NumPy経路です。校正exposure以外の非対角応答・dead time・backgroundは
この実験経路では未対応です。時系列priorや推定誤差の校正は未導入で、結果は暫定候補です。

```powershell
.venv/Scripts/python working/kaguya-er-fit-review/build_incident_week.py --workers 6 --output working/kaguya-er-fit-review/integrated-week-20080818-20080824
```

対象は2008-08-18〜24、20–1500 eV。全37,800窓を記録し、データがある非校正の対象は
既存cacheで10,433窓です。完了数は生成先の `progress.json` / 日別 `heartbeat.json` で確認します。
READMEやギャラリーの存在だけでは全件計算完了を意味しません。

## 8. 主要文献

- Halekas, J. S. et al. (2008), [Lunar Prospector observations of the electrostatic potential of the lunar surface and its response to incident currents](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2008JA013194).
- Halekas, J. S. et al. (2011), [First remote measurements of lunar surface charging from ARTEMIS](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2011JA016542).
- Halekas, J. S. et al. (2003), [Inferring the scale height of the lunar nightside double layer](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2003GL018421).
- Halekas, J. S. et al. (2010), [How strong are lunar crustal magnetic fields at the surface?](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2009JE003516).
- Halekas, J. S. et al. (2012), [Solar wind electron interaction with the dayside lunar surface and crustal magnetic fields](https://link.springer.com/article/10.5047/eps.2011.03.008).
- Mitchell, D. L. et al. (2007), [A global map of Mars' crustal magnetic field based on electron reflectometry](https://agupubs.onlinelibrary.wiley.com/doi/10.1029/2005JE002564).
- Lillis, R. J. et al. (2008), [Electron reflectometry in the Martian atmosphere](https://www.sciencedirect.com/science/article/pii/S0019103507004940).
- Lillis, R. J. et al. (2008), [An improved crustal magnetic field map of Mars from electron reflectometry](https://www.sciencedirect.com/science/article/pii/S0019103507005465).
- Lillis, R. J. et al. (2018), [Field-aligned electrostatic potentials above the Martian exobase from MGS electron reflectometry](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1002/2017JE005395).
- Harada, Y. et al. (2021), [Global maps of solar wind electron modification by electrostatic waves above the lunar day side](https://agupubs.onlinelibrary.wiley.com/doi/10.1029/2021GL095260).
- Kurita, S. et al. (2025), [Direct evidence for electron pitch angle scattering driven by electrostatic cyclotron harmonic waves](https://agupubs.onlinelibrary.wiley.com/doi/10.1029/2024GL113188).
- NASA PDS, [Lunar Prospector ER Level 4 Electron Data](https://pds.nasa.gov/ds-view/pds/viewProfile.jsp?dsid=LP-L-ER-4-ELECTRON-DATA-V1.0).
