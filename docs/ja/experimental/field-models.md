# 磁場モデルと軌道の道具

ER結果を磁場モデルや環境条件と比べるための試作です。いずれも結果を返すだけで、Storeへ自動保存しません。

| 道具 | モジュール | 用途 |
|---|---|---|
| テスト粒子軌道 | `sopran.experimental.moon.test_particle` | SVM3D＋一様外部場での電子軌道（Boris法、磁場のみ） |
| 閉じた磁力線の島 | `sopran.experimental.moon.closure` | 格子上の閉じたセルを連結成分にまとめる |
| 磁場残差と静穏基準 | `sopran.experimental.kaguya.field_residual` | 観測磁場とモデルの差の分解、静穏時の中央値基準 |
| 環境応答の回帰 | `sopran.experimental.statistics.ridge` | 標準化リッジ回帰、軌道単位の交差検証、外部場のゲイン |

## テスト粒子軌道

```python
import numpy as np
from sopran.experimental.moon.svm3d import SVM3DShellGrid
from sopran.experimental.moon.test_particle import (
    TestParticleSettings, electron_velocity_me, trace_test_particles,
)

grid = SVM3DShellGrid.load("svm3d_shell_grid.npz")
r0 = np.array([[1737.4 + 100.0, 0.0, 0.0]])              # MOON_ME [km]
b_external = np.array([[2.0, -1.0, 4.0]])                  # 一様外部場 [nT]
b_local = b_external + grid.field_at(r0)
v0 = electron_velocity_me([200.0], [150.0], [0.0], b_local)   # 200 eV、ピッチ角150°
settings = TestParticleSettings.for_field(float(np.linalg.norm(b_local)), gyrations=500.0)
result = trace_test_particles(grid, r0, v0, b_external, settings=settings)
result.status                       # "surface_hit" / "returned" / "escaped" / "max_steps" ...
result.arrays["spacecraft_shell_pitch_deg"]   # 出発半径へ戻った点のピッチ角
```

`for_field`はジャイロ周期の$1/120$を時間刻みにし、`gyrations`で歩数を決めます。
`stop_altitude_km`（既定6.1 km、殻格子の下端）に達すると`surface_hit`、`escape_altitude_km`を超えると`escaped`、
出発点の周り`return_radius_km`へ戻ると`returned`です。`spacecraft_shell_*`は出発半径を上向きに初めて横切った状態で、
衛星で見る反射電子と比べる量です。電場は含めず、殻格子の外（`bounds="nan"`）では`invalid_field`になります。

## 閉じた磁力線の島

```python
from sopran.experimental.moon.closure import classify_closed_islands

islands = classify_closed_islands(
    lon_deg, lat_deg, closed_like, path_max_nT, footpoint_separation_deg,
    min_path_max_nT=10.0, min_footpoint_separation_deg=5.0, min_cells=3,
)
islands.island_id, islands.island_count
```

完全な経度×緯度格子の各セルについて、`closed_like`が真で経路最大磁場と足点の間隔が閾値以上のセルを
4近傍・経度の周期で連結し、`min_cells`未満の成分を落とします。閾値の物理的な意味は呼び出し側で決めます。

## 磁場残差と静穏基準

```python
from sopran.experimental.kaguya.field_residual import (
    quiet_field_baseline, residual_decomposition, svm3d_residual,
)

residual = svm3d_residual(grid, position_me_km, observed_nT)   # 観測 − SVM3D
residual.parallel_nT, residual.perpendicular_abs_nT, residual.fractional_abs
baseline = quiet_field_baseline(lon_deg, lat_deg, b_sc_nT, quiet_mask, grid_deg=10.0, min_events=5)
compression = b_sc_nT / baseline.value          # B_sc / B_quiet
```

`residual_decomposition(observed, base, direction)`は残差ベクトルと、`direction`（既定は観測方向）に沿う成分・直交成分の大きさ、
$|\text{残差}|/|\text{base}|$を返します。`quiet_field_baseline`は`quiet_mask`の行だけで`grid_deg`セルごとの中央値を作り、
`min_events`に満たないセルは全体の中央値、それも無ければ`fallback`で埋め、どれを使ったかを`source`に残します。
lunarsatの解析では、太陽風動圧とIMFが中央値以下で尾部内でない行を`quiet`とし、
太陽風に対するER磁場の応答の大部分が$B_\mathrm{sc}/B_\mathrm{quiet}$で説明されました。

## 環境応答の回帰

```python
from sopran.experimental.statistics.ridge import (
    external_gain, feature_drop_diagnostics, grouped_cv_predictions, model_ladder,
)

ladder = model_ladder(
    frame, targets=["log_b_eff"],
    specs=[("local", ["log_b_sc"]), ("physical", ["log_b_sc", "log_pressure", "imf_abs"])],
    alpha=1.0, folds=5, seed=0, group_column="track_id",
)
ladder.metrics          # train_r2 / cv_r2 / n_rows
drops = feature_drop_diagnostics(
    frame, target="log_b_eff",
    feature_groups={"local": ["log_b_sc"], "upstream": ["log_pressure", "imf_abs"]},
    alpha=1.0, group_column="track_id",
)
gain = external_gain(base_x, physical_x, log_target, alpha=1.0, eps=0.25)
gain.external_gain, gain.corrected
```

特徴量は学習行で標準化し、切片に罰則を掛けません。`group_column`を指定すると同じ値の行を同じfoldに入れるため、
`cv_r2`は軌道をまたぐ予測の指標になります。`external_gain`は基本モデルと物理モデルの対数予測の差$\exp(\Delta)$をゲインとし、
`corrected = max(exp(y − Δ) − eps, 0)`を返します。回帰の指標は相関の記述であり、因果の検定ではありません。

## 制約

- テスト粒子は磁場のみ・一様外部場・SVM3D殻格子の補間精度の範囲で有効です。殻格子の高度範囲（既定6.1〜200 km）の外は追えません。
- 残差の物理的な読み（外部場、誘導場、モデル誤差）は分解の結果からは決まりません。
- 回帰の出力はStoreに書きません。保存するときは設定と入力の来歴を一緒に残してください。
