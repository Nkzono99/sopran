# KAGUYA LRS/WFC 波動イベント抽出

この文書は、KAGUYA LRS/WFC のスペクトルから**候補区間**を抽出するための
`KAGUYA_WFC_V1` preset と、その検証・集計上の境界を定める。ここで得るラベルは
自動検出候補であり、物理現象の確定ラベルではない。

## 対象と preset

入力は WFC-H の Ex/Ey power spectral density を想定する。時刻は UTC、区間は
半開区間 `[start, stop)` とする。標準窓は 120 s、step は 60 s で、主な特徴帯域は
次のとおりである。

| 用途 | 周波数帯 (kHz) | 意図 |
| --- | ---: | --- |
| `low_broadband` | 0.1--10 | 低周波広帯域増強 |
| `low_fpe` | 2--30 | 低周波ピーク候補（30 kHz線を一律maskしない） |
| `ridge` | 10--100 | ridge、drift、shift |
| `radio` | 100--500 | 広帯域radio候補 |
| `high` | 500--1000 | 高周波側の診断 |

固定線は全帯域から無条件に削除しない。用途別に次の処置を行う。

| 中心周波数 | 半幅 | 用途 | 処置 |
| ---: | ---: | --- | --- |
| 30 kHz | 2 kHz | `ridge` / `tracker` | ridge scoreと追跡経路からmaskする。`low_fpe`の単独peak判定には一律適用しない |
| 200 kHz | 12 kHz | `radio` | broad radio scoreからmaskし、別のRFI診断には残す |
| 957 kHz | 3 kHz | `high` | high-band派生特徴・cluster入力からmaskし、raw summaryとRFI診断には残す |
| 30/200/957 kHz | 各3 kHz | `clustering` | raw peak位置がクラスタを支配しないよう除外・別特徴化する |

legacy trackerの30 kHz maskは±2 kHz、raw-spectrum clusteringの共通maskは±3 kHz
であり、同じ `FixedLine` を流用しない。200 kHz と 957 kHz は「検出しない」のでは
なく、物理候補のscoreと固定線診断を
分離する。特に 957 kHz の最大値を、低kHz帯で起きたイベントの代表周波数にしては
ならない。preset とその特徴定義は `feature_spec_hash` とともに shard へ保存する。

最小の実行例は次のとおりである。

```python
import sopran as spn
from sopran.analysis.waves import detect_wave_candidates
from sopran.missions.kaguya import KAGUYA_WFC_V1, build_kaguya_wfc_quality_mask

time = spn.day("2008-01-10")
data = spn.Kaguya().lrs.load(time, kind="WFC")
spectrum = data.wfc_ey_power_spectral_density.to_xarray()
quality = build_kaguya_wfc_quality_mask(
    spectrum.values,
    mode=data.wfc_mode.to_xarray().values,
    gain=data.wfc_gain.to_xarray().values,
    fband=data.wfc_fband.to_xarray().values,
    postgap=data.wfc_postgap.to_xarray().values,
)
result = detect_wave_candidates(
    spectrum.time.values,
    spectrum.frequency.values,
    spectrum.values,
    input_scale="linear_power",
    config=KAGUYA_WFC_V1,
    valid_time=quality.valid_time,
    component="Ey",
    source_dataset="kaguya.lrs.wfc_ey_power_spectral_density",
)

window_features = result.features_to_polars()
events = result.events_to_polars(mission="kaguya", instrument="lrs_wfc_h")
```

`confidence` は現段階では閾値から作る未較正heuristicである。比較・順位付けにはraw
`score` を残し、確率として解釈しない。

## quality mask

`build_kaguya_wfc_quality_mask` は、スペクトル値ごとの `sample_valid`、時刻ごとの
`record_valid`、および状態遷移の warning を返す。

- NaN、inf、CDF pad (`254`, `65534`) のスペクトル値は hard invalid とする。
- `Mode`、`Gain`、`Fband`、`PostGap` の NaN/pad は、その時刻を hard invalid とする。
- 有限な `Mode`、`Gain`、`Fband`、`PostGap` の値やその遷移は、それだけで観測を
  捨てず warning とする。安定した非既定モードも科学的に利用できるためである。
- 一部の周波数binだけが欠損する時刻は、有効binを使えるよう `record_valid` を維持し、
  `sample_valid` と `finite_fraction` で欠損を伝える。全bin欠損なら hard invalid である。
- warningを含む窓は自動的に棄却せず、review queueへ回せるよう detector metadata に
  各 warning 数を残す。

`Mode` のraw値を渡してもよい。decoded flagを使う場合は、`xymode` や `omode` を
個別の品質系列として評価し、`fband` は専用引数へ渡す。状態の意味を変える補間は
行わない。

## strict と review の gold 区間

`tests/fixtures/kaguya_wfc_wave_gold.json` は完全なイベントカタログではなく、detectorの
退行を見つけるための小さな anchor set である。

- `strict_intervals` は、品質とスペクトル形状が比較的明瞭で、preset変更後も候補が
  残ることを期待する区間である。
- `review_intervals` は、状態遷移、gap、飽和、固定線、太陽電波などの文脈を人が
  再確認する探索区間である。検出の有無だけでテストを失敗させない。
- gold の「候補種別」は科学的同定ではない。閾値や背景推定を変更したときは、図と
  featureを見直してからmanifestを更新する。
- 2008-01-10 04:55の旧「200 kHz RFI」メモは、実日背景差で195 kHz増強を再現せず、
  215--225 kHz側が約+3 dBだったためreviewへ降ろした。旧ラベルへ合うよう閾値を緩めない。
- 2008-06-18 14:44:36の957.03 kHz spikeは8秒の短時間事象で、120秒medianでは抑制される。
  主detectorから物理候補へ漏れないことをstrictに確認し、検出自体は短時間triageへ分ける。

## coverage で正規化した発生率

発生率の分母は暦時間やファイル数ではなく、対象detectorが実際に判定可能だった
**eligible exposure** とする。detector、成分、周波数帯、preset hashごとに、coverage、
`record_valid`、必要周波数binの有無を満たす時間だけを積算する。

120 s窓を60 sずつずらす場合、窓長を単純合計すると重複分を二重計上する。基本の
実装では、有効なwindow centerにstep相当の時間を割り当て、coverage境界でclipした
非重複時間、または有効時刻区間のunionを `exposure_seconds` として保存する。
`finite_sample_count` はサンプリング周期や周波数bin数に依存するため、exposureの代用に
しない。

集計は例えば

```text
event_rate_per_hour = event_count / (exposure_seconds / 3600)
```

とし、`exposure_seconds == 0` は0件・0率ではなく「未観測」とする。日別shardには
event数だけでなく、eligible/invalid/warningの各秒数、source product、component、
detector名、preset/feature hashを保存する。連結されたeventを日境界で二重計数しない
ため、event IDと半開区間を用いて最終catalogでdeduplicateする。

## WFC-H と WFC-L の境界

WFC-H spectrumから言えるのは `BBN/ESW candidate`、broadband enhancement、ridge、
radio candidateまでである。ESWの確定には、WFC-L waveformで双極性パルスと時間波形を
確認する必要がある。WFC-Hの広帯域スペクトルだけを根拠に `ESW confirmed` としない。

WFC-HとWFC-Lは、reader、source product、coverage、品質条件を別に持つ。WFC-Lが
未取得・未coverageでもWFC-H候補は保存できるが、確認状態は `unverified` のままにする。
後段の照合は共通event IDまたは重なるUTC区間で行い、WFC-Lがない時間を負例として
扱わない。

公開CDF `sln-l-lrs-4-wfc-spectrum-v1.0` とSPEDASの
`idl/projects/kaguya/lrs/kgy_lrs_load.pro` はWFC-H spectrumを対象とする。WFC-Lは
10 Hz--100 kHzのwaveform receiverであり、この公開spectrumや地下探査Sounderの
`sln-l-lrs-2-sndr-waveform-*` とは別製品である。2026-08-07時点でDARTSの公開一覧と
SPEDASに自然波動WFC-L waveformのloader/pathは確認できなかったため、取得できるまでは
dataset registryへ推測pathを登録しない。

`PDC-TI` はUTCではなく、high/middle/lowの3つのuint16 wordからなる48-bit衛星time
counterである。公開APIはexactに表現できるscalar countとraw 3 wordsの両方を保持し、
UTCにはCDF `Epoch` を用いる。TI--UT変換表なしにcounterを時刻へ変換しない。CDFの
`FILLVAL=0` とsparse default padは別であり、WFC support変数ではUINT1の254、PDC-TIでは
`[65534, 0, 65534]` を欠損として扱う。

## shard と clustering

最初のshardには候補区間だけでなく、背景差分、帯域別統計、ridgeの傾き・連続性、
固定線診断、quality warning、coverage/exposureを保存する。clusteringはその再現可能な
特徴shardを入力とし、mission固有readerや生CDFを直接呼ばない。30/200/957 kHzのraw
peakは除外または専用RFI特徴へ分離し、preset/feature hashが異なるshardを暗黙に混ぜない。

探索的clusterは `fit_background_residual_clustering(result.windows.normalized_z)` で作れる。
返る整数IDはfitごとの局所名であり、必ず `cluster_run_id` と組にして保存する。clusterを
物理現象名やnoise判定へ自動昇格させず、解釈済みラベルだけを別versionのdetectorとして
EventCatalogへ書く。

## 参照

- Y. Kasahara et al., “Plasma wave observation using waveform capture in the Lunar Radar
  Sounder on board the SELENE spacecraft,” *Earth, Planets and Space* 60, 341--351
  (2008), DOI [10.1186/BF03352799](https://doi.org/10.1186/BF03352799)。WFC-H/WFC-Lの
  機器境界、およびp.350の12桁hex TI counter記述を参照した。
- NASA/SPDF, [CDF User's Guide](https://spdf.gsfc.nasa.gov/pub/software/cdf/doc/cdf_User_Guide.pdf)。
  CDF_UINT1/CDF_UINT2のdefault pad値を参照した。
- [DARTS KAGUYA archive](https://darts.isas.jaxa.jp/en/missions/kaguya)。公開product境界の
  確認に用いた。
