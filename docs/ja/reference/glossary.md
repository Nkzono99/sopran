# 用語集

このドキュメントで使う用語の意味です。

| 用語 | 意味 |
|---|---|
| エンドポイント | `spn.kaguya.esa1.energy_flux`のように、ミッション・機器・物理量をたどった末端のオブジェクト。属性として取り出しただけではファイルを読まず、`load()`や`plot()`で処理が始まる |
| `SopranArray` | `load()`が返す配列。xarrayの`DataArray`に、スキーマ・期間・出典ファイル・処理履歴を付けたもの |
| スキーマ | 変数の名前・次元・単位・データ型・座標系・別名の定義（`VariableSchema`、`InstrumentSchema`）。コードに書き、ドキュメントと検証はここから作る |
| 別名（alias） | 同じ変数の短い名前。`energy_flux`に対する`eflux`、`magnetic_field`に対する`b`など |
| 期間（`TimeRange`） | 開始を含み終了を含まない半開区間`[start, stop)`。タイムゾーンの無い時刻はUTC |
| `View` | 期間・領域と処理条件を束ねた、変更不可の解析条件 |
| `Project` | 解析テーマごとの作業ディレクトリ。`sopran.toml`と成果物を置く |
| `Case` | `sopran.toml`に名前を付けて保存した解析条件 |
| Store | 元ファイル・中間データ・採用した解析結果を層に分けて置く、1つのルートディレクトリ |
| 層（layer） | Storeの中の区分。`raw`、`normalized`、`features`、`models`、`databases`、`cache`、`registry` |
| データセット | Storeの中の1単位のデータ。マニフェスト・スキーマ・カタログ・シャードを持ち、`kaguya.esa1.counts`のようなIDで呼ぶ |
| シャード | データセットを分けて保存したParquetファイル。多くは1日1シャード |
| 付属JSON | 元ファイルやシャードの隣に置く`*.sopran.json`。チェックサムなどを記録し、カタログの正本になる |
| マニフェスト | データセットの`dataset.json`。来歴・設定・入力を記録する |
| カタログ | `catalog.parquet`。シャードの期間・行数・チェックサム・状態の索引 |
| variant | 同じデータセットIDの下で、計算条件ごとに分けた保存単位。IDは設定と入力の内容から決まる |
| managed | SOPRANが自動で作り再利用するデータセットの印。同期の既定の対象 |
| キャッシュ | 計算結果をStoreに保存して再利用すること。`cache="use"`、`"refresh"`、`"never"`で制御する |
| ダウンロード方針 | 元ファイルが無いときの取得の仕方。`missing`、`never`、`always` |
| 来歴（provenance） | データや図を作った入力・設定・処理の記録。`metadata`、マニフェスト、図のJSONに残す |
| 処理履歴（operations） | `rebin`や`transform`などの操作と引数の記録。`metadata["operations"]` |
| クイックルック | 図と作成条件のJSONをまとめて保存したもの。`quicklook()`で作る |
| `PlotStack` | 時間軸を共有して複数のパネルを縦に並べる図。SPEDASの`tplot`に相当する |
| 元の観測ビン | 校正や再ビン化の前の、機器が記録したままの時間・エネルギー・視線のビン |
| `look` | PACEの検出器の視線方向の番号。方向そのものではなく、校正テーブルで方向に戻す |
| ピッチ角 | 粒子の速度と磁場のなす角（0〜180度） |
| `FrameContext` | 座標変換に使うSPICEカーネル・時刻系・バックエンドをまとめたもの |
| SPICEカーネル | NASA NAIFのSPICEで使う、時刻・座標系・天体暦・姿勢のデータファイル |
| Rust拡張 | 重い計算を担う同梱のネイティブモジュール`sopran._native`。利用者は意識せずに使う |
| 試作API | `sopran.experimental`の研究用API。互換性を保証しない |
| Pipeline | 取得・デコード・保存の段を並べて、長い期間をまとめて処理する仕組み |
