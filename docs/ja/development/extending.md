# データ源を追加する

新しいミッションや天体のデータを`spn.<name>`・`view.<name>`・`spn.load("<name>...")`から使えるようにする手順です。
最も小さな実装例は`src/sopran/missions/omni/`（OMNI）なので、並べて読むと分かりやすくなります。

## 1. 登録する

データ源はそれぞれのパッケージの`__init__.py`で登録します。`core`はミッションをimportしないため、登録はミッション側で行います。

```python
# src/sopran/missions/<name>/__init__.py
from sopran.core.sources import register_source

register_source("<name>", "sopran.missions.<name>.mission:<Mission>.from_view")
```

第2引数は`"モジュール:属性のパス"`で、最初に使われたときにimportします。
登録されたファクトリーは`View`を受け取り、その期間・ダウンロード方針・Storeに結び付いた実体を返します。

```python
class Mission:
    def __init__(self, *, store: Store | None = None, download: DownloadMode | None = None,
                 view: View | None = None) -> None:
        self.store = store or Store()
        self.download = resolve_download_mode(download)   # 方針の解決は一か所に任せる
        self.view = view

    @classmethod
    def from_view(cls, view: View) -> "Mission":
        return cls(store=view.project.store, download=view.context.download, view=view)
```

`src/sopran/__init__.py`でこのパッケージをimportすると登録が済み、`spn.<name>`・`view.<name>`・`case.<name>`・`spn.load("<name>.…")`がすべて同じ実体を使うようになります。

## 2. スキーマを書く

変数ごとに`VariableSchema`を書き、機器ごとに`InstrumentSchema`にまとめます。単位・次元・座標系はここが正本です。

```python
DENSITY = VariableSchema(name="density", dims=("time",), units="cm^-3", description="Proton density.")
SCHEMA = InstrumentSchema(mission="<name>", instrument="<instrument>", variables=(DENSITY,))
```

何桁にもまたがる量（フラックスやパワースペクトル密度など）には`log_scale=True`、対数軸で描く座標には`log_dims=("energy",)`を付けます。
配列とエンドポイントの作図は、この指定から既定の対数表示を決めます。

スキーマをリファレンスに載せるには、`sopran.schema_docs.builtin_schemas()`に加えてから
`python -m sopran.schema_docs`でページを作り直します。

## 3. エンドポイントを作る

エンドポイントは、属性として取り出しただけではファイルを読まないようにします。少なくとも次を用意します。

| メソッド | 返り値 |
|---|---|
| `load(time=None, *, download=None, ...)` | `SopranArray`。`time`を省いたら`view.time`を使い、どちらも無ければ例を添えた例外にする |
| `plot(time=None, **kwargs)` | `load(...).plot(...)` |
| `line()`、`lines()`、`spectrogram()`など | PlotStack用のパネル |
| `info()`、`schema()`、`guide()`、`example()` | 説明と定義 |
| `plan(time)` | 読み込む元ファイルやデータセットID |

元ファイルは`store.raw_path("<name>", "<provider>", ...)`の下に配布元の構成で置き、取得したら`store.register_raw_file(...)`で
URLとチェックサムを記録します。取得は一時ファイルに書いてから置き換え、失敗しても以前のファイルを残します。
派生量をキャッシュするときは、設定と入力の内容から`variant_id`を作り、`managed=True`で登録します。

## 4. Pipelineに対応する（必要な場合）

`PipelineBackend`を継承し、対応する操作だけを上書きします。エンドポイントの`pipeline(time)`は、このバックエンドを付けた`Pipeline`を返します。

```python
from sopran.core.pipeline import Pipeline, PipelineBackend

class MyBackend(PipelineBackend):
    def scan_pipeline(self, pipeline: Pipeline):
        ...   # polars.LazyFrame を返す。stream(partition="day") はここから自動で分割される

    def run_pipeline(self, pipeline: Pipeline, *, mode, run_id, resume, only_failed, on_error, download):
        ...   # PipelineResult を返す
```

上書きしない操作は`PipelineError`になります。PACEの実装は`src/sopran/missions/kaguya/pipeline.py`にあります。

## 5. 説明とテストを付ける

- `guide()`が返す説明は、パッケージの中の`README.md`（英語）と`README.ja.md`に書き、公開ドキュメントのURLを`GuidePage(url=...)`に渡します。
- 公開ドキュメントには[データ](../data/index.md)の下にページを作り、[ドキュメントの書き方](documentation.md)のひな形に沿って書きます。
- 任意の依存は使う経路で遅延importし、extraに加えます。`tests/test_project_metadata.py`がextraと実際のimportの一致を確かめます。
- 合成データかfixtureで、単位・欠測とゼロの区別・期間の半開区間・キャッシュのキーをテストします。
