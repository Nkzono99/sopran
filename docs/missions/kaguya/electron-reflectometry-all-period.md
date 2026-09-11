# 全期間の16秒窓ER推定

## 目的と現在の到達点

ESA-S1/S2の同時観測から $B_{\mathrm{eff}}$ と $\Delta U$ を推定し、
上流条件・場所・日照条件との関係を評価するための処理系。
全期間の**実行対象**と**処理完了範囲**は区別する。完了範囲は出力の
`day-inventory.csv` と `progress.json` で確認する。

推定器は `analysis.electron_reflection.integrated`、解析勾配のRust実装は
`crates/sopran-native/src/incident_reflection.rs`。
実行・可視化スクリプトは作業用の
`working/kaguya-er-fit-review/build_mission_incident.py` にある。
このスクリプトは同ディレクトリの既存データ準備・描画ヘルパーを使う。
現時点では配布パッケージの全期間バッチAPIではない。

## 観測とモデル

- UTCの固定16秒窓。120秒間引き、10分サンプリングはしない。
- 窓内のnative観測レコードとS1/S2の区別を保持し、共通の物理パラメータをfitする。
  カウントを単純合算した負の二項分布として扱うものではない。
- 20--1500 eV、有限エネルギー・pitchビンを積分したhard境界。
- 入射スペクトル、3点のエネルギー依存PAD、共通減衰率、センサーgainと過分散を同時推定。
- `no_edge` / `mirror_only` / `electrostatic` と、各々のbeam off/onの6候補。
  multistartと2回の対称的再探索を行う。smooth fitは実行しない。
- beamはauto。Halekas論文の固定0.1/1.0対数分布最小二乗法そのものではなく、
  現行の入射PAD付きカウントモデルを高速化した経路。
- event/trash補正は既存の `event_trash` 校正exposureに従う。
  共通mode 17/18のESA EC-Nは残し、[ESA固有の無効条件](esa-mode-policy.md)を適用する。
- 低カウント・ゼロカウントは有効exposureがあれば尤度に残す。
  補正後の同時scienceレコードがない窓、mode変更、support不足は別に記録する。
  窓coverage/gapだけでは除外しない。

`no_records` は「ESA入力選別とS1/S2時刻整合後にレコードがない」という意味で、
元のESAファイルに観測も校正データもないと断定するラベルではない。
片側だけの観測は今回のjoint推定には含まれない。

## 採択とラベル

| 列・値 | 意味 |
|---|---|
| `fit_label=edge_fit` | 比較対象に対してロスコーンモデルが支持された |
| `fit_label=no_edge` | 探索したモデルではロスコーンなしが採択された |
| `fit_label=edge_quality_rejected` | edge候補は改善したが境界support等で品質不合格。物理的なedge不在とは異なる |
| `fit_label=insufficient_support` | センサー・energy/pitch・カウントsupportが不足 |
| `fit_label=all_candidates_nonconverged` | 全候補が非収束 |
| `fit_label=model_comparison_unresolved` | beam候補も含む6候補のいずれかが非収束 |
| `fit_label=edge_evidence_model_sensitive` | 除外されたnull候補も考えるとedge支持が未確定 |
| `fit_label=not_attempted` | 同時scienceデータなし等。`input_label` に理由 |
| `fit_label=input_error/numerical_error` | 入力準備または数値処理の例外 |
| `field_label=provisional` | edgeあり、現在の感度スクリーニングを通過。確定値ではない |
| `field_label=review_required` | edge候補はあるが制約やモデル選択への感度がある |
| `field_label=not_identified` | 採択されたedgeによる磁場推定なし |

edge採択は $\Delta\mathrm{BIC}\ge6$、静電パラメータ追加は1、beam追加は10。
制約端にあるbeam候補は採択対象外だが、その候補のBICを捨ててedge検出を主張しない。
とくに良いnull候補が残る場合は `edge_evidence_model_sensitive` とする。

`field_flags` は制約端、非収束の競合候補、より良い除外候補、beam感度を記録する。
beam感度はoff/onで磁場比が1.5倍超、または $\Delta U$ の差が30 eV超という
**暫定的な感度検査**であり、信頼区間ではない。
`population_screen_pass` はその検査を通った候補の抽出用。
全結果で `field_identified=False` とし、profile likelihoodや独立データで未検証の値を
「地殻磁場を確実に測れた値」とは呼ばない。

$R_m<1$ を一律に捨てない。ただし数式上の推定可能性と磁場・電位の空間分布の
一意な同定は別問題。窓代表 $R_m$ は代表衛星磁場に対する比で、
nativeレコードごとの比がすべて同じ側にあることも意味しない。

`effective_field_nT` / `delta_u_eff_eV` は採択edgeの候補値。
`mirror_only` の $\Delta U=0$ は制約値であり、電位差ゼロを測定したという意味ではない。
現在の設定は衛星電位 $U_{\mathrm{sc}}=0$ eVを仮定するため、$\Delta U$ はその仮定に
依存する実効量であり、独立検証なしに月面電位と同一視しない。
採択されなかった最良候補は `diagnostic_*` と候補パラメータに分けて保持する。
`sigma_ln_b=0` はhard境界の遷移幅であり、磁場推定誤差ゼロの意味ではない。

## 上流条件

NASA OMNI2の年別ASCIIをStoreに保存し、fill値をNaNに変換する。
時刻は `[HH:00, HH+1:00)` の時間平均として結合し、欠損時間を補間しない。
磁場、流速、密度、動圧、温度、beta、Alfven Mach数、Dstを保持する。
[NASA OMNI仕様](https://omniweb.gsfc.nasa.gov/html/ow_data.html)

OMNIは**地球近傍の上流proxy**であり、かぐや位置の局所プラズマ観測ではない。
月が太陽風中か磁気圏中かは自動断定せず、`lunar_plasma_regime=undetermined` とする。
衛星GSE座標、直下点SZA・経緯度、高度を併記する。
ここでの直下点は磁力線footpointではない。SVMとの比較・磁力線追跡による
footpointの確定や上流伝播時間の再推定は、このバッチにはまだ含めない。

`pressure-sza-summary.csv` は動圧/SZA帯ごとの採用率・暫定磁場の中央値等。
`population.csv` は場所・高度も含む後続解析用の表。
連続16秒窓を独立サンプルとは扱わず、観測日数・OMNI時間数を併記する。
これだけで地理的偏りを除いた因果的な動圧依存性を推定できたとはしない。

## 実行と再開

```powershell
.venv/Scripts/python.exe working/kaguya-er-fit-review/build_mission_incident.py `
  --start 2007-11-07 --stop 2009-06-11 --workers 5 `
  --search warm --audit-every 16 --chain-windows 64 `
  --output working/kaguya-er-fit-review/mission-native-all-period-v6
```

終了日はexclusive。既知の比較例のある2008-08-18を先に処理してから日付順に進む。
原データは既存Storeとfallback archiveから読む。ESA/SPICEを新規にネット取得する
モードではないため、未収録日やloader失敗は `day-inventory.csv` に残る。
NASA OMNI年別ファイルのみ初回自動取得する。
確認したfallback archiveではS1ファイル487日、S2ファイル457日、共通457日
（2007-12-12--2009-06-10）。これはnative時刻の整合後の窓数とは異なる。

- `results.sqlite`: 全窓ラベル・値・候補vectorの原本。1結果ごとにtransactionをcommit。
- `day-inventory.csv`: pending/running/partial/complete/complete_with_failures/input_error。
- `progress.json`, `workers/*.json`: 完了数、処理窓、候補名、経過秒。
- 日別 `index.csv`, `timeseries.png`, `images/`, `beams/`: 表と確認図。
  全窓fitするが、画像は最初の窓と各時の代表窓に限定し大量PNG出力を避ける。

同じコマンドで再開する。非収束・例外の再試行は `--retry-failed`。
`--workers` は1--5で指定でき、既定値は2。現在の実行は5並列。
出力直下の `STOP` ファイルで、実行中の窓（現在は最大5窓）を保存してから停止する。
コード・設定・入力fingerprint・OMNI hashが変わった場合は別出力を使う。
SQLiteが原本であり、CSV/HTML生成に失敗してもfit結果を捨てない。
再試行で以前の収束候補が非収束になった場合は以前の結果を主表に残し、
新しい試行を `attempts` 表に保存する。数値的に改善したと断定して上書きしない。

## 速度と検証

2026-09-08、2008-08-18 13:40:56 UTCの2924有効セルを使った代表例:

| 処理 | Python | Rust |
|---|---:|---:|
| 6候補・multistart・2回再探索 | 84.0秒 | 14.6秒 |
| ロスコーン候補の尤度＋勾配 | 約13--15 ms | 約1.5--1.8 ms |

別例2008-08-19 00:41:44 UTC（3184セル）でも、6候補全体が71.1秒から11.5秒に短縮。
採択されたmirror+beamの $R_m$ はPython 1.449398、Rust 1.449386で一致した。

CPU並列化以外に、FFIで入力を1回だけpackし、解析勾配・角度積分不変量のcacheを使う。
最適化器自体はSciPy L-BFGS-B。画像生成・日別入力準備・上流結合の時間は上表に含まない。
最良のbeam候補は一致したが、非採用electrostatic候補のBICは2例で約4.7、14.8異なった。
同じvectorでの目的関数・勾配の一致と、局所解を含む最適化結果の完全一致は別である。

全候補×beam×PAD有無の期待カウント・尤度・勾配一致、数値微分、
ゼロカウント・欠損・異なる衛星磁場と半球、初期解保護、ラベル、OMNI結合をテストする。
### 応答計算の再利用による追加高速化

同日の追加測定では、旧Rust経路のfit時間の約94--96%がRustの目的関数評価だった。
同一エネルギー・pitch bin・spectrum/PAD基底の応答を1評価内で再利用し、
sensor別の負の二項分布定数もまとめて計算する。衛星磁場、半球、exposure、
応答重み、境界との部分積分はセルごとに保持する。
探索候補、初期値、反復予算、採択条件は変更しない。

| UTC時刻 | 旧Rust | 応答再利用後 | 倍率 | 目的関数評価回数 |
|---|---:|---:|---:|---:|
| 2008-08-18 13:40:56 | 14.62秒 | 4.59秒 | 3.19 | 6373 |
| 2008-08-19 00:41:44 | 11.33秒 | 3.41秒 | 3.32 | 4638 |
| 2008-08-20 19:04:56 | 19.16秒 | 5.82秒 | 3.29 | 6940 |

各構成2--3回実行し、cProfileを有効にした初回を除く中央値。
3例とも6候補すべてのBIC・パラメータvector・評価回数が旧Rustと完全一致した。
これは上記のPython対Rust比較とは別の、Rust内最適化前後の比較である。
固定vectorの尤度・勾配・予測値も保存した旧binaryとbitwise比較する回帰テストを通した。
測定原本は `working/kaguya-er-fit-review/incident-response-reuse/`。

`v2` は427窓の処理結果（423 fit本体と4失敗記録）を保存して停止し、
nativeのみの変更であることをhash検証して `v3` に引き継いだ。
未解析ラベルも含む3933行について元の値・fit本体の一致を確認した。
`parent-run.json` と各行の `record_origin_code_hash` に元の来歴を保持する。
旧出力は上書きせず、SQLite backupと出力lockを使って移行する。

これは3例のfit単体の測定で、全期間の完了時間ではない。
仮に50万窓すべてが4.59秒なら2並列で約13.3日だが、窓ごとの探索時間差、
入力準備・画像生成・CPU競合は含まない。全期間の有効窓数と実測速度を蓄積して
所要時間を更新する必要がある。

### 境界・カウント再利用とwarm-start試験

追加のRust最適化で、同じ `(energy, Bsc)` の境界角と `(sensor, counts)` の
負の二項尤度の特殊関数を1評価内で再利用した。上記3例でさらに1.15--1.22倍となり、
全6候補のBIC・vector・評価回数は完全一致した。現在の本処理はこの `v4` を使う。

別途、前の16秒窓のvectorと当該窓の初期値を使って探索数を減らす実験を行った。
4区間・32窓のうち28比較窓で合計2.48倍（初回の全探索4窓を含めると2.09倍）に
なったが、モデル等の採択一致は25/28、fitラベル一致は27/28だった。
同一モデルでも磁場候補が約54%、電位差が約54 eV変わる例があり、
この初期試験の単純な探索削減は本処理に採用しなかった。
良い局所解を見つける場合もあるため、全探索結果との違いを一律に誤りとはしない。
ただし現状は全探索相当のロバストさを確認できていない。
詳細・比較図は `working/kaguya-er-fit-review/incident-temporal-speed/README.md`。

### 監査付きwarm-start

2026-09-09に `analysis.electron_reflection.temporal` と全期間runnerへ組み込んだ。
**前の窓から引き継ぐのは初期パラメータのみ**であり、カウント、尤度、事前分布は
引き継がない。磁場・電位を時間的に平滑化した推定ではなく、各16秒窓の独立fitである。

- no-edge / mirror-only / electrostatic、それぞれbeamなし・ありの全6候補を維持する。
- 直前の同候補のvectorと当該窓の初期値に加え、独立した磁場・電位の初期値を残す。
  beamは70/150/800 eVの初期値と、振幅がほぼゼロの初期値も評価する。
- 候補間のパラメータ交換による再探索は1回。従来の全探索は2回のまま残す。
- 64窓単位のUTC固定区間を最大5区間並列に処理し、各区間内では前の窓のcommit後に
  次を投入する。途中再開でもSQLiteの直前の保存vectorを使う。区間境界では初期化する。
- 前窓なし、16秒を超えるgap、sensor構成/エネルギー基底端点/半球/設定の変化、
  前窓の未収束候補、観測磁場2倍超の変化などでは初めから全探索する。
- 粗いenergy/pitch/半球ごとのrate変化が中央値3倍超または90%点5倍超、
  有効featureの欠測変化25%超でも全探索する。これらは計算方式を切り替える経験的条件で、
  観測を捨てるフィルターではない。変化検出の半カウント補正を実fitへ混ぜない。
- UTC16窓ごとの監査、非収束、候補比較BICの採択しきい値から1以内では、warm探索に
  独立した全探索を追加する。候補ごとに低いBICの解を保存し、両方のvectorと比較も残す。
  良いBICでも未収束なら、収束済みの悪い解へ黙って置き換えず未解決として扱う。
  warm探索の数値例外でも全探索を試す。

隣の窓からモデル・ラベルが変わっただけでは全探索しない。実際の時間変化も含むためである。
初期実装でこの条件とsupport境界付近を一律に全探索すると、大半の窓で二重探索となった。
元のsupport・beam品質・BIC・磁場解のスクリーニング自体は変更していない。

`--search full` で従来の独立multistart全探索を選べる。方式変更時は別の出力先を使う。
`search_mode` は `full` / `warm` / `refined`（warmと全探索の比較後）で、
`search_reasons`, `search_seed_status`, `search_previous_time_ns`, `search_audit` を保存する。
`search_audit` は監査した窓の全6候補のBIC・vector・採択結果を含む。
監査されていない窓について、全探索との同値性や大域最適解を保証するものではない。

旧v5結果はSTOPとlockを確認し、SQLite backupで別のv6へコピーする。
旧runnerと未変更のモデル・入力処理・native binaryのhashを照合し、既存fit値を保持する。
既存行は全探索由来と明記し、元のcode hashも保持する。旧行にはwarm状態を捏造せず、
その直後の新しい窓は全探索から始める。全期間完了ではなく、未収録・loader失敗日は
引き続き日別inventoryに区別して記録する。

最終版の比較原本は `working/kaguya-er-fit-review/incident-temporal-audited-v3/`。
`comparison.csv` は窓ごとの時間・採択・候補BIC差、`results.json` は全探索とwarmの
全候補・監査内容、`config.json` は入力・コードhashを含む。

最終版の4区間・32窓では、全探索128.91秒に対して監査付きwarmは130.48秒で、
**全体の高速化は確認できなかった**。warmのみで完了した21窓に限ると約1.09倍だが、
初回/変更検出の全探索8窓と追加監査3窓の費用も含めて評価する必要がある。
採択モデル・beam・理由の一致31/32、fitラベル31/32、磁場ラベル30/32。
3窓では少なくとも1候補のBICが全探索より1超悪く、非採用候補で最大284.69の差が残った。
一方、warmから良い局所解を得る候補もある。独立探索を削った初期版の2.48倍を
この監査付き構成の速度として使ってはいけない。

5並列の実データ試験は23窓fitでSTOPし、SQLiteを閉じてから12窓を追加した。
元の4953行（未解析ラベルも含む）とfit blobが不変で、追加12窓のseedはすべて
checkpointからロードされることを確認した（変化検出による全探索への切替は別）。
試験では短い区間で並列/監査を検証するためchain=8、audit=4とし、
本処理はchain=64、audit=16を使う。
旧v5からは10781行、1894 fit blobと日別inventoryの不変を確認してv6へ引き継いだ。

### 入力の除外と公開欠測

全期間runnerは `--download missing` を既定とし、足りないESA1/ESA2/LMAGを
SPEDASと同じ公開productからStoreへ取得する。LMAG nominal/optionalは代替候補であり、
両方を必須にしない。既存ファイルは再取得しない。

- `excluded_by_record_policy`: 要求UTC日に入力はあるが、ESA固有の無効条件や
  未対応形式の除外後にS1/S2同時入力がなくなる。空配列を「校正不足」と誤判定しない。
- `no_joint_records`: 要求時間・時刻対応後にjoint入力がない。
- `source_unavailable`: 必要productの公開URLが404/410。設定済み公開先での欠測であり、
  未公開の原観測まで存在しないとは断定しない。
- `input_error`: 通信障害、校正不足、decode/geometry等の処理失敗。公開欠測とは区別する。

`--download never` はローカル不足を未確認として扱い、公開欠測とはしない。
`--retry-failed` は `source_unavailable` の再照会にも使える。
`input-availability.json` にURL、HTTP結果、取得先を記録する。
取得はatomicで、接続/readの既定timeoutは60秒。途中切断・Content-Length不足を
成功扱いしない。通信失敗を公開欠測に置き換えない。
配列の `record_selection` には要求日内のraw数、理由別除外数、eligible数、対応数、pitch数を残す。

以下は旧 `exclude_calibration_v1` に基づくv7時点の記録であり、現在の除外理由ではない。
17/18を残す新規則への変更と再評価は [ESA入力フィルター](esa-mode-policy.md) を参照。

2026-09-09の監査では、旧161入力エラー日のうち107日はmode除外後の空配列、
53日は確認した公開productの欠測、1日（2008-02-29）はローカル未取得だった。
この1日はESA1/ESA2/LMAGを取得・decodeできたが、当時のmode除外後は空だった。
0x11/0x12はTOFCAL/POSCALである一方ESA Electron Checkを含むため、
この除外方針と「ESA観測そのものがない」は区別する。
正常日2008-04-28の9,524組では修正前後のcounts/exposure等と入力fingerprintが完全一致した。
調査原本と出典は `working/kaguya-er-fit-review/mission-input-audit/README.md`。
v7移行時には旧75,327行の値・warm状態と3,445 fit blobすべての一致を確認した。
