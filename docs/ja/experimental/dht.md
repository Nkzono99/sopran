# dHT座標系のピッチ角分布

`sopran.experimental.kaguya.dht`は、太陽風の流れに伴う電場を消すde Hoffmann–Teller（dHT）座標系へ、
KAGUYA ESAの各look方向の電子速度を移してからピッチ角とエネルギーを計算し直す試作です。
ロスコーンの境界が月面に固定される条件（dHT系）で電子分布を読むために使います。
磁場が月面に沿う向きに近い観測ではdHT速度が定義できないため、適用できる記録はもとの分布より大きく減ります。
通常のピッチ角分布を基準に残し、dHT版は比較として使ってください。

## 速度の規約

lunarsatでの2026年9月の検証（20分区間、59記録）で確定した順序をそのまま実装しています。

| 手順 | 内容 |
|---|---|
| 1 | OMNI HRO 5分値の$\boldsymbol V_\mathrm{GSE}$を、月到達時刻が記録時刻に最も近い標本から取る（`omni_tolerance_seconds`以内） |
| 2 | NASAが除いている地球公転の収差を$V_y$に`+29.8 km/s`として一度戻す（`restore_omni_aberration`） |
| 3 | OMNIの元epochで求めた太陽方向からGSE→J2000へ回し、記録時刻で`MOON_ME`へ回す |
| 4 | 月の地心速度を引き、局所動径を法線としてHT速度$\boldsymbol H_M=\boldsymbol u_M-\frac{\boldsymbol u_M\cdot\boldsymbol n}{\boldsymbol B\cdot\boldsymbol n}\boldsymbol B$を作る |
| 5 | 衛星の月心速度を引き、look座標系（既定`SELENE_M_SPACECRAFT`）へ回す |
| 6 | 各lookの電子速度からこのboostを引き、ピッチ角$\alpha'$とエネルギー$E'$を計算し直す |

月到達時刻は$t_\mathrm{arrival}=t_\mathrm{OMNI}+(R_E\,\mathrm{BSN}_x-x_\mathrm{Moon,GSE})/V_\mathrm{sw}$で、
`arrival_shift="none"`にすると補正しません。月・衛星の速度はSPICE（DE421とSELENEのSPK）の`spkezr`から慣性軸で取り、
回転は3×3の`pxform`だけを使います。

$|\boldsymbol B\cdot\boldsymbol n|/|\boldsymbol B|$が`min_abs_b_normal_fraction`（既定0.15）を下回る記録は`field_tangent`として除きます。
2026年4月のlunarsat全期間runでは、dHT版のfit数は非dHT版の約27%でした。

## 使い方

```python
import numpy as np
import sopran as spn
from sopran.experimental.kaguya.dht import DhtSettings, dht_pitch_angle_spectrum
from sopran.frames import FrameContext
from sopran.missions.kaguya.geometry import lmag_position, lmag_position_gse
from sopran.missions.kaguya.spice import selene_spice_kernels

kg = spn.Kaguya()
time = spn.period("2008-04-02T08:20", "2008-04-02T08:50")
calibration = kg.esa1.load_calibration()
esa1 = kg.esa1.load(time, calibration=calibration)
lmag = kg.lmag.load(time)
omni = spn.omni.hro.load(spn.period("2008-04-02T07:00", "2008-04-02T09:00"))
frames = FrameContext(spice_kernels=selene_spice_kernels(kg.store, time), default_backend="spiceypy")

result = dht_pitch_angle_spectrum(
    pace=esa1.pace,
    time=time,
    calibration=calibration,
    magnetic_field=lmag.magnetic_field,
    position=lmag_position(lmag),
    position_gse=lmag_position_gse(lmag),
    omni=omni,
    frame_context=frames,
    energy_edges_eV=np.geomspace(20.0, 1500.0, 10),
    pitch_bins=16,
    settings=DhtSettings(),
)
result.spectrum            # time x energy band x pitch_angle のカウント（SopranArray）
result.frame.coverage()    # {"records": ..., "ok": ..., "field_tangent": ..., "omni_missing": ...}
result.frame.to_pandas()   # 記録ごとのboost、|B.n|/|B|、OMNIの時刻差
```

エネルギーはシフト後に`energy_edges_eV`の帯へ入れるため、出力の格子は全記録で共通です。
座標`exposure`はlookの応答に$(E/E')^2$を掛けて足した値で、`counts / exposure`がdHT系の微分エネルギーフラックスの近似になります
（Liouvilleの定理）。`exposure_unshifted`は掛けない和、`look_samples`はセルに入ったlook数、
`shifted_energy_mean_eV`と`unshifted_pitch_mean_deg`はセル内の平均です。

部品も個別に使えます。`frame_velocity()`は記録ごとのboostと診断、`shift_looks()`はlook単位のシフト、
`dht_tangential_velocity()`はHT速度、`lunar_arrival_times()`は到達時刻です。

## 制約

- 電場は流れに伴うもののみ消え、静電ポテンシャルは扱いません。`DhtSettings.look_sign`はlook方向を粒子速度の向き（+1）として扱います。
- 記録の除外理由は`frame.status`（`ok`、`omni_missing`、`geometry_missing`、`field_tangent`、`spice_failed`）に残ります。
  図やfitの前に`coverage()`を報告してください。
- SPICEカーネルは地球・月・太陽（DE421）と衛星（SELENE SPK）、月の向き（`MOON_ME`）、衛星姿勢（CK）を含む必要があります。
  `selene_spice_kernels`がこれを満たします。
- 出典：OMNI HRO文書 Appendix 4（収差）、NAIF `spkezr`/`pxform`、
  lunarsat `working/kgy-er/notes/er-dht-velocity-convention-2026-09-27.md`。
