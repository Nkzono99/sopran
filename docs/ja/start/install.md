# インストール

SOPRANは現在PyPIで配布しておらず、リポジトリを取得してインストールします。
Python 3.11以上が必要です。

```bash
git clone https://github.com/Nkzono99/sopran.git
cd sopran
python -m pip install -e ".[full]"
```

`[full]`は、KAGUYA・ARTEMIS・月面マップ・可視化に必要な依存をまとめて入れます。
使うデータが決まっている場合は、下の表から必要なextraだけを選べます。

## Rust拡張のビルドに必要なもの

ソースからのインストールでは、PACEのデコードやピッチ角集計を担うRust拡張
`sopran._native`を同時にビルドします。Rustのツールチェーンと、WindowsではMSVCのビルドツールが必要です。
事前の確認には`sopran-env-check`を使います（インストール後にも実行できます）。

```powershell
.\.venv\Scripts\sopran-env-check.exe --native
```

Windowsでは、管理者権限のPowerShellでChocolateyを使うと次の手順でそろいます。

```powershell
choco install -y python314
choco install -y rust visualstudio2022buildtools visualstudio2022-workload-vctools
refreshenv

python3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[full]"
```

## extraの選び方

`pip install -e .`だけでは`numpy`と`pandas`しか入らず、`import sopran`と
トップレベルの入口だけが動きます。各extraには、その経路でSOPRANが実際にimportするパッケージだけを入れています。

| extra | 使う場面 | 入るパッケージ |
|---|---|---|
| `kaguya` | PACE・LMAG・LRSの読み込み、SPICEによる幾何計算 | `cdflib`, `polars`, `pyarrow`, `scipy`, `spiceypy`, `xarray` |
| `artemis` | Storeに置いたARTEMISデータの読み込み | `polars`, `pyarrow`, `xarray` |
| `moon` | GeoTIFFの月面地図、SPICEによる太陽方向 | `rasterio`, `spiceypy` |
| `viz` | 図の作成、PlotStackの対話表示 | `matplotlib`, `panel` |
| `analysis`, `experimental` | 補間、試作モデル | `scipy` |
| `full` | 上記すべて | |

OMNIの読み込みには`xarray`、作図には`matplotlib`が必要です。`[kaguya,viz]`を入れていれば足ります。

```powershell
python -m pip install -e ".[kaguya,viz]"
```

## 動作を確かめる

```python
import sopran as spn

spn.kaguya.info()     # KAGUYAで使える機器の一覧
```

一覧が表示されれば準備完了です。データの保存先を決めて、[最初の図を描く](quickstart.md)へ進んでください。
開発用の依存（`[dev]`）やテストの実行方法は[開発環境と検証](../development/setup.md)にまとめています。
