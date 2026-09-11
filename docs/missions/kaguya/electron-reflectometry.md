# 電子反射法による実効磁場

`KAGUYA.er.effective_field` は、月向き・反月向きの電子 count を対にして、
loss-cone 境界から実効的な mirror field を推定します。この product は候補段階です。

詳しい読み物は目的別に分けています。

- [全期間16秒窓のjoint推定](electron-reflectometry-all-period.md): 入射PAD付きRust経路、fitラベル、上流条件、実行・再開
- [ESAのmodeと入力フィルター](esa-mode-policy.md): 17/18を残す理由、SPEDASの無効条件、収録形式とキャッシュ
- [フィルター・サンプリング棚卸し](electron-reflectometry-selection-audit.md): 実効条件、未使用設定、不足する診断、見直し候補
- [推定アルゴリズム](electron-reflectometry-algorithm.md): 物理の前提、count 尤度、model 選択、品質判定
- [全期間検証](electron-reflectometry-validation.md): coverage、selection function、画像監査、SVM 比較
- [外部手法調査](electron-reflectometry-method-survey.md): 既存のloss-cone推定、遷移幅、2次元・時系列modelの設計

## 推定量

主推定量は mirror ratio です。

\[
R_m = \frac{B_{\mathrm{eff}}}{B_{\mathrm{sc}}}
\]

`B_eff` は `R_m * |B_sc|` から得る派生量です。磁場ベクトル、月面の一点における
真の磁場、Tsunakawa SVM の置き換えではありません。磁気 mirror、静電場、有限 gyroradius、
時間変動などを含み得る観測上の実効量として扱います。

境界モデルは次式です。

\[
\sin^2 \alpha_c(E) = \frac{1}{R_m}
\left(1 + \frac{\Delta U_{\mathrm{eff}}}{E-U_{\mathrm{sc}}}\right)
\]

`DeltaU_eff` は低エネルギー側の曲率を表す nuisance parameter です。独立な検証なしに
月面電位と解釈しません。`U_sc` は
`EffectiveFieldFitSettings(spacecraft_potential_eV=...)` で指定し、既定値は 0 eV です。

## 入力と尤度

入力は `time x energy x pitch_angle` の full-pitch **counts** です。energy flux の比を
対数化して fit するのではなく、対になった affected/reference count の合計を条件とした
beta-binomial 尤度を使います。これによりゼロ count を捨てず、Poisson sampling と
overdispersion を扱えます。

pitch-angle bin ごとの exposure がある場合は補正に使います。KAGUYA PACE の counts
pitch spectrum は exposure を補助座標として保存します。結果の `exposure_mode` は
`calibrated`、`relative`、`explicit`、`assumed_equal` のいずれかです。

PACE の `0x11` (TOFCAL) と `0x12` (POSCAL) でもESAはEC-Nの角度別カウントを取得するため、
一括除外しません。[ESA固有の無効条件と対応形式](esa-mode-policy.md)で判定します。sensor別出力では採用した record の mode と type を
`pace_data_mode`、`pace_data_type` 座標に残します。S1/S2 combined出力ではsensor名を付けた
`pace_data_mode_esa_s1` などの座標を使います。除外規則は `pace_data_mode_policy` metadata
に保存され、raw countへのアクセスは影響を受けません。

affected side は fit の良さで選びません。`affected_side="auto"` では同一 frame の磁場
ベクトルと位置ベクトルから `B dot r` の符号を使い、外向き電子の hemisphere を決めます。

## モデル選択

同じデータに三つの nested model を当てます。

| model | 内容 |
| --- | --- |
| `no_edge` | energy ごとに一定の affected/reference 比 |
| `mirror_only` | energy に依存しない mirror boundary |
| `electrostatic` | `DeltaU_eff` を含む energy-dependent boundary |

count 比の二次元モデルは次の形です。

\[
\log q(E_i,\alpha_j) = \beta_i + A(E_i)\,T(E_i,\alpha_j)
\]

`beta_i` は energy ごとの baseline、`T` は上の境界式から得る滑らかな pitch-angle
transition です。既定の `contrast_model="auto"` は、一定 contrast と次の log-energy
band を比較します。

\[
T(E,\alpha) = \Phi\!\left(
\frac{\ln\sin^2\alpha -
\ln\left[(1+\Delta U_{\mathrm{eff}}/(E-U_{\mathrm{sc}}))/R_m\right]}
{\sigma_{\ln B}}
\right)
\]

ここで `Phi` は標準正規分布の累積分布関数です。観測面は exposure 補正した
`log[(affected + 0.5) / (reference + 0.5)]` で可視化しますが、最適化自体は
この擬似 count 比への最小二乗ではなく、元 count の beta-binomial 尤度で行います。

\[
A(E) = A_{\mathrm{floor}} + (A_{\mathrm{peak}}-A_{\mathrm{floor}})
\exp\left[-\frac{(\ln E-\ln E_c)^2}{2w^2}\right]
\]

band は、特定の energy 帯だけ edge が明瞭になる sensor response、count statistics、
または電子分布の影響を低次元で吸収する nuisance model です。`E_c` を energy cutoff、
spacecraft potential、energy calibration shift と直接解釈しません。電位に伴う境界の
energy 依存は別の `DeltaU_eff` が表します。従来の energy ごとに自由な contrast は
`contrast_model="free"` で明示的に利用できます。

全 pitch に共通して見える横方向の energy step は mirror boundary と分離します。選択した
二次元 model の energy ごとの baseline に、linear log-energy trend と change point を
事後的に当て、`energy_ratio_step_*` として記録します。この change point は edge model の
採否には使いません。また、affected/reference 比の段差であり、絶対 spectrum の cutoff、
spacecraft potential、energy calibration shift の推定値ではありません。

\[
\beta(E) = c_0 + c_1\ln E + s\,\mathbf{1}(E \ge E_c)
\]

既定では edge 自体、transition width、contrast band は BIC が6以上改善した場合だけ採用します。
mirror-only に対する electrostatic curvature は、BIC の parameter penalty を通過したうえで
1以上改善した場合に採用します。mirror ratio、transition width、`DeltaU_eff`、または band の
excess contrast・中心・幅が bounds に
張り付いた fit は
採用しません。さらに、retained energy の 80% 以上で境界の両側に一つ以上、50% 以上で
両側に二つ以上の実測 pitch bin が必要です。採用された mirror ratio には
profile-likelihood 95% interval を計算します。

## API

```python
import sopran as spn

settings = spn.EffectiveFieldFitSettings(
    spacecraft_potential_eV=0.0,
    contrast_model="auto",
    profile_likelihood=True,
)

result = spn.kaguya.er.effective_field.fit(
    pitch_counts,
    magnetic_field=magnetic_field,
    position=spacecraft_position,
    affected_side="auto",
    settings=settings,
    cache="use",
)

frame = result.to_pandas()
```

`cache="use"` は同じ variant と時刻範囲が Store にあればロードし、なければ fit 後に
`features/kaguya/er/effective_field` へ保存します。手元で paired counts を構築する場合は、
mission 非依存 API の `spn.ElectronReflectionCounts` と
`spn.fit_effective_field(...)` を使えます。

native cadence の全レコードを16秒ごとに積分し、ESA-S1/S2を分離したままglobal 2-D
count modelでfitする入口は次です。

```python
fits = spn.kaguya.er.effective_field.fit_timeseries(
    spn.day("2008-08-20"),
    integration="16s",
    workers=8,
)

frame = fits.to_pandas()
```

PACEは通常約2秒間隔なので、完全な16秒窓は8レコードです。4/8という値は
`window_coverage`の診断基準として記録しますが、fitのhard filterには使いません。
各native recordは独立したnegative-binomial尤度項として保持し、窓内で物理パラメータとS1/S2別の
gain・background・dispersionを共有します。したがって上り・下りsweepの半binずれも保持されます。
共有する物理量は$B_\mathrm{eff}$であり、各recordの境界には
$R_{m,i}=B_\mathrm{eff}/B_{\mathrm{sc},i}$を使います。疎な窓、観測gap、affected側の反転は
除外せず、利用できるcountとexposureを尤度へ入れます。`window_coverage`、
`max_record_gap_seconds`、`affected_side_changed`は品質診断として保存します。
空窓とPACE modeが窓内で変わる場合だけ事前にfitせず、`fit_status`と`fit_error`に理由を残します。
既定モデルはRust hard-edge経路、count補正は
SPEDAS互換の`event_trash`です。結果は時刻範囲を含む同じvariantがなければ
`kaguya.er.global_joint_effective_field`としてStoreへ保存されます。

ESA-S1とESA-S2の反対向き半球視野を統合したcount spectrumは次の入口で作ります。

```python
pitch_counts = spn.kaguya.er.pitch_angle_spectrum(
    time,
    cadence_seconds=600,
    pitch_bins=16,
    energy_bins=24,
)
```

両sensorをそれぞれのFOV・感度較正でpitch binningし、共通energy範囲を対数binへ再集計します。
countとexposureは整数countを保ったまま加算し、ESA-S2の低い感度を単純なcount差として扱いません。
生成物の`source_sensors`は`ESA-S1`, `ESA-S2`です。

Halekas 2008のloss-cone synthetic distributionに近い全2次元面fitは次です。

```python
hard = spn.fit_halekas_distribution(paired_counts)

hard.mirror_ratio
hard.delta_u_eff_eV
hard.root_mean_square_error
hard.fitted_log_ratio
```

energy別edgeを先に検出せず、正規化ratioがloss cone外で1、内で0.1となるsharp分布を
$(R_m, \Delta U_{eff})$についてgrid searchします。緩やかな境界を同じ分布モデルで調べる場合は、

```python
smooth = spn.fit_halekas_distribution(
    paired_counts,
    settings=spn.HalekasFitSettings(edge_transition="probit"),
)

smooth.sigma_ln_sin2
smooth.hard_to_smooth_delta_bic
```

とします。現在は論文のsecondary-electron beam成分を含まないため、loss-cone部分の再現です。

共通pitch背景とenergy局在contrastをprofileする旧binary prototypeは次です。

```python
binary = spn.fit_binary_loss_cone(paired_counts)

binary.selected_model
binary.mirror_ratio
binary.delta_u_eff_eV
binary.no_edge_delta_bic
binary.electrostatic_delta_bic
```

この旧prototypeは共通pitch背景をprofileしたexposure補正log rate ratioのbinary least-squares fitです。
既定のsmooth beta-binomial fitとはBICを直接比較せず、独立した感度解析として扱います。

従来の10分代表レコードによる全球比較用catalogは次のように作ります。

```python
catalog = spn.kaguya.er.effective_field.build_archive(
    cadence="10min",
    pitch_bins=16,
    workers=8,
)

fits = catalog.scan()
```

出力は `date=YYYY-MM-DD` の Parquet shard です。`build-state.json` に
`complete`、`missing`、`no_data`、`failed` を日ごとに記録し、再実行時は完成shardを
再利用します。`sampling_cadence_seconds` は各行にも残ります。

## Global joint の beam 分解診断

beam が境界の曲率を吸収していないか確認する場合、fit に用いた同じ観測・設定から
期待 count を分解できます。採択された fit だけでなく比較候補も指定できます。

```python
from sopran.analysis.electron_reflection import (
    decompose_global_joint_beam,
    plot_global_joint_beam_decomposition,
)

# observations / settings は global joint fit 時と同じもの。
parts = decompose_global_joint_beam(observations, candidate, settings=settings)
fig = plot_global_joint_beam_decomposition(parts, comparison_fit=other_candidate)
```

global FOV の観測・全モデル・beam 予測、観測から beam を差し引いた面、beam をゼロに
した反射モデル、fold 後の比較を表示します。beam 振幅だけをゼロにして他のパラメータを
固定し、装置応答を通した期待 count の差を取ります。log 値から直接引く処理ではありません。
これは再 fit でも独立な観測でもなく、beam 推定誤差は伝播していない条件付き診断です。
非線形 dead-time 応答では加法的に分離できないため、この API は非ゼロ dead time を拒否します。

負の差し引き count は magenta、欠測は gray、ゼロは濃い青で区別します。fold の観測比は
表示専用の `normalized_rate_prior_count` を両側に足した比です。
fold の magenta は加算前にいずれかの半球の残差が負だったセルを示します。
生の符号付き残差は `parts.observed_minus_beam_counts` に保持されます。

`beam_sigma_pitch_bounds_deg=(2, 60)` は Gaussian の標準偏差の探索範囲で、
60 度より外の粒子をゼロにする物理的な制約ではありません。
角度依存性は $\exp[-\alpha^2/(2\sigma_\alpha^2)]$ なので、$\sigma_\alpha=60$ 度でも
90 度でピークの約 32% が残ります。上限は広い成分と背景・反射成分との縮退を抑えるための
モデリング上の選択です。上限付近の解は幅が決まっていない可能性があり、上限を変えた感度確認と
成分の解釈が必要です。現行の beam `auto` は beam パラメータの bounds 到達を不採択条件にします。

## 品質列

最低限、次を同時に確認します。

- `edge_supported` と `selected_model`
- `no_edge_delta_bic` と `electrostatic_delta_bic`
- `contrast_model`、`contrast_band_center`、`contrast_band_width_ln`
- `contrast_band_floor_log_ratio` と `contrast_band_peak_log_ratio`
- `contrast_band_delta_bic`
- `edge_candidate_model` と `edge_candidate_contrast_model`
- `boundary_bracket_fraction` と `strict_boundary_bracket_fraction`
- `energy_ratio_step_supported`、`energy_ratio_step_center`、`energy_ratio_step_log_ratio`
- `energy_ratio_step_delta_bic` と `energy_ratio_step_direction`
- `mirror_ratio_ci95_low/high`
- `bound_stuck`、`profile_truncated`、`reason`
- `n_energy_bins`、`n_cells`、`total_counts`
- `affected_side`、`exposure_mode`
- `quality_grade` と `quality_reasons`
- `edge_fit_log_ratio_residual_p90_abs`
- `edge_fit_pitch_pattern_correlation` と `edge_fit_pitch_pattern_nrmse`
- `edge_fit_standardized_residual_inlier_fraction`

`edge_supported=False` の行では `mirror_ratio` と `effective_field` は null です。
`quality_grade` の意味は次の通りです。

| grade | 用途 |
| --- | --- |
| `good` | edge 支持に加え、実測2次元面との一致が強い。主解析用。 |
| `review` | edge は支持されるが残差または pitch pattern が弱い。主解析に含め、`good` のみの図と比較する。 |
| `poor` | edge は形式上支持されるが予測面との一致が弱い。感度解析・目視確認用。 |
| `reject` | no-edge、bounds、または境界支持条件により物理 edge を採用しない。 |

## 検証の現在地

合成 beta-binomial data では、constant / log-energy band contrast、mirror-only、
electrostatic curvature、no-edge、energy-ratio step の recovery test を行っています。

全期間の10分 catalog は473 complete day、109 missing day、55,702 fit row です。
`good + review` は2,470件（4.43%）、中央値 `B_eff=9.18 nT` でした。時期を層化した
70 edge 候補の既存画像監査では、`good + review` の38/40が clear または plausible でした。

一方、radial subpoint の Tsunakawa SVM との Spearman 相関は `good + review` で0.081、
energy-step 除外で0.001でした。straight-local footpoint へ限定しても相関は0.043で、
`good + review` の接続率は46.4%でした。このため、候補選別の内部検証は進みましたが、月面磁場
map としての外部検証は通っていません。また全期間 variant は profile likelihood を無効にしており、
個々の区間推定を持ちません。数値、標本設計、selection bias、再現コマンドは
[全期間検証](electron-reflectometry-validation.md)にまとめています。

hard fit高速化の実測値、PyO3境界、gradient戦略、equivalence test、性能ゲートは
[Rust backend設計](electron-reflectometry-rust-backend.md)にまとめています。
