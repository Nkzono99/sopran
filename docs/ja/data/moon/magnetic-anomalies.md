# 磁気異常カタログ

`spn.moon.magnetic_anomalies()`は、論文の位置表から作った月の磁気異常の一覧を`pandas.DataFrame`で返します。
表はパッケージに同梱しているため、ネットワーク接続やSVMのファイルは要りません。

```python
import sopran as spn

sites = spn.moon.magnetic_anomalies()       # Blewett (2011) の訂正版、15件
sites[["name", "lon_deg", "lat_deg", "peak_field_30km_nt", "swirl"]]

# 名前・feature_id の部分一致。Gamma と γ、ハイフン、下線の表記揺れに対応する
reiner = spn.moon.magnetic_anomalies("all", name="Reiner Gamma")

# (東経, 緯度) の近くを探す。西経57.5度は -57.5 でも 302.5 でもよい
nearby = spn.moon.magnetic_anomalies("all", near=(-57.5, 7.5), radius_deg=5)

# 孤立した異常の解析中心と、論文で使った観測領域の半径
isolated = spn.moon.magnetic_anomalies("oliveira2017")
```

## 収録している表

| `catalog` | 内容 | 出典 |
|---|---|---|
| `blewett2011`（既定） | 15件。おおよその位置、高度30 kmでの磁場のピーク、地形の区分、当時のスワール分類 | [Blewett et al. (2011)、訂正版のTable 1](https://doi.org/10.1029/2011JE003852) |
| `oliveira2017` | 15件。孤立した異常の解析中心、観測半径$r_o$、双極子を置く半径$r_d$ | [Oliveira & Wieczorek (2017)、Table 1](https://doi.org/10.1002/2016JE005199) |
| `all` | 上の2表の計30行、23個の`feature_id`。同じ地域の異なる文献値を別の行で保つ | 上の2表 |

これは文献が選んだ地域の一覧で、月面のすべての磁気異常を網羅したものではありません。
`name`は文献の表記のまま残し、Reiner-γとReiner Gamma、SirsalisとRima Sirsalisは`feature_id`で対応付けます。
座標の異なる行を平均・統合しません。Blewettの元の論文には座標の誤りがあるため、訂正版を採用しています。

## 列

| 列 | 意味 |
|---|---|
| `lon_deg`、`lat_deg` | 東経0〜360度、北緯を正とする文献の月固定座標。MOON_MEとMOON_PAの間の精密な変換はしない |
| `position_kind` | `approximate_anomaly_location`はおおよその位置、`analysis_center`は解析領域の中心 |
| `peak_field_30km_nt` | 高度30 kmでの地域内の推定ピーク$\lvert B\rvert$（nT）。月面での値や掲載座標での点の値とは異なる |
| `setting`、`swirl` | Blewettの表の地形・スワール分類。`not_recognized`は2011年時点で未確認という意味 |
| `observation_radius_deg`、`dipole_radius_deg` | Oliveiraの論文の解析領域の角半径。磁気異常の物理的な境界や大きさではない |
| `reference_doi`、`note` | 行ごとの出典と注記。Marginisは月探査機Lunar Prospectorの磁力計の観測が乏しい |
| `distance_deg`、`distance_km` | `near`を指定したときだけ。掲載座標までの大円距離。kmへの換算には月半径1737.4 kmを使う |

文献に値が無い所は欠損値です。`near`を指定すると距離の近い順に並べ、`radius_deg`で掲載点までの角距離が近いものに絞ります。
領域との交差判定には使えません。`radius_deg`は`near`と一緒に、0〜180度で指定します。
結果が空でも、列と`DataFrame.attrs`のメタデータは保たれます。

## SVMと組み合わせる

位置の表とSVMを合わせて使う場合は、SVMの`sample()`に座標を渡します。追加した列はSVMの点の値で、
文献の地域内ピークとは別の量です。

```python
svm = spn.moon.svm.load(path="/path/to/LunarSVM_000_02_v02.dat")
sites["svm_surface_point_nt"] = svm.sample(lat=sites.lat_deg, lon=sites.lon_deg)
```
