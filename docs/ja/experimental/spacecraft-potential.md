# 衛星電位の代理量と PACE 低レベル表

`sopran.experimental.kaguya.spacecraft_potential`は、PACEのエネルギースペクトルの段差から衛星電位$V_\mathrm{sc}$の代理量を作り、
イベント時刻へ対応付ける試作です。帯電の物理モデルは解きません。
得られる値は「補正の候補と幅」であり、測定した電位ではありません。
lunarsatの2026年5月の試行では、ESAの段差は採用できたものの、イオン側の代理量はESAに対して約$-57\,\mathrm{V}$の系統差が残り、
診断用に留めました。エネルギー分解能と閾値で精度が決まり、全期間での独立検証は行っていません。

## 採用規則

| 代理量 | 条件 | 値 | 適用側 |
|---|---|---|---|
| ESAの`falling`段差 | 昼側（SZA < 80°） | 衛星光電子の境界、$V_\mathrm{sc}=+E_\mathrm{edge}$ | `use_dayside_photoelectron`（既定True） |
| ESAの`rising`段差 | 夜側（SZA ≥ 120°） | 負に帯電した衛星による低エネルギー電子の遮断、$V_\mathrm{sc}=-E_\mathrm{edge}$ | 常に採用 |
| IMA/IEAの低エネルギーイオンピーク | 夜側 | $V_\mathrm{sc}=-E_\mathrm{peak}$ | `use_ion_proxies`（既定False、診断） |

段差は`edge_min_eV`〜`edge_max_eV`（既定5〜350 eV）の範囲で、3点中央値で平滑した$\log_{10}$信号の隣接差が最大の対を取り、
20〜80パーセンタイルの中間を横切るエネルギーを`cutoff_energy_eV`にします。
`quality`は段差の高さ（≥ 0.25 dex）、プロファイルの幅（≥ 0.35 dex）、ビン数、低エネルギー側のカウント比から作る
`quality_score`が1以上のときに立ちます。

## 使い方

```python
import sopran as spn
from sopran.experimental.kaguya import spacecraft_potential as sp
from sopran.missions.kaguya.geometry import lmag_sza

kg = spn.Kaguya()
time = spn.day("2008-04-02")
esa1 = kg.esa1.load(time, calibration=kg.esa1.load_calibration())
times, energy, counts, eflux = sp.energy_spectra(esa1.to_xarray())   # lookを合計したスペクトル
features = sp.cutoff_features(energy, counts, eflux, settings=sp.CutoffSettings())
sza = lmag_sza(kg.lmag.load(time)).to_xarray().interp(time=times.astype("datetime64[s]")).values
cutoff = sp.cutoff_table(times, features, sensor="esa1", sza_deg=sza)
proxies = sp.proxy_table(cutoff)

events = ...  # time_unix と sza_deg を持つ polars.DataFrame（例：ERの窓）
estimate = sp.estimate_potential(events, proxies, settings=sp.PotentialEstimateSettings())
estimate.select("time_unix", "vsc_est_V", "vsc_sigma_V", "vsc_method")
```

`estimate_potential`は次の順で値を決め、どれを使ったかを`vsc_method`に残します。

1. `direct_proxy`：同じ側（昼・夜）の代理量が`direct_tolerance_seconds`（既定60 s）以内にある
2. `time_smoothed_proxy`：採用した代理量の`smooth_window_seconds`（既定1800 s）の移動中央値が`gapfill_max_gap_seconds`以内にある
3. `condition_prior`：同じ側・同じSZA帯（`sza_bin_deg`）の中央値（3行以上）
4. `global_prior`：`global_prior_V`（既定0 V）と`global_sigma_V`（既定60 V）

ERの境界式で使うときは、電子のエネルギー補正が$E-U_\mathrm{sc}$である点に注意してください。
`FiniteBinObservation`などの`spacecraft_potential_eV`へ渡す値の符号は、この表の$V_\mathrm{sc}$（物理的な衛星電位）と同じです。

## PACE低レベル表

`sopran.experimental.kaguya.pace_lowlevel`は、デコード済みのPBF1記録を公開ファイルに近い形の表にします。
ヘッダの整数列（`headers`）、記録ごとの`cnt`・`event`・`trash`の合計と最大値・fill値（65535）のセル数（`counts`）、
IMAでは`0x40`記録のTOFヒストグラムを記録と4つの軸で合計した`(energy_index, tof_index, counts)`（`tof`）です。

```python
from sopran.experimental.kaguya.pace_lowlevel import lowlevel_summary

tables = lowlevel_summary(kg.ima.load(time).pace)
tables["headers"], tables["counts"], tables["tof"]
```

## 制約

- 段差の探索は1記録ずつで、隣接記録の連続性は使いません。`quality`の閾値は夜側の遮断を想定した経験値です。
- 昼側の光電子境界は、太陽活動と周囲プラズマで動く月面電位とは別のものです（Kato et al.）。
- イオンの代理量は、期待される太陽風イオンのエネルギーと冷たいイオン・電子ビームの同時観測で検証するまで採用しないでください。
- 出典：Saito et al. (2010, 2013)、Halekas et al. (2008)、lunarsat `working/kgy-er/notes/kgy-er-spacecraft-potential-strategy-2026-05-02.md`。
