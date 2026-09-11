# ERのフィルター・サンプリング条件の棚卸し

2026-09-09。棚卸しの基準は `mission-native-all-period-v8` と
`working/kaguya-er-fit-review/build_mission_incident.py` の実行経路。
最初の棚卸しでは並列数だけを5から3へ変更した。以下の追補で入力処理を改善した。
一般API `fit_global_joint_effective_field()` の全オプションが、このbatchでも動くわけではない。

## 実装した改善

supportはユーザーの指定どおり、**総count 100、pitchセル6以上のenergyビン3以上**などを
維持する。BIC、beam採択、窓coverage/gapによる非除外の方針も変更していない。

- **補間:** pitchとERで同じbounded interpolationを使う。指定区間の前後8秒もLMAGを
  読み込み、区間端の有効な補間点を確保する。追加の日のファイルがなければ端値で代替しない。
  必要な区間のファイル欠損は従来どおり別の入力エラーとして扱う。範囲外はNaN、補間元の間隔が
  8秒を超えた場所もNaN。実際に値がある時刻は、隣に長い欠測があっても使用する。
  sourceのNaNを取り除いてから補間する処理はしない。4月11日と8月18日の公開LMAGで
  4秒cadenceを確認し、1サンプル欠損まで許す8秒を暫定値とした。物理的定常性の保証ではない。
- **S1/S2:** `kg.er.pitch_angle_spectra(..., align=False)` を追加。
  両sensorの独立した元時刻を保持し、1対1ペアの事前選別を行わない。
  `fit_timeseries()`と全期間runnerはこの経路を使う。従来の単一時刻用paired APIは
  `align=True`で残り、その場合だけ`max_time_offset_seconds`が働く。
- **16秒窓:** recordの中心時刻で一つのUTC窓にだけ割り当てる。index用配列は時刻の和集合で
  揃えるが、`record_present=False`は観測ではない。カウント、energy、exposureは補間しない。
  0 countは観測として保持し、欠測、paddingとは区別する。取得区間が隣の窓にまたがっても、
  countを複製・割合分割しない。厳密な取得区間の重なりを用いた尤度ではない。
- **幾何欠測:** 非有限/ゼロ磁場、無効位置、厳密に接線方向で側を定義できないrecordは
  尤度に入れない。残りのrecordは保持し、片側sensorが全て使えない窓には
  `ESA-S1_geometry_unavailable`等の理由を付ける。pitch構築前の幾何欠測は入力選別統計にも残す。
- **診断:** `sensor_records`、`geometry_rejected_records`、sensor間最近傍時刻差の最大値、
  `field_radial_abs_cosine_min`を出力する。窓内の4秒LMAGから方向の最大偏差[deg]、
  方向平均の長さ[無次元]、強度の変動係数[無次元]、有効/無効サンプル数も記録する。
  これらは新しい足切りではない。LMAG欠測・大きな変動・接線方向を後から監査できるようにする。
- **磁場の解釈:** `field_connection_status='not_evaluated'`を明記。
  `B dot r`の符号だけで月面への接続を確定しない。runnerの`magnetic_interpretation`は
  非検出=`not_identified`、採択された$R_m<1$=`subunity_boundary_parameter`、
  それ以外の採択edge=`provisional_mirror_field`とする。いずれも`field_identified=False`を維持する。
- **再現性:** `bounded_geometry_v2`と`independent_native`を入力fingerprint/cacheへ含める。
  旧v8は停止・保存し、異なる入力処理の結果をその出力へ追記しない。

S1/S2の件数が違うと、異なる時刻を1回ずつ数えたBの中央値と、尤度に使う全sensor観測の
Bの中央値は一致しない場合がある。fit後の`b_sc_nT`は後者とし、
`effective_field_nT = mirror_ratio * b_sc_nT`と整合させる。
前者は`record_time_median_b_sc_nT`に別途保持する。

`records_integrated`は使えたrecordの異なる時刻数で、S1/S2のペア数ではなくなる。
幾何欠測で除外した時刻も含めたindex数は`input_record_timestamps`へ別に保存する。
sensor別の件数は`sensor_records`を使う。`window_coverage`は少ない側のrecord数を
参考のexpected数で割った診断値であり、取得区間の重なり率ではない。

まだ実装していないのはprofile likelihoodによる区間推定、物理的な磁力線追跡、
衛星電位の同時推定、取得区間内のpitch変化を応答に積分する処理。
方向変動が大きいことを記録できても、それによる分布の広がりを補正したことにはならない。

小規模実データ検証と画像は
`working/kaguya-er-fit-review/geometry-native-audit/validation-v3/`へ出力した。
3日分の入力比較ではS1/S2合計2,143件のrecordを追加保持した。共通recordは日末の
23:59:58の1件/センサーを除いて完全一致し、その1件は翌日の実測磁場によるpitch割当の修正。
元の総countは保存される。代表8窓を可視化し、再比較した6例の判定は変わっていない。
以下の表・再現例・数値は**修正前v8の棚卸し記録**として残す。

## 結論

全期間の候補を広く残し、**入力が物理的に定義できる条件、fit可能性、磁場の同定可能性**を
別々に判定する構成がよい。一律に厳しいfilterを追加する方針ではない。

優先順位は次のとおり。

1. **補間の欠測・範囲外チェックと、S1/S2時刻条件の矛盾を先に修正する。**
2. 同時観測を一対一ペアではなく、各センサーの取得区間と16秒窓で扱う案を検証する。
3. 窓内の磁場方向変動・定常性・月面接続の診断を追加する。まずflagとして保持する。
4. support条件を感度試験し、情報量・不確実性に基づく判断へ近づける。
5. モデル比較の失敗と磁場の非同定を分け、profile likelihood等で $B_\mathrm{eff}$ と $\Delta U$ の縮退を調べる。

SZA、上流圧、磁気圏/太陽風領域、SVM強度そのものによる一律除外は勧めない。
これらは調べたい説明変数なので、層別集計に使い、検出率と失敗率も併記する。

## 実際の経路

```text
PACE原カウント + INFO校正 + LMAG + SPICE
  -> ESA record policy
  -> S1/S2時刻対応 -> 各センサーのenergy-pitch配列
  -> UTC 16秒窓 -> 個別native recordを保持
  -> temporal.fit_candidates -> integrated -> IncidentProblem
  -> 6候補のカウント尤度fit -> BIC/境界support -> fit_label/field_flags
```

実際のfitは入射PAD付きshared hard境界の**負の二項カウントモデル**。
folded画像にedge検出を行ってからfitする経路ではない。
S1/S2や窓内native recordは、共通の物理パラメータを持つ別観測として尤度へ入る。

## 取得・入力・時間窓

| 段階 | 実行中の条件 | 評価 |
|---|---|---|
| 期間 | 2007-11-07以上、2009-06-11未満 | 全期間指定。処理完了を意味しない |
| ダウンロード | 不足する公開ESA1/ESA2/LMAGを取得。404/410と処理エラーを区別 | 必要。未取得を観測不在と混同しない |
| ESA mode | `esa_look_quality_v2`、17/18は残す。既知無効組合せ等は除外理由付き | 維持。未確認の特殊modeは後で個別検証 |
| 対応形式 | type 0/1。type 2は搭載側pitch集約済みで未対応 | 物理的無効ではなく実装上の制約。別経路の余地あり |
| 校正 | INFO校正、正のsampling time、calibrated exposure必須 | 必要。missingをequal exposureで代替しない |
| event/trash | `event_trash`。raw countsを保持し、補正係数をexposureへ反映 | 維持。補正係数の極端さ・欠損割合の診断は追加候補 |
| 欠損カウント | 65535等の欠損をNaN。有効exposureのないセルはfitに入れない | 必要 |
| pitch | 0--180度を16等分、11.25度/ビン、各セルに有効lookが1つ以上 | 計算上の選択。単一lookと十分な角度coverageは同義ではない |
| S1/S2対応 | 一対一の最近傍、最大時刻差1秒、使ったrecordを再使用しない | **見直し候補**。片側だけのrecordを捨てる |
| 日別入力 | 対応後にS1/S2のtimestamp完全一致を要求 | **1秒許容との矛盾**。後述の最小再現で確認 |
| 間引き | `cadence_seconds=None`。120秒・10分等の間引きなし | 維持 |
| 時間窓 | UTC固定16秒、中心時刻でrecordを割当、窓内の全recordを保持 | 基準として維持。取得区間の厳密な重なり積分ではない |
| coverage/gap | `minimum_records=1`。coverage/gapを理由に窓を除外しない | 維持。実効exposureと定常性は別途評価する |
| mode切替 | type/submode/RAMまたは共通mode変化で窓を保留。ただし17↔18のみは許す | 応答が変わるかで判断する方向がよい。共通modeだけの変更は過剰な場合がある |
| 月面側反転 | `B dot r`から各recordの側を決定。`affected_side_changed`を記録 | **現状は反転だけで窓除外しない**。方向不安定性の診断が不足 |

EC-Nは16秒record1件、それ以外は通常2秒record約8件で16秒窓を構成する。
EC-Nを8秒窓へ分けても独立な8秒観測にはならない。16秒record内部の方向変動は
中心時刻1点の磁場だけでは見えず、高時間分解能LMAGで別途診断する必要がある。

根拠コード: `missions/kaguya/{esa_quality.py,pitch.py,er_timeseries.py}`、
`build_shared_week.py:load_day/skip_reason`、`build_mission_incident.py:run_day`。
[ESA modeの詳細](esa-mode-policy.md)

## Fit前の条件

| 条件 | 実効値・意味 | 評価 |
|---|---|---|
| Energy | 中心値20--1500 eV。energyビンの下端が衛星電位より大きい | 基準帯域として妥当。高磁場で境界が帯域外なら上限/下限推定も残す |
| 衛星電位 | `spacecraft_potential_eV=0`固定 | **仮定であって計測結果ではない**。低energyの系統誤差の評価が必要 |
| 個別セル | counts有限かつ0以上、exposure有限かつ正 | 必要。0や1 countを一括削除していない |
| センサー数 | 有効観測を持つsensor groupが2つ以上 | 現行joint構成の制約。単独センサー専用の縮退診断付き経路は検討可能 |
| 総カウント | 窓・両センサー・対象帯域の有効raw counts合計100以上 | 経験的な足切り。磁場情報量そのものではない。50/100/200の感度試験候補 |
| 個別sensor support | 24分割の共通energy診断格子上で、異なるpitchセル6個以上のenergyビンが3個以上 | **6個という条件は調整余地あり**。片側が狭いFOVの場合を落とし得る |
| 半球baselineのanchor | 少なくとも1センサーにaffected/reference両側のsupportがあるenergyビンが3個以上 | 現行の自由なsensor gain/baselineを識別するため重要。単純に撤去しない |
| センサー間energy重複 | support格子で3ビン以上の重複により固定gainセンサーへ接続 | 現行モデルの識別性に関係。校正gainの事前情報を入れる場合は再検討可能 |
| 角度応答 | energy方向8点、hard境界位置で分けたpitch区間にGL12点 | 有限分解能のため必要。cfgのpitch=64がそのまま主尤度の積分点数ではない |

supportはカウント数によらない有効セルの幾何学的coverageで、同じpitchセルを時間積分した
回数だけ増やして条件を満たすものではない。総count条件とは別である。
24energyビンはsupport・境界診断にも使うが、尤度を24ビンに事前rebinしてはいない。

根拠コード: `global_joint.py:_prepare_observation/_validate_global_support/_sensor_window_support`、
`temporal.py:fit_candidates`、`incident.py:IncidentProblem`。

## 探索・採択・表示

| 種別 | 現在の条件 | 評価 |
|---|---|---|
| モデル候補 | no_edge/mirror_only/electrostatic × beam off/onの6候補 | 維持。beamを常時採用するのではない |
| 探索範囲 | $R_m=0.001$--1000、$\Delta U=-500$--1000 eV | 事前制約。端の解を物理値として確定しない |
| 最適化 | L-BFGS-B、解析勾配、maxiter=500、ftol=1e-9、maxls=60 | 計算条件。full searchも数学的な大域最適性の保証ではない |
| 全候補の収束 | 6候補すべて成功しないと比較未解決扱い | 保守的。競合しないbeamの失敗で全体を落とす場合の感度検証余地あり |
| Edge採択 | 対no_edgeの $\Delta\mathrm{BIC}\ge6$ | 経験的な証拠基準。現状維持し、null合成データで偽陽性率を校正する |
| 曲率追加 | mirrorが支持される場合は対mirrorで $\Delta\mathrm{BIC}\ge1$ | ユーザー指定の緩い比較基準。維持 |
| Beam採択 | off/onとも収束、beamパラメータ非境界、品質検査合格、$\Delta\mathrm{BIC}\ge10$ | 現状維持し、広いbeamがbaselineへ化ける例を監査 |
| 境界端 | field、DeltaU、contrast、hemisphere baselineの探索端でedge候補を棄却 | 端では不確定とすることは必要。ただし全て同じ「不良fit」にはしない |
| 境界bracketing | 遷移域のenergyビンが3以上、両側1セル以上が80%以上、両側2セル以上が50%以上 | 幾何学proxy。**不確実性そのものではない**。境界をまたぐ1セルは両側に数える |
| 除外されたnull | 採択候補が最良の収束nullをBIC6以上上回らない場合、model-sensitive | 必要。都合の悪いno_edge候補を捨てて検出と呼ばない |
| Field flags | 任意パラメータの境界、より良い除外候補(BIC差>1)、beam有無で磁場比>1.5またはDeltaU差>30 eV | fit結果は残してreview扱い。nuisanceの境界と物理量の境界を分ける余地あり |
| 識別済み磁場 | 全件 `field_identified=False`。flagなしedgeもprovisional | 妥当な留保。次は区間推定・縮退判定を実装すべき |
| 図のreliable | folded両側exposure、合計5 raw counts以上、log10比の標準偏差0.5以下 | **診断マスクでありfit入力の足切りではない**。半count事前項も尤度に足さない |
| PNG作成 | batchは毎時の先頭窓と各起動/日の最初のtask等を描画。未fit等で図が出ない場合あり | 計算の間引きではなく描画のみの間引き。全窓PNGではない |

`fit_label`はedge検出/非検出/未解決を表し、`field_label`と`field_flags`は
磁場値の利用可否を別に表す。`no_edge`を磁場0、support不足を弱磁場、
`edge_fit`を確定した地殻磁場と読み替えてはいけない。

### Warm-startはデータ選別ではない

64窓単位のchain、16窓ごとのfull監査。前時刻との差16.01秒超、分布変化
(中央値3倍、90%点5倍)、有効coverageの変化25%超、磁場強度2倍超などでfull searchへ戻る。
**これらの閾値で観測を捨てていない。** 前窓から引き継ぐのは初期値で、尤度・事前分布・時間平滑化ではない。

### configにあるが主経路では働かない項目

`smooth_screening`, smooth/contrast/beam screening用の反復・pitch設定、
`contrast_model='auto'`, `optimizer_starts=4` をそのままbatchの実効条件と読まない。
integrated/temporal経路は独自のseed群で6候補をfitし、hard/constantを明示指定している。
sharedでは `hemisphere_baseline_knots=4` でも実効baselineは1係数。
通常global経路のresidual/correlation品質閾値やprofile設定も、現在の採択・区間推定としては使われない。
今後は `effective_run_settings.json` のように実際に使った設定だけを別途出力すると分かりやすい。

## 確認できた欠落・矛盾

### 1. 補間された磁場が有限でも、観測で裏付けられているとは限らない

fit用 `er._vectors_at` とpitch用 `_magnetic_source_vectors` は `np.interp` を使い、
長いギャップを跨ぐ補間と範囲外の端値保持を制限していない。
10分離れた磁場2点に対して、5分の位置と範囲外±10秒で有限ベクトルが返ることを最小再現で確認した。
これは当該ギャップが実際のv8観測に存在すると確認したという意味ではない。

**追加すべき条件:** source範囲内であること、補間元間隔・最近接サンプル距離の記録、
許容ギャップを超えた時刻の無効化。許容値はLMAGの通常cadenceと欠損分布から決める。
SZA/GSE診断の `context_vectors` には既に範囲外と60秒超gapのmaskがあるが、fit入力には適用されない。
その60秒を根拠なくそのままfitへ流用するのではない。

### 2. 「1秒以内で対応」と「完全に同じ時刻」が併存する

0.5秒ずれた2recordはpitchの対応付けには通るが、`load_day` は
`Sensor timestamps are not aligned` で日全体をエラーにすることを最小再現で確認した。
設定上の許容差が実際のデータ受入条件と一致していない。

**改善案:** sensorごとの真の時刻を保存し、各取得区間が重なる16秒窓に所属させる。
同一窓だから同一状態とは限らないので、実時間差・区間重なりを診断する。
時刻を単に上書きする、許容差だけを16秒へ広げる、同じrecordを複製する修正は避ける。

### 3. 1点の向きと、窓内の定常性・月面接続は別

`B dot r`の符号はoutgoing側を決めるが、磁力線が月面に到達する証明ではない。
ほぼ接線方向の磁場に対する信頼度閾値はなく、ちょうど0や非有限値は現状例外になる。
窓内の反転や大きな方向変動を診断し、必要なら短い窓・時間依存モデル・角度応答の拡幅で扱う。
単純に全反転窓を捨てるかどうかは、分布の変化とモデル予測を比べて決める。

追加候補は、LMAG由来の方向ばらつき、強度ばらつき、接線角、直線/磁場モデルでのfootpoint、
16秒内の入射rate変化、gyro半径と場のscale長の比など。ただしSVMは仮定を含むモデルであり、
SVMと一致する解だけを採る循環的な検証にはしない。

### 4. 「fitできる」と「磁場を測れる」の区別を強める

境界が見えても $R_m$ と $\Delta U$ が縮退したり、観測帯域で磁場にほとんど感度を
持たなかったりする。profile likelihood、パラメータ相関、境界予測の区間、対nullの予測残差を
追加し、`field_identified` / `potential_dominated` / `upper_or_lower_limit` /
`unresolved` 等へ分けるのがよい。これらは現状のラベルではなく提案。

衛星電位の補正は低energy解析の重要な前提である。
[Halekas et al. (2008)](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2008JA013194)
は分布全体と衛星電位を考慮して月面電位を推定している。
また、低energyのbeam/conic、速度座標系の違い、非断熱効果による説明の可能性があるため、
beamがあること自体を異常として切るべきではない。
[Halekas et al. (2012)](https://link.springer.com/article/10.5047/eps.2011.03.008)
ここから上記の診断を優先するのは、本パッケージに対する改善提案であり論文の閾値の転用ではない。

## まず試す比較

本処理の条件をまとめて変える前に、次を**一項目ずつ**比較する。

- 時刻整合: 現行の厳密ペア vs sensor別native時刻・取得区間を保持した16秒窓。
- support: 6 pitchセル vs 4。ただしbaseline/gain識別のanchorは維持し、区間幅と偽陽性を比べる。
- count: 合計50/100/200。採択率だけでなく、null注入・模擬edge注入で誤検出率と回復率を測る。
- 時間幅: 2秒native期間で8/16/32秒を比較。EC-N16秒は独立な8秒に分解しない。
- 境界support: 現行80%/50%を基準に、bracketing値とfieldのprofile幅の相関を調べる。
- 収束: 競合候補の再探索を行い、非競合候補の失敗が採択を妨げる頻度を測る。

上流圧・SZA・場所・高度・mode別に分母を残す。低密度領域でcount不足が増えることを
無視して「通過例の平均磁場」だけを比べると、上流条件依存と選別効果を混同し得る。
現行OMNIは近地球の時間平均proxyで、月の局所上流や伝播遅延を確定した値ではない。
磁気圏内も含めた環境ラベルとOMNI適用可否は別に持たせるのがよい。

## 今回の実測範囲

`working/kaguya-er-fit-review/selection-policy-audit/snapshot.json` に再現結果とrun設定を保存した。
02:17:58 UTC時点のv8は4月11日の途中で、記録862窓中、no_recordsが581、
count不足が64、edge_fitが148、edge_quality_rejectedが38、no_edgeが22、model-sensitiveが9。
未fit窓は日全体について先に書かれ、fitはchain順・非同期で進むため、
**この割合はランダムサンプルでも全期間成功率でもない。**
この時点のsupport不足64件はすべて合計count<100で、pitchセル条件が原因の例はまだない。
3 workerで再開し、既存checkpoint・科学設定のhashを維持した。
