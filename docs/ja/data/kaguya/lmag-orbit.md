# LMAGと軌道

LMAG（Lunar MAGnetometer）は探査機上の磁場を測る磁力計です。公開ファイル（`MAG_TS*.dat`）には磁場と探査機の位置が
入っているため、SOPRANは同じファイルから軌道幾何（高度、直下点、太陽天頂角）と、磁力線が月面に届くかどうかも計算します。
軌道幾何の時刻はLMAGの観測時刻そのものです。

## 変数

| 入口 | 次元 | 単位 | 座標系 | 内容 |
|---|---|---|---|---|
| `kg.lmag.magnetic_field` | `time, component` | nT | `MOON_ME` | 磁場ベクトル。別名`b` |
| `kg.lmag.magnetic_field_gse` | `time, component` | nT | `GSE` | ファイルに入っているGSE系の磁場。別名`bgse` |
| `kg.lmag.magnetic_field_magnitude` | `time` | nT | | 磁場の強さ$\lvert B\rvert$。別名`bmag` |
| `kg.lmag.magnetic_connection` | `time` | | `MOON_ME` | 磁力線と月面の接続（下記） |
| `kg.orbit.position` | `time, component` | km | `MOON_ME` | 探査機の位置 |
| `kg.orbit.position_gse` | `time, component` | km | `GSE` | 探査機の位置 |
| `kg.orbit.radial_distance` | `time` | km | | 月中心からの距離 |
| `kg.orbit.altitude` | `time` | km | | 半径1737.4 kmの球からの高度 |
| `kg.orbit.subpoint` | `time, component` | deg | `MOON_ME` | 球面上の直下点の経度・緯度 |
| `kg.orbit.sza` | `time` | deg | | 直下点の太陽天頂角 |

```python
kg = spn.kaguya
time = spn.day("2008-01-01")

b = kg.lmag.magnetic_field.load(time)
altitude = kg.orbit.altitude.load(time)
spn.stack(kg.lmag.bmag.load(time).line(), altitude.line()).plot()
```

軌道幾何と磁力線の接続は計算結果を既定でStoreに保存し（`cache="use"`）、2回目からは読み直すだけになります。
元ファイルが欠けて`missing="empty"`や`"warn"`で読んだ結果は保存しません。

## 太陽天頂角

`kg.orbit.sza`は、SPICEで求めた太陽方向から直下点の太陽天頂角を計算します。
カーネルを渡さず、ダウンロード方針が`never`でなければ、NAIFの汎用カーネルを自動で取得します（[座標変換](../../guide/frames.md#spiceカーネルの入手)）。
太陽方向を自分で与えるときは`sun_vector=`を使います。

```python
sza = kg.orbit.sza.load(time)
sza = kg.orbit.sza.load(time, sun_vector=[1.0, 0.0, 0.0], sun_frame="MOON_ME")
```

軌道の位置は`frame=`と`context=`（`FrameContext`）を渡すと、読み込み時に別の座標系へ変換できます。

## 磁力線と月面の接続

`magnetic_connection`は、探査機の位置から局所の磁場方向へ直線を延ばし、半径`radius_km`（既定1737.4 km）の球と交わるかを調べます。
磁場の向き（plus）と逆向き（minus）の両方を調べます（`direction="both"`）。

```python
conn = kg.lmag.magnetic_connection.load(time)
conn.plot(kind="footpoint")      # footpoint, altitude, incidence, distance
conn.to_xarray()
```

| 変数 | 内容 |
|---|---|
| `connected_any`、`connected_plus`、`connected_minus` | どちらか・各向きで球と交わるか |
| `footpoint_plus_lon`、`footpoint_plus_lat`など | 交点の経度・緯度（deg） |
| `distance_plus_km`、`distance_minus_km` | 交点までの距離 |
| `incidence_angle_plus_deg`、`incidence_angle_minus_deg` | 磁力線と月面の法線のなす鋭角 |
| `altitude_km` | 探査機の高度 |

これは直線で近似した幾何で、月面の磁気異常による磁力線の曲がりは含みません。
表面磁場モデルを使った追跡は試作API（`sopran.experimental.moon.svm3d`）にあります。

## 別の機器の時刻に合わせる

PACEなど別の機器の時刻に合わせるときは`resample_like`を使います。

```python
esa1 = kg.esa1.counts.load(time, missing="warn")
conn_on_esa1 = conn.resample_like(esa1, method="nearest", tolerance="2s")
altitude_on_esa1 = altitude.resample_like(esa1, method="linear", tolerance="10s")
```

方法の一覧は[時刻をそろえる](../../guide/alignment.md)にあります。

## 制約

- SPICEで求めた太陽方向・座標変換と、SPEDASの幾何計算との照合テストはまだありません。
- 高度と直下点は球の月で計算しており、地形（DEM）は使いません。
