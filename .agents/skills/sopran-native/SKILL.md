---
name: sopran-native
description: SOPRANのPyO3/Rust backendの移植、高速化、数値等価性検証、native拡張のbuild・wheel問題で使う。Rustに触れない通常のPython API変更には使わない。
---

# Native backendの変更と検証

## 境界と参照先

パスはリポジトリルートからの相対パスです。
build設定は`pyproject.toml`の`tool.maturin`と`crates/sopran-native/Cargo.toml`、
Pythonの拡張名は`sopran._native`。配布行列は`.github/workflows/publish.yml`を確認する。
ERの設計経緯は`docs/missions/kaguya/electron-reflectometry-rust-backend.md`にあるが、
過去の計測値・未移植経路の記述は現行コードと照合する。

- 公開API、機器の補正仕様、モデル選択方針と、重い計算kernelの責務を分ける。
  数式が同じでも単位、配列順序、mask、境界条件が異なれば同等ではない。
- レコードやbinごとのFFIを増やさず、配列・problem・batch単位で渡す。
  不変な応答や補間情報は再利用し、optimizer反復内のPython callback、コピー、
  小配列の割当を測定対象に含める。
- Python worker数とRayon/BLAS等の内部thread数を一緒に確認する。
  並列数の変更とkernelの高速化は別々に測り、過剰並列を避ける。

## 同等性と速度

- 同一入力・設定・seedでbaselineを測る。初回build/import、I/O、準備、
  objective/gradient、最適化全体を区別し、中央値と遅いケースも報告する。
- 既知の合成例から少数の実データへ進め、目的関数、パラメータ、採択モデル、
  失敗理由を比較する。許容差は量のscaleと推定の感度から決める。
- solverやwarm-startで探索が変わる場合、同じ解への収束と単なる高速終了を区別する。
  勾配変更は有限差分等と照合する。fallbackが黙ってPythonへ戻していないか確認する。
- 新しいbridge、CLI fallback、依存を追加する前に現在のPyO3/NumPy境界で改善できるか測る。
  wheelのABI方針や依存versionを性能改善と無関係に変更しない。

## buildとテスト

先に、このソースツリーやnative拡張を使用中のジョブがないか確認する。
`maturin develop`はソースツリー内の拡張を更新し得るため、venvやCargo targetだけを
分けても隔離にならない。稼働中なら、変更内容を反映した別のソースコピーと別venvで
検証するか、非editableのwheelを別環境へインストールしてソース外のcwdで検証する。
共有環境を更新する必要がある場合は、対象ジョブの停止を確認してから行う。

使用するvenvを有効化したリポジトリルートでの例:

```powershell
cargo test -p sopran-native
cargo fmt --all --check
python -m maturin develop --release
python -c "import sopran._native as native; print(native.__file__)"
python -m pytest -q tests/test_kaguya_pace.py
```

テストは変更したkernelに合わせて選ぶ。ERでは`tests/test_electron_reflection*.py`や
`tests/test_incident*.py`等の該当ファイルを明示する。
新しいrelease buildを本当にロードしているか、新しいPythonプロセスで確認する。
Windowsで使用中の`.pyd`を差し替えるために無関係なPythonを停止しない。

配布を変更した場合はwheelをbuildし、source treeの影響を受けない別環境・別cwdで
インストールとimportを検証する。ローカル1環境の成功を全OS/全Pythonの成功と報告しない。
