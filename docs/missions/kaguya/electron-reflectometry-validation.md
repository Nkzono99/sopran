# 電子反射法の全期間検証

このページは、KAGUYA/PACE count から `mirror_ratio` と `effective_field` を推定する
固定 variant `robust_counts_v2_600s_p16_e78a09b2d1c7` を、2026-08-23 に検証した報告です。
推定式と実装手順は[推定アルゴリズム](electron-reflectometry-algorithm.md)を先に参照してください。

!!! danger "先に結論"
    archive と推定器の**機械的再現性は確認できました**。一方、ブラインド再監査、ESA1/ESA2
    相互検証、短時間 cadence、独立な磁場 model との比較はいずれも、現在の
    `good + review` をロバストな月面磁場推定値とみなすには不十分または否定的でした。
    現在の出力は `status="candidate"` の **loss-cone-like edge 候補**です。
    月面磁場 map、現象数、絶対精度の入力には使用しないでください。

## 1. この検証で区別するもの

「コードが正しく動く」と「物理量を正しく測る」は別です。本報告は次の5段階を分けます。

| 段階 | 問い | 今回の結果 |
| --- | --- | --- |
| archive integrity | file、時刻、式、provenance は壊れていないか | 確認 |
| numerical reproducibility | 同じ raw data から同じ fit を再現できるか | 確認 |
| statistical uncertainty | 点推定はどの程度絞れているか | 広い例・truncation が多い |
| internal replication | 別 sensor、別 cadence、blind review でも残るか | 否定的 |
| external physical validity | 独立な月磁場 model と対応するか | 確認できず |

従って、「全テストが通った」は archive の正しさを表しますが、`B_eff` の物理的正しさを
意味しません。逆に外部対応が弱いことだけで count 面に edge がないとも断定できません。
現在確認できる estimand は、選択 model の仮定下での観測時点の effective mirror field です。

## 2. 対象と sampling

| 項目 | 固定値 |
| --- | --- |
| 要求期間 | 2007-11-07 00:00 UTC 以上、2009-06-11 00:00 UTC 未満 |
| 要求日 | 582日 |
| 主 sensor | PACE ESA1 |
| 磁場・位置 | LMAG + SPICE |
| sampling | 600 s bucket の中心に最も近い native record を1件 |
| pitch | 0--180 degree を16 bin、対称 pair を0--90 degreeへ折り畳み |
| likelihood | exposure-aware beta-binomial |
| model | `no_edge`、`mirror_only`、`electrostatic` |
| model selection | nested BIC、既定改善量6 |
| primary selection | `quality_grade in {"good", "review"}` |
| archive profile likelihood | 無効。別 validation artifact で全候補を再計算 |

!!! warning "全期間の意味"
    全期間の公開 file を日単位で走査しましたが、全 native record を fit したわけではありません。
    10分値は10分平均でも積算でもなく、1 record の系統標本です。cadence 感度でこの差を別に
    検証しています。

## 3. 結果一覧

| 検証 | 主な結果 | 判定 |
| --- | --- | --- |
| archive integrity | 473 shard、55,702行、違反0 | 確認 |
| accepted 再 fit | 2,470/2,470で grade、model、点推定一致 | 確認 |
| profile 95%区間 | 全行で有限、32.7%が探索範囲で truncated | 注意 |
| selection model | edge 発生の combined AUC 0.548 | 単純環境変数で説明できず |
| blinded re-audit | 二値一致58.2%、kappa 0.074 | 再現性が低い |
| ESA1/ESA2 | 共通1,772時刻中、最終同時 accepted は1件 | sensor 間不整合 |
| 2分/10分 | 10分 accepted 40件中、別2分 recordでも残るのは15件 | 持続性が低い |
| official SVM evaluator | 5,041点、成分最大誤差0.000683 nT | 実装確認 |
| curved SVM3D | \(B_{sc}\) 調整後の相関 -0.046 | 独立対応なし |

## 4. Archive integrity と coverage

検証器は `build-state.json`、`catalog.parquet`、各 shard を read-only で照合しました。

- complete day と shard 集合、row count、SHA-256 checksum
- 重複時刻、UTC 日付、600 s cadence、`exposure_mode="calibrated"`
- LMAG vector norm と `b_sc_nT`
- 位置 vector norm、平均月半径1737.4 kmからの altitude
- accepted 行の `effective_field = mirror_ratio * b_sc_nT`
- edge 非採択行の field 値が null であること

| coverage 指標 | 結果 |
| --- | ---: |
| complete | 473 / 582日 (81.27%) |
| missing | 109日 (PACE 95、LMAG 14) |
| no_data / failed | 0 / 0 |
| fit rows | 55,702 |
| 全要求期間の nominal 10分 slot | 83,808 |
| fit row / 全要求 slot | 66.46% |
| fit row / complete-day slot | 81.78% |

2007年11月の対象24日と2009年1月31日は全て missing です。欠測を「現象0件」として扱っては
いけません。月別の accepted fraction も、現象 prevalence ではなく観測・calibration・gate を
含む selection probability です。

![月別 coverage と accepted fraction](../../assets/kaguya/er-validation/monthly-coverage-and-selection.png)

## 5. Fit と出力量

| grade | 行数 | 全 fit 行に対する割合 |
| --- | ---: | ---: |
| `good` | 649 | 1.17% |
| `review` | 1,821 | 3.27% |
| `poor` | 2,264 | 4.06% |
| `reject` | 50,968 | 91.50% |
| `good + review` | 2,470 | 4.43% |
| 全 edge-supported | 4,734 | 8.50% |

accepted 2,470件の点推定は次の分布でした。

| 量 | p10 | median | p90 | p99 |
| --- | ---: | ---: | ---: | ---: |
| `mirror_ratio` | 1.154 | 1.751 | 4.105 | 11.393 |
| `effective_field` [nT] | 4.12 | 9.18 | 25.21 | 75.20 |

`energy_ratio_step_supported=True` は1,847件 (74.78%) です。全 pitch に共通する energy step が
accepted 集合の大部分にあるため、step なし623件を必ず感度集合として併記します。ただし623件も
異なる selection を受けた小標本であり、自動的に真値へ近いわけではありません。

最多 rejection は `insufficient_energy_support=25,331` (45.48%) で、次が
`no_edge_evidence=11,464`、`edge_parameter_at_bound=8,959` です。非採択の多くは「物理的に
edge がない」ではなく、推定可能な入力支持がないことを意味します。

## 6. Profile-likelihood 不確かさ

archive 自体は計算量のため profile likelihood を無効にしています。そこで accepted 2,470件を
raw ESA1、LMAG、SPICE から全て再構成し、点推定以外の parameter を各 \(R_m\) grid で再最適化しました。

- 458観測日、失敗0
- source grade 一致 2,470/2,470
- source model 一致 2,470/2,470
- source 点推定相対差 0
- 95% profile 区間が有限 2,470/2,470
- `profile_truncated=True` 807件 (32.67%)
- 相対区間幅 \((R_{hi}-R_{lo})/\hat R\): median 0.347、p90 1.379、p99 3.659
- 相対幅0.5以下 1,536件 (62.19%)、1.0以下 2,065件 (83.60%)

| grade | n | truncated | 相対幅 median | 相対幅 p90 |
| --- | ---: | ---: | ---: | ---: |
| `good` | 649 | 162 (24.96%) | 0.257 | 1.004 |
| `review` | 1,821 | 645 (35.42%) | 0.387 | 1.631 |

`truncated` は95%境界が model の global bound まで確定したという意味ではなく、設定した profile
探索範囲内に交点がなかったことを表します。その区間端を通常の閉じた95%区間として扱わないで
ください。点推定だけの地図は、この不確かさを隠します。

## 7. Selection function

単変量では nightside、特に SZA 150--180 degree で accepted fraction が低く、total count の
低い層で大きく低下しました。さらに、日を時間順に分けた5-fold cross-validation で三段階の
ridge logistic model を評価しました。

1. `input_supported`: fit に必要な cell があるか
2. `edge_supported_given_input`: 入力がある条件で edge gate を通るか
3. `quality_accepted_given_edge`: edge 条件で `good/review` になるか

| outcome | observation AUC | environment AUC | combined AUC | combined log loss |
| --- | ---: | ---: | ---: | ---: |
| input supported | 1.000 | 0.961 | 1.000 | 0.005 |
| edge given input | 0.536 | 0.544 | 0.548 | 0.442 |
| quality given edge | 0.674 | 0.591 | 0.673 | 0.634 |

input support を count/cell 数で予測できるのは定義に近い結果です。重要なのは、altitude、SZA、
\(B_{sc}\)、緯度経度、mission time を加えても edge 発生はほぼ chance に近いことです。edge 後の
quality は主に観測支持で説明され、combined model の1標準偏差あたり odds ratio は
`log_total_counts=1.89`、`n_cells=0.595`、`n_energy_bins=2.26` でした。環境係数はほぼ1です。

これは環境が無関係という証明ではありません。wake、solar wind、magnetotail など必要な plasma
regime を現在の model が持たず、単純な geometry だけでは selection を説明できないという結果です。

![SZA、count、SVM に対する selection](../../assets/kaguya/er-validation/selection-function.png)

## 8. Blinded re-audit

### なぜ旧結果を下方修正したか

旧監査は edge-supported 70件を fit 境界・診断と一緒に見て label し、`good + review` の38/40
(95.0%) を `clear/plausible` としました。しかし reviewer が自動境界を知っているため、独立な
precision ではありません。

同じ70件を固定 seed で並べ替え、次を隠して再監査しました。

- 時刻、automatic grade、selected model
- fitted boundary、fit diagnostics
- 旧 manual grade と理由

表示したのは exposure 補正済みの**観測 count-rate ratio だけ**です。label を全件固定してから
answer key を開きました。

| 指標 | 結果 |
| --- | ---: |
| evaluable | 67 / 70 (indeterminate 3) |
| 旧監査との二値一致 | 39 / 67 = 58.2% |
| 一致率 Wilson 95%区間 | 46.3--69.3% |
| Cohen's kappa | 0.074 |
| 旧 positive を再び positive | 30 / 45 = 66.7% |
| 旧 negative を再び negative | 9 / 22 = 40.9% |
| automatic `good/review` を blind positive | 23 / 37 = 62.2% |
| 上記 Wilson 95%区間 | 46.1--75.9% |

blind positive は `good=5/5`、`review=18/32`、`poor=20/30` でした。`good` は良好ですが n=5 と
小さく、`review` と `poor` は raw observation だけでは分離しません。従って旧95%を精度として
引用してはいけません。これは同じ review process の repeatability test であり、独立 expert
ground truth でもありません。また no-edge/reject を標本に含めていないため recall は測れません。

## 9. ESA1/ESA2 相互検証

[PACE の設計論文](https://doi.org/10.2322/tstj.7.Tk_7)では、三軸安定 KAGUYA で完全な3次元電子
分布を得るには ESA-S1 と ESA-S2 の組が必要です。そこで fit 結果を見ず、各月15日に最も近い
joint-available day を18か月から固定し、両 sensor を独立に同じ設定で処理しました。

| availability | 結果 |
| --- | ---: |
| ESA1 + LMAG complete | 473日 |
| ESA2 raw available | 457日 |
| joint available | 449日 (ESA1 complete の94.93%) |

ESA2 の calibration fallback 探索不具合を修正した後、FOV と INFO table を両方読みました。
ESA1 の再 fit は元 archive 1,990/1,990 行で grade、model、点推定が完全一致しました。

| 指標 | ESA1 | ESA2 |
| --- | ---: | ---: |
| fit rows | 1,990 | 1,926 |
| finite cell fraction median | 0.711 | 0.758 |
| paired cell fraction median | 0.609 | 0.641 |
| supported energy bins median | 26 | 25 |
| accepted | 79 (3.97%) | 21 (1.09%) |

同じ channel index の energy は一致せず、median | log ratio | は0.616です。RAM6 などで sweep
table が異なるため、channel 番号で結合してはいけません。実 energy 最近傍では median
| log ratio | は0.0915まで下がりました。

共通1,772時刻では edge evidence の ΔBIC は Spearman 0.811 で連動しました。しかし
edge-supported は ESA1 141件、ESA2 171件、共通33件で、Jaccard は11.8%です。両方が edge を
選んだ33件では `B_eff` の Spearman ρ=0.560、ESA2/ESA1 比の中央値は1.011でしたが、最終的に
両方で `good/review` になったのは1件だけでした。

角度 cell 数の不足だけでは説明できません。ESA2 の look-vector 座標、半球対応、sensor 固有応答、
geometric factor と duty factor を独立に監査し、共通境界 + sensor 固有 nuisance parameter の
joint likelihood を設計するまで、ESA1/ESA2 を単純結合しません。

## 10. Cadence 感度

### 2分対10分

監査に使った固定6日を、同じ raw data と settings で再処理しました。

| cadence | rows | accepted | accepted fraction |
| --- | ---: | ---: | ---: |
| 10分 | 769 | 40 | 5.20% |
| 2分 | 3,778 | 175 | 4.63% |

600 s 代表 record は120 s 系列にも含まれます。その同一 record を除くと、10分 accepted 40件のうち
周辺4 recordのどれかでも accepted だったのは15件 (37.5%、Wilson 95%区間24.2--53.0%)、
周辺の過半数で accepted だったのは1件 (2.5%、0.44--12.9%) でした。周辺 accepted がある15件では
`B_eff` の Spearman ρ=0.786、fine/coarse log ratio の中央値は -0.031 ですが、p10--p90 は
-0.695--0.382 と広いです。

### Native 対10分

固定日 2008-08-20 の native 20,314行では522件 (2.57%) が accepted でした。同日の10分値は
5/128 (3.91%) です。10分 accepted 5件は全て別 native recordにも候補がありましたが、bucket 内の
周辺 accepted fraction は中央値2.78%、p90 7.22%、過半数持続は0/5でした。n=5なので field
correlation は評価できません。

従って10分 catalog は event の10分継続を意味しません。次の production estimator では、独立な
代表 record の fit ではなく、時間 window の count を階層 model で同時に扱うか、最低持続率を
明示的な gate にする必要があります。

## 11. Tsunakawa SVM と曲線追跡

### 公式 evaluator の検証

公式 v2 配布物の `Positions.dat` と Fortran 出力 `B_Positions_v02.rst` 5,041点を、Rust surface
integral evaluator と全点比較しました。

| 誤差 | median | p95 | p99 | maximum |
| --- | ---: | ---: | ---: | ---: |
| component absolute [nT] | 0.000252 | 0.000475 | 0.000496 | 0.000683 |
| vector [nT] | 0.000494 | 0.000695 | 0.000766 | 0.000825 |

公式出力は0.001 nT丸めです。この一致により直接 evaluator の移植は確認できました。これは
electron-reflectometry estimator の正しさではなく、比較用 SVM backend の正しさです。

### Shell 補間精度

曲線追跡用に高度6.1--200 kmの9面を作りました。同じ乱数点を各高度区間256点で直接評価しました。

| altitude [km] | 1 deg median relative | 0.5 deg median relative | 0.5 deg p95 relative |
| --- | ---: | ---: | ---: |
| 6.1--10 | 47.3% | 19.8% | 52.7% |
| 10--20 | 28.6% | 10.8% | 36.1% |
| 20--30 | 17.7% | 6.85% | 25.5% |
| 30--50 | 10.9% | 5.86% | 21.9% |
| 50--75 | 5.99% | 5.31% | 21.3% |

0.5 degree は改善しますが、低高度の急峻な anomaly に対して precision grid ではありません。
field-line trace は診断用であり、最終 footpoint product にはしません。

### 全期間 curved trace

各 spacecraft 点で

\[
\mathbf B_{total}(\mathbf r)
=\mathbf B_{LMAG}(\mathbf r_{sc})
-\mathbf B_{SVM}(\mathbf r_{sc})
+\mathbf B_{SVM}(\mathbf r)
\]

とし、外部場残差を一様と仮定して1 km固定 step RK4で両符号を追跡しました。0.5 degree shell の
accepted 2,470件では preferred branch 接続が1,441件 (58.34%)、opposite は26件 (1.05%) です。

1 degree と0.5 degree の preferred 接続 status は98.99%一致しました。両方で接続した1,423件の
footpoint 差は median 0.088 degree、p90 0.469 degree、p99 4.09 degreeです。一方、`B_eff` 到達は
334件から382件へ増え、status 一致は96.36%でした。到達点は fitted `B_eff` から定義するため、
独立な validation target ではありません。

| curved preferred comparison、`good + review` | Spearman ρ |
| --- | ---: |
| raw `B_eff` vs path total maximum | 0.543 |
| `R_m` vs path maximum / `B_sc` | -0.089 |
| field excess vs path excess | -0.109 |
| `B_eff` vs crustal SVM maximum | -0.101 |
| `B_eff` vs path maximum、`B_sc` を rank 調整 | -0.046 |

raw 相関だけが正に見えるのは、両辺に同じ spacecraft field \(B_{sc}\) が入るためです。正規化・差分・
partial rank では独立対応がありません。radial subpoint の ρ=0.081、straight-local footpoint の
ρ=0.043から、曲線追跡へ変えても物理的対応は改善しませんでした。

![曲線 SVM3D 診断](../../assets/kaguya/er-validation/svm3d-curved-field-validation.png)

## 12. 総合判断

### 確認できたこと

- raw reader、calibration、pitch binning、fit、archive shard は決定的に再現する。
- nested count likelihood は55,702行を処理し、内部式と provenance に矛盾がない。
- accepted 点推定は別 workflow でも2,470/2,470再現する。
- official SVM v2 evaluator と Rust backend は0.001 nT丸め以下の規模で一致する。
- `good` は profile 幅と blind review の両方で `review` より良い傾向がある。

### 現在否定的なこと

- 旧95%画像監査は blind repeatability で再現せず、accuracy として使えない。
- ESA1 と ESA2 は edge evidence の強弱は共有するが、候補集合と最終 grade が一致しない。
- 10分 accepted の大部分は周辺2分 recordの過半数で持続しない。
- SVM path との raw 相関は \(B_{sc}\) 共有で説明でき、正規化後の独立相関がない。
- 32.7%の profile interval が探索範囲で truncated し、点推定だけでは過信を招く。

従って package は現在の public field 名を維持できますが、scientific status は candidate のままです。
`effective_field` を「月面磁場強度」と表示せず、`effective mirror field candidate` として grade、
profile interval、truncation、cadence provenance と一緒に扱う必要があります。

## 13. PM003のbinary 2次元境界fit

`fit_binary_loss_cone()` の初期事例として、2008-01-31 14:35 UTCのPM003を再解析しました。
これは全期間再検証ではなく、model実装と見えている鋭いedgeの対応を調べるcase studyです。

| 指標 | smooth count fit | binary surface fit |
| --- | ---: | ---: |
| selected model | `mirror_only` | `mirror_only` |
| $R_m$ | 1.378 | 1.105 |
| $B_{eff}$ | 6.53 nT | 5.24 nT |
| boundary | 約58 degree、広い | 72.1 degree、hard edge |
| contrast band center | constant contrast | 217 eV |
| contrast band width | - | 0.431 in $\ln E$ |
| edge $\Delta$BIC | 143（別尤度） | 43.4 |
| electrostatic $\Delta$BIC | -2.52 | 5.65 |

binary fitは観測面の207--334 eVにある強いedgeを約72 degreeで回収しました。一方、電位項の追加は
既定閾値6へ僅かに届かず、$\Delta U$を含むenergy曲率はまだ採択していません。従ってPM003については
「鋭いenergy局在loss-cone-like edge」は支持されますが、「electrostatic curvatureが確定した」とは
言えません。次に全galleryとblind sampleへ適用し、beam未モデル化時のfalse positiveを調べる必要が
あります。

## 14. Halekas 2008型の全分布fit

energyごとのedge検出を入力にせず、観測したenergy-pitch log ratio面そのものへsynthetic
distributionを最小二乗fitする `fit_halekas_distribution()` を、既存galleryの108ケースへ適用しました。
hard版はloss cone内外の比を0.1/1へ固定します。probit版は同じ物理境界を保ち、
$\ln(\sin^2\alpha)$ 上の遷移幅 $\sigma_{\ln\sin^2\alpha}$ だけを追加します。

| 指標 | hard | probit |
| --- | ---: | ---: |
| log-ratio RMSE中央値 | 0.892 | 0.767 |
| $\Delta\mathrm{BIC}_{hard-probit} \ge 6$ | - | 97/108 (89.8%) |
| 上記かつparameter bounds非張り付き | - | 50/108 (46.3%) |
| parameter bounds張り付き | - | 55/108 (50.9%) |
| $\sigma_{\ln\sin^2\alpha}$ 中央値 | - | 0.717 |

PM003ではhard版が $R_m=1.185$、$\Delta U=-3.13$ eV、RMSE=1.269、probit版が
$R_m=1.054$、$\Delta U=-3.33$ eV、$\sigma_{\ln\sin^2\alpha}=0.101$、RMSE=1.218となり、
$\Delta\mathrm{BIC}_{hard-probit}=7.76$ でした。したがってPM003では小さいが有限の境界幅が
支持されます。

一方、全体ではBIC改善97例に対してbounds非張り付きは50例だけです。特に大きい $\sigma$ が
探索上限へ張り付く例では、probit遷移が明瞭なloss-cone edgeではなく広いpitch-angle勾配を
吸収している可能性があります。このため、現時点ではBICだけで「緩やかなedgeを検出した」と
判定せず、bounds、残差面、隣接時刻での持続性もgateに含めます。

この検証には次の制限があります。

- secondary-electron beamはまだforward modelへ入れていない。
- loss cone内のbackscatter fractionは0.1固定である。
- log-ratio面の各cellをcount uncertaintyで重み付けしていない。
- 108ケースは既存galleryのgrade別層化sampleであり、全期間における現象の発生率を表さない。

比較図、contact sheet、case別parameterは
`working/kaguya-er-fit-review/halekas-paper-comparison/` にあります。

PE007はESA-S1 onlyとESA-S1/S2統合の両方で、hard解が$\Delta U_{eff}=+156$ eV、probit解が
$\Delta U_{eff}=+1000$ eVの探索上限となりました。統合後も符号が維持されたため、曲率反転はS1の視野欠損だけでは
説明できません。ただしprobit幅も上限であり、電位検出としては棄却します。S1/S2比較図は
`working/kaguya-er-fit-review/halekas-paper-comparison-esa1-esa2/images/PE007.png`です。

S1/S2双方が存在する共通103ケースでは、hard $\Delta U_{eff}$の符号がS1-onlyと一致したのは
73/103でした。両fitともparameter bounds非張り付きに限っても57/86であり、30ケースで符号が
反転しました。S1/S2統合後のprobitは64/103がparameter boundsへ張り付きました。従って
$\Delta U_{eff}$の符号は現forward modelでは一般にロバストではなく、PE007の正符号も単独では
物理的電位の証拠にしません。

ESA2 public PBFが存在しない5ケース（GE010、GM012、PM017、PM018、RM019）は統合比較から
除外しました。S1で補完するとfull-FOVという条件を満たさないためです。統合結果は103 images、
26 contact sheets、case別CSVとして同directoryに保存しています。

## 15. S1/S2 global 2次元 model の多数sample評価

S1/S2を先に足し合わせず、sensor固有のcount、exposure、gain、dispersion、native coverageを
残したraw-count negative-binomial joint likelihoodを、2分cadenceの72時刻へ適用しました。
対象は期間を分けた6日で、各日3つの時間blockから4連続sampleを取っています。従って単独の
10分代表点より短時間変動を調べられますが、全期間の無作為標本や現象発生率の推定ではありません。

| 指標 | 結果 |
| --- | ---: |
| 要求 / 完走 / 低count除外 | 72 / 71 / 1 |
| `no_edge` | 42 |
| `mirror_only` | 22 |
| `electrostatic` | 7 |
| edge採択率（完走中） | 29/71 (40.8%) |
| folded log10 ratio residual RMSE中央値 | 0.256 |
| standardized residualの3 sigma内率中央値 | 98.7% |
| 隣接2分pairでedge有無が一致 | 39/53 (73.6%) |
| 隣接pairでselected modelが一致 | 34/53 (64.2%) |

計算量を抑えるscreening設定はincident spectrumを12 knots、optimizerを1 startとしました。
同一4時刻を32 knots、3 starts、最大4000 iterationで再fitすると、model選択とedge有無は4/4一致し、
edge 2件の $R_m$ 相対差中央値は0.51%でした。
4件だけの数値検証なので局所解リスクを否定はできません。実行時間は並列数と同時負荷の影響を
受けるため、この4件のwall time比は性能指標として使いません。今回の母集団図を作る設定としては
大きな系統差を検出していません。

ESAの昇降sweepでは同一時刻のenergy rowが降順または重複する場合がありました。
`GlobalPitchCountObservation.from_spectrum()` はenergyとcount/exposureを一緒に安定sortし、同一energyの
反復測定をcount/exposure空間で加算してからfitするようにしました。これにより順序由来の13失敗は
解消し、残った1件は本当に総count閾値未満でした。

可視化するratio面は `log10(normalized rate)` と `log10(affected/reference)` に統一しています。
raw-count尤度、BIC、正値parameterの内部変換は自然対数のままです。また境界幅
$\sigma_{\ln B}$ は定義自体が自然対数座標なので変更していません。表示の底だけを変えており、
fit parameterとmodel選択は変わりません。

全71 fit画像、6枚のcontact sheet、overview、parameter分布、時間block図、CSVは
`working/kaguya-er-fit-review/global-joint-population-evaluation/` にあります。
日別resumeはfit設定、依存version、評価・pitch・geometry・SPICE関連sourceのSHA-256を記録し、
fingerprintが異なるCSVの混在を拒否します。外部mission archive自体はread-onlyで同一pathの内容が
不変という運用前提です。

## 16. 次に必要な推定 model

優先順は次です。

1. **時間を model に入れる。** native count を window 内で同時 fit し、共通境界と時刻別 contrastを
   分ける。最低持続率を candidate gate にする。
2. **joint likelihoodを全期間へ拡張する。** 今回の6日72時刻をmission全期間の時間層化sampleへ
   広げ、plasma regimeと観測coverageごとのprecisionをblind labelで測る。
3. **独立 blind label を作る。** accepted、poor、no-edge/reject を混ぜ、複数 expert が境界なしで
   label する。precision、recall、inter-rater agreement を事前登録した基準で計算する。
4. **profile 情報を標準 artifact にする。** truncated または相対幅の大きい候補を map から除外する
   sensitivity rule を固定する。
5. **finite-gyroradius forward model を使う。** SVM3D 上で particle trajectory を生成し、既知の
   surface field から instrument count 面までを forward simulate して estimator bias を測る。
6. **plasma regime を追加する。** solar wind、wake、magnetotail、spacecraft potential を外部 dataで
   定義し、時間 block を保った validation を行う。

## 17. 再現方法

主な artifact は `working/kaguya-er-fit-review/` と Store の
`features/kaguya/er/validation/` にあります。外部 dataset は read-only です。

```powershell
$variant = Join-Path $env:SOPRAN_DATA_ROOT `
  "features/kaguya/er/effective_field/variants/robust_counts_v2_600s_p16_e78a09b2d1c7"
$svm = "F:\datasets\spedas_data\globalSVM_v02_2022\LunarSVM_000_02_v02.dat"
$shell = Join-Path $env:SOPRAN_DATA_ROOT `
  "features/kaguya/er/validation/svm3d/svm3d_v2_0p5deg.npz"

python working/kaguya-er-fit-review/run_profile_validation.py --workers 8
python working/kaguya-er-fit-review/evaluate_blind_reaudit.py
python working/kaguya-er-fit-review/validate_esa_pair.py --workers 8
python working/kaguya-er-fit-review/validate_cadence.py --workers 8
python working/kaguya-er-fit-review/build_halekas_paper_comparison.py --workers 8
python working/kaguya-er-fit-review/evaluate_global_joint_population.py --workers 6 --force
python working/kaguya-er-fit-review/evaluate_global_joint_population.py --smoke --force `
  --day 2008-03-10 --spectrum-knots 32 --optimizer-starts 3 --max-iterations 4000 `
  --output working/kaguya-er-fit-review/global-joint-population-reference
python working/kaguya-er-fit-review/evaluate_global_joint_population.py --smoke --force `
  --day 2008-12-25 --spectrum-knots 32 --optimizer-starts 3 --max-iterations 4000 `
  --output working/kaguya-er-fit-review/global-joint-population-reference-edge
python working/kaguya-er-fit-review/evaluate_global_joint_population.py --workers 6 `
  --reference-index working/kaguya-er-fit-review/global-joint-population-reference/index.csv `
  --reference-index working/kaguya-er-fit-review/global-joint-population-reference-edge/index.csv

python -m sopran.missions.kaguya.er_validation $variant `
  --svm "F:\lunarsat_datasets\processed\maps\svm\LunarSVM_000_02_v02.npy" `
  --svm3d-shell $shell --svm3d-source $svm `
  --audit working/kaguya-er-fit-review/period-audit/audit-sample.csv `
  --output working/kaguya-er-fit-review/full-archive-validation-svm3d-v2-0p5 `
  --figure-output docs/assets/kaguya/er-validation
```

固定結果の主な file は次です。

- `full-archive-validation-svm3d-v2-0p5/summary.json`
- `selection_model_performance.csv`
- `blind-reaudit/summary.json`
- `esa-pair-validation/summary.json`
- `cadence-validation/summary.json`
- `svm3d-official-validation.json`
- `svm3d-grid-sensitivity.json`
- Store の `profile_likelihood_600s_p16/summary.json`

## 参考文献

- Saito et al. (2009), [Low Energy Charged Particle Measurement by MAP-PACE Onboard KAGUYA](https://doi.org/10.2322/tstj.7.Tk_7)
- Halekas et al. (2010), [How strong are lunar crustal magnetic fields at the surface?](https://doi.org/10.1029/2009JE003516)
- Tsunakawa et al. (2015), [Surface vector mapping of magnetic anomalies over the Moon](https://doi.org/10.1002/2014JE004785)
- Tsunakawa et al. (2023), [月・火星・水星・地球の磁気異常マッピング](https://doi.org/10.20637/00049167)
