# 設計ドラフト

このディレクトリには、SOPRAN の内部設計や v0.1 以降の方向性を整理するための
draft 文書を置きます。利用者向けに安定させた説明は Concepts、How-to、Reference の
各ページを優先します。

| 文書 | 内容 |
| --- | --- |
| [API and Data Store Spec](spec.md) | user-facing API、中核データモデル、v0.1 contract |
| [Store Spec](store.md) | raw / normalized / features / databases、manifest、catalog |
| [Pipeline Spec](pipeline.md) | batch processing、lazy execution、Rust backend stages |
| [Surface Spec](surface.md) | Moon、DEM、SVM、SZA、shadow、illumination、map projection |
| [Plotting Spec](plotting.md) | PlotStack、quicklook、plotting backend policy |
