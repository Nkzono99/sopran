# 座標変換

ベクトル量（磁場、位置）は、スキーマに座標系を持っています。たとえばLMAGの`magnetic_field`は`MOON_ME`、
`magnetic_field_gse`は`GSE`です。別の座標系への変換は`transform()`で明示し、
SPICEカーネルなど変換に使った条件を`FrameContext`にまとめて来歴に残します。

## 変換する

```python
# 変換元と変換先の両方の座標系を定義するカーネル（ここではメタカーネル）を渡す
frames = spn.FrameContext(spice_kernels=("kernels/kaguya.tm",))

b = spn.kaguya.lmag.magnetic_field.load(time)        # MOON_ME
b_sc = b.transform("SELENE_M_SPACECRAFT", context=frames)
b_sc.metadata["operations"]                           # 変換元・変換先・バックエンド・カーネルの記録
```

時刻ごとの3成分ベクトルの配列を直接変換することもできます。

```python
frames.transform_vectors(
    [[1.0, 0.0, 0.0]],
    times=["2008-01-01T00:00:00"],
    source_frame="MOON_ME",
    target_frame="SELENE_M_SPACECRAFT",
)
```

`View`から作る場合は`view.frame_context()`で、Viewに設定したSPICEカーネル・時刻系・バックエンドを使います。

## 変換の規則

- 同じ座標系への変換は恒等変換として記録だけを残します。
- 異なる座標系への変換は、現在`spiceypy`（SPICE）で行います。時刻カーネルと、変換元・変換先を定義する
  フレームカーネル・天体暦を`spice_kernels`に渡してください。足りない場合は推定で補わず`FrameTransformError`で止まります。
  `SSE`や`GSE`はNAIFの汎用カーネルに含まれないため、それらを定義するフレームカーネルが別に必要です。
- `GSE`・`GSM`・`SM`の間の変換は`spacepy`で行う予定で、まだ実装していません。
  `frames.plan("GSE", "GSM")`の`status`は`"planned"`になり、変換を試みると`FrameTransformError`になります。

`frames.plan(source, target)`は、実行せずに選ばれるバックエンドと状態（`applied`、`implemented`、`planned`）を返します。
`frames.metadata()`は、環境にインストールされているバックエンド（`available_backends`）と、
SOPRANが実装済みとして扱うもの（`implemented_backends`）を分けて返します。

バックエンドは通常指定しません。研究上固定したい場合だけ、`FrameContext(default_backend="spiceypy")`や
`project.view(..., backend={"frames": "spiceypy"})`で指定します。

## SPICEカーネルの入手

KAGUYAの`orbit.sza`は、カーネルを渡さず`download`が`never`でない場合、NAIFの汎用カーネル
（うるう秒、月の座標系、DE421）を自動で取得してStoreの`raw/spice/kernels/`に置きます。
それ以外の変換では、利用者がカーネルを用意して`FrameContext`へ渡します。
KAGUYAの姿勢を含むカーネルは`sopran.missions.kaguya.selene_spice_kernels(store, time)`で取得できます。

## 主な座標系

| 名前 | 意味 |
|---|---|
| `MOON_ME` | 月固定のMean Earth/Polar Axis系 |
| `SSE` | 月中心のSelenocentric Solar Ecliptic系 |
| `GSE` | 地球中心のGeocentric Solar Ecliptic系 |
| `GSM` | 地球中心のGeocentric Solar Magnetospheric系 |
| `SELENE_M_SPACECRAFT` | KAGUYA（SELENE）の機体座標系。PACEの視線方向の基準 |
