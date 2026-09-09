---
name: sopran-er-batch
description: SOPRANの電子反射法（ER）のfit、実データ評価、可視化、長時間バッチの実行・再開・進捗調査で使う。一般的なreader追加や無関係なドキュメント修正には使わない。
---

# ER解析と長時間バッチ

## 調査する場所

パスはリポジトリルートからの相対パスです。必要なものだけ読む。

- 数式・モデル: `docs/missions/kaguya/electron-reflectometry-algorithm.md`、
  `src/sopran/analysis/electron_reflection/`。
- 機器データからの構成と公開API: `src/sopran/missions/kaguya/er.py`、`er_timeseries.py`。
- 評価・制約: `docs/missions/kaguya/electron-reflectometry-validation.md`、
  `docs/missions/kaguya/electron-reflectometry-method-survey.md`。
- ローカル実験: `working/kaguya-er-fit-review/`。指定されたrunのREADME、
  binding、summary、input audit、ログと、その生成scriptを対応付ける。
  最新という名前や画像の見た目だけで実行中・採択済みと判断しない。

## モデルを変える前に

- 実際に使ったmodel family、bounds、beam設定、BIC gate、重み・応答・補正を
  保存された設定と現行コードで特定する。過去の説明や図のタイトルだけに依存しない。
- 生カウントと補正済み量、S1/S2の独立観測と合成表示、incident/affected/referenceの
  定義、磁場に対するpitch角の向きを確認する。表示用foldとfit入力を混同しない。
- 時間積分と間引きを区別する。窓内のnative recordsを集める処理と、
  評価時刻の選択を別々に数える。欠測・校正mode・低countを一律NaNにする変更は避け、
  現行のmode仕様・exposure・尤度・品質判定との整合を検証する。
- `B_eff`、`B_sc`、`R_m`、`Delta_U`は実装の定義・符号で説明する。
  `R_m < 1`等の診断解を、地殻磁場の直接測定値と同一視しない。

## 小規模検証から展開する

- baselineを残し、要求に応じて明瞭な境界、beam、低count、欠測、
  mirror/electrostaticの競合を含む少数ケースで数値と図を比較する。
- 全期間へ拡張する前に適切な小単位でwall timeと失敗率を測る。
  総観測数、候補窓数、fit実行数、採択数、除外理由を別々に集計する。
- 再開前にプロセスと出力先、runnerが照合する設定・入力・コードhashを確認する。
  別設定は新しいrunへ出力する。warm-startは時系列の切れ目や条件変更での扱いと、
  cold-startとの比較で解の品質が保たれるか確認する。
- 進捗は日別状態、成功/失敗数、処理時間、更新時刻とログで報告する。
  未取得ファイルと公開元自体の欠損、未処理とfit失敗を区別する。

## 図と報告

- 観測と再構成は同じエネルギー/pitch範囲・色範囲で比較し、比の対数は`log10`と明記する。
- NaNとゼロを分け、採択境界・診断候補・観測由来edgeはlegendで区別する。
  beamを用いる比較ではbeam成分と除去後の分布も示す。
- fitの成否、境界パラメータの識別可能性、磁場推定としての利用可否を分けてラベル付けする。
  `no_edge`や最適化成功を磁場測定の成功と読み替えない。
- 図はrun出力に保存し、PNGを開いて単位・凡例・欠測表示を確認する。
  代表図だけか全対象を描いたか、総数・範囲・未完了分を明記する。
