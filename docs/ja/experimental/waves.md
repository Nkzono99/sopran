# 波動候補の抽出

KAGUYA LRS/WFCのスペクトルから、波動イベントの**候補区間**を抽出する試作です。
検出プリセット`KAGUYA_WFC_V1`、品質マスク、検証用の区間、発生率の分母の決め方をまとめます。
ここで得るラベルは自動検出の候補で、物理現象として確定したものではありません。

## 最小の例

```python
import sopran as spn
from sopran.experimental.waves import detect_wave_candidates
from sopran.experimental.kaguya.waves import KAGUYA_WFC_V1, build_kaguya_wfc_quality_mask

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

`confidence`は今のところしきい値から作った未較正の目安です。比較や順位付けには生の`score`を使い、確率としては読みません。

## プリセット`KAGUYA_WFC_V1`

入力はWFC-HのEx・Eyのパワースペクトル密度です。時刻はUTC、区間は半開区間`[start, stop)`で、
窓の長さは120秒、ずらし幅は60秒です。特徴を計算する帯域は次のとおりです。

| 用途 | 周波数帯（kHz） | 意図 |
|---|---:|---|
| `low_broadband` | 0.1–10 | 低周波の広帯域の増強 |
| `low_fpe` | 2–30 | 低周波のピーク候補（30 kHzの線を一律には除かない） |
| `ridge` | 10–100 | リッジ、ドリフト、周波数の移動 |
| `radio` | 100–500 | 広帯域の電波の候補 |
| `high` | 500–1000 | 高周波側の診断 |

### 固定の線

機器由来の固定の周波数の線は、全帯域から無条件に消しません。用途ごとに次の処置をします。

| 中心周波数 | 半幅 | 用途 | 処置 |
|---:|---:|---|---|
| 30 kHz | 2 kHz | `ridge`、追跡 | リッジのスコアと追跡の経路から除く。`low_fpe`の単独ピークの判定には一律には適用しない |
| 200 kHz | 12 kHz | `radio` | 広帯域電波のスコアから除き、別の電波干渉（RFI）の診断には残す |
| 957 kHz | 3 kHz | `high` | 高周波側の派生特徴とクラスタの入力から除き、生の集計とRFIの診断には残す |
| 30/200/957 kHz | 各3 kHz | クラスタリング | 生のピーク位置がクラスタを支配しないよう、除外するか別の特徴にする |

以前の追跡で使った30 kHzの除外幅は±2 kHz、生スペクトルのクラスタリングの共通の除外幅は±3 kHzで、同じ`FixedLine`を使い回しません。
200 kHzと957 kHzも検出の対象には残し、物理現象の候補のスコアと固定線の診断を分けて持ちます。
特に、957 kHzの最大値を低周波で起きたイベントの代表周波数にしてはいけません。
プリセットと特徴の定義は、`feature_spec_hash`と一緒にシャードへ保存します。

## 品質マスク

`build_kaguya_wfc_quality_mask`は、スペクトルの値ごとの`sample_valid`、時刻ごとの`record_valid`、状態の変化の警告を返します。

- NaN、inf、CDFのpad値（`254`、`65534`）のスペクトル値は無効にします。
- `Mode`、`Gain`、`Fband`、`PostGap`がNaNやpad値の時刻は無効にします。
- 有限な`Mode`、`Gain`、`Fband`、`PostGap`の値や、その切り替わりだけでは観測を捨てず、警告にとどめます。
  安定した既定外のモードも科学的に使えるためです。
- 一部の周波数ビンだけが欠けた時刻は、使えるビンを活かすため`record_valid`を保ち、欠けは`sample_valid`と
  `finite_fraction`で伝えます。全ビンが欠けた時刻は無効です。
- 警告を含む窓は自動では棄却せず、人が見直せるよう、検出器のメタデータに警告の数を残します。

`Mode`は生の値を渡して構いません。分解したフラグを使う場合は、`xymode`や`omode`を個別の品質系列として評価し、
`fband`は専用の引数に渡します。状態の意味を変えてしまう補間はしません。

## 検証用の区間

`tests/fixtures/kaguya_wfc_wave_gold.json`は、検出器の退行を見つけるための小さな基準集合です。イベントを網羅したカタログとしては使えません。

- `strict_intervals`は、品質とスペクトルの形が比較的はっきりしていて、プリセットを変えても候補が残るはずの区間です。
- `review_intervals`は、状態の切り替わり、データの切れ目、飽和、固定線、太陽電波などの文脈を人が確かめ直す区間です。
  検出の有無だけでテストを失敗にはしません。
- 区間に付けた「候補の種類」は科学的な同定ではありません。しきい値や背景の推定を変えたときは、図と特徴を見直してから更新します。
- 短いスパイクは120秒のメディアンで抑えられることがあります。主検出器が物理現象の候補へ誤分類することと、
  短時間用の検出器の検出性能は分けて評価します。

## 発生率の分母

発生率の分母は暦の時間やファイル数ではなく、その検出器が実際に判定できた**判定可能時間**です。
検出器・成分・周波数帯・プリセットのハッシュごとに、データがあり、`record_valid`で、必要な周波数ビンがそろっている時間だけを積算します。

120秒の窓を60秒ずつずらすと、窓の長さを足すだけでは重なりを二重計上します。基本の実装では、有効な窓の中心にずらし幅に相当する時間を割り当て、
データの範囲の境界で切った重ならない時間、または有効な時刻区間の和集合を`exposure_seconds`として保存します。
`finite_sample_count`はサンプリング周期や周波数ビンの数に依存するため、露出時間の代わりにはしません。

```text
event_rate_per_hour = event_count / (exposure_seconds / 3600)
```

`exposure_seconds == 0`は0件・0率ではなく「未観測」です。日別シャードには、イベント数に加えて、判定可能・無効・警告の各秒数、
元のプロダクト、成分、検出器名、プリセットと特徴のハッシュを保存します。日の境界をまたぐイベントを二重に数えないよう、
最終のカタログではイベントIDと半開区間で重複を除きます。Storeのイベントカタログの`rates()`はこの考え方で率を計算します
（[Storeにデータを保存する](../guide/store.md#イベントカタログ)）。

## WFC-HとWFC-Lの境界

WFC-Hのスペクトルから言えるのは、`BBN/ESW candidate`、広帯域の増強、リッジ、電波の候補までです。
静電孤立波（ESW）だと確定するには、WFC-Lの波形で双極性のパルスと時間波形を確かめる必要があります。
WFC-Hの広帯域スペクトルだけを根拠に`ESW confirmed`とはしません。

WFC-HとWFC-Lは、読み込み処理、元のプロダクト、データの有無、品質の条件を別々に持ちます。WFC-Lが未取得でもWFC-Hの候補は保存できますが、
確認の状態は`unverified`のままにします。後の照合は共通のイベントIDか重なるUTC区間で行い、WFC-Lが無い時間を負例として扱いません。

公開CDF`sln-l-lrs-4-wfc-spectrum-v1.0`とSPEDASの`kgy_lrs_load.pro`はWFC-Hのスペクトルを対象にしています。
WFC-Lは10 Hz〜100 kHzの波形受信機で、この公開スペクトルとも、地下探査用サウンダーの`sln-l-lrs-2-sndr-waveform-*`とも別の製品です。
現在の読み込み処理はWFC-Lの波形に対応しておらず、推測したパスをデータセットの登録に入れることもしません。

## シャードとクラスタリング

最初のシャードには、候補区間だけでなく、背景との差、帯域ごとの統計、リッジの傾きと連続性、固定線の診断、品質の警告、
データの有無と判定可能時間を保存します。クラスタリングはこの再現できる特徴のシャードを入力にし、
ミッション固有の読み込み処理や生のCDFを直接呼びません。30/200/957 kHzの生のピークは除くか電波干渉の専用特徴に分け、
プリセットや特徴のハッシュが違うシャードを黙って混ぜません。

探索的なクラスタは`fit_background_residual_clustering(result.windows.normalized_z)`で作れます。
返る整数のIDは当てはめごとの局所的な名前なので、必ず`cluster_run_id`と組にして保存します。
クラスタを物理現象の名前やノイズの判定へ自動で昇格させず、解釈したラベルだけを別の版の検出器としてイベントカタログに書きます。

## 参考文献

- Y. Kasahara et al., "Plasma wave observation using waveform capture in the Lunar Radar Sounder on board the SELENE spacecraft,"
  *Earth, Planets and Space* 60, 341–351 (2008). [doi:10.1186/BF03352799](https://doi.org/10.1186/BF03352799)。
  WFC-HとWFC-Lの機器の境界と、p. 350の12桁16進のTIカウンターの記述を参照しました。
- NASA/SPDF, [CDF User's Guide](https://spdf.gsfc.nasa.gov/pub/software/cdf/doc/cdf_User_Guide.pdf)。CDF_UINT1・CDF_UINT2の既定のpad値を参照しました。
- [DARTS KAGUYAアーカイブ](https://darts.isas.jaxa.jp/en/missions/kaguya)。公開プロダクトの境界の確認に使いました。
