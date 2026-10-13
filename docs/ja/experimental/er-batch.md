# ER全期間バッチ

`sopran.experimental.kaguya.er_batch`は、保存済みのペア分布に対して、finite-binの当てはめと$R_m$のプロファイルを全期間で行うCLIです。
同じコマンドが手元のPCでも、京都大学のスーパーコンピューターのSlurm配列ジョブでも動きます。
入力と出力はどちらもStoreのデータセットで、日別のParquetに分かれているため`rsync`でそのまま運べます。

| データセット | 層 | variant | 中身 |
|---|---|---|---|
| `experimental.kaguya.er.paired_distributions` | `features` | 入力のビルド名 | 16秒窓ごとの折り返したカウント・露出・窓の記録。1日1シャード |
| `experimental.kaguya.er.finite_bin_fits` | `models` | 実行名（run） | 窓ごとの当てはめ・プロファイル・候補。1日1シャード |

コマンドは`python -m sopran.experimental.kaguya.er_batch [--data-root ROOT] <command>`の形で使います。
`--data-root`を省くと、`SOPRAN_DATA_ROOT`（またはSOPRANの設定）のStoreを使います。
依存は`experimental`と`kaguya`のextraです。

## 流れ

```text
export-catalog → verify-inputs → prepare → run（並列・再開可） → status → finalize → compare
```

| コマンド | 内容 |
|---|---|
| `export-catalog --catalog PATH --input-variant V [--workers N]` | SQLiteのカタログを日別シャードへ変換する。既にある日は飛ばす |
| `verify-inputs --input-variant V` | 転送した後に入力シャードのチェックサムを確かめる |
| `prepare --input-variant V --run-variant R [--groups G] [--fit-setting name=JSON]` | 設定・入力・コードと環境のハッシュを`run.json`に固定する |
| `run --run-variant R [--group i \| --days D...] [--workers N]` | 指定した日を当てはめる。未完了の日だけを処理する |
| `status --run-variant R` | 完了した日数とハートビートを表示する |
| `finalize --run-variant R` | 完了したシャードのチェックサムを計算し直し、Storeのカタログに登録する |
| `compare --run-variant R --reference FILE...` | 別の実行の日別Parquetと、同じ窓の目的関数・$B_\mathrm{eff}$・候補を比べる |

## 入力を用意する

入力は、窓ごとのペア分布を保存したSQLiteのカタログを変換するか、下のSOPRANの部品で元データから作ります。

### SQLiteのカタログから変換する

カタログは`windows`という表を1つ持ちます。

| 列 | 型 | 内容 |
|---|---|---|
| `sample_id` | TEXT | 16秒窓のID |
| `day` | TEXT | UTCの日（`YYYY-MM-DD`） |
| `record` | TEXT | 窓の記録（JSON）。`time`、`b_sc_nT`、`affected_side`、`field_connection_status`、`field_radial_abs_cosine_min`、`magnetic_direction_max_deviation_deg`、`reason`を読む |
| `maps` | BLOB | `.npz`。分布の無い窓はNULL |

`maps`には`FLOAT_ARRAYS`と`BOOL_ARRAYS`の配列を入れます。折り返した配列は`energy × pitch_folded`、
`global_*`は`energy × pitch`の形です。

```bash
python -m sopran.experimental.kaguya.er_batch --data-root /path/to/sopran_data export-catalog \
  --catalog /path/to/catalog.sqlite --input-variant <build> --workers 3
```

変換では、窓ごとのnpzから、折り返したカウント・露出・`fit_valid`・`pair_observed`と、全ピッチ角のカウント・露出・
エネルギーとピッチ角の境界を、行優先で平坦にしたリスト列へ移します。各配列がfloat64・boolで損失なく表せることも確かめます。
以前の当てはめの派生量（`observed_log_ratio`、`fitted_log_ratio`、`beam_ratio`）は持ち込みません。
窓の記録（JSON）と、記録とnpzのsha256（`source_sha256`）も残し、`days.json`に全日（入力の無い日を含む）の窓数・分布数・チェックサムを書きます。

### SOPRANの部品で元データから作る

SQLiteのカタログを使わずに、元データから入力シャードを作る部品もあります。
既定値は2026年9月の全期間の実行（`halekas_mission_v1`）の規則と同じです。
日の並列化・再開・ログといった全期間の組み立ては、利用者のスクリプトで行います。

| 段階 | 部品 |
|---|---|
| 1日分の元の記録とLMAGの幾何 | `KaguyaErInstrument(mission).native_records(day)` |
| 16秒窓への集計と診断 | `er_windows.calendar_windows`、`window_record`、`window_input_diagnostic` |
| SVM3Dによる接続判定 | `moon.connection.trace_connection`、`classify_connection`（`ConnectionPolicy`） |
| ペア分布 | `er_windows.window_pitch_records` → `electron_reflection.maps.build_paired_map` |
| 書き出しと登録 | `er_batch.window_input_row` → `er_batch.write_input_days` |

```python
import numpy as np
import sopran as spn
from sopran.experimental.electron_reflection.maps import build_paired_map
from sopran.experimental.kaguya import er_batch
from sopran.experimental.kaguya.er import KaguyaErInstrument
from sopran.experimental.kaguya.er_windows import (
    calendar_windows, usable_record_indices, window_input_diagnostic,
    window_pitch_records, window_record,
)
from sopran.experimental.moon.connection import (
    classify_connection, trace_connection, unconnected_window,
)
from sopran.experimental.moon.svm3d import SVM3DShellGrid

day = spn.day("2008-02-10")
records = KaguyaErInstrument(spn.Kaguya(download="never")).native_records(day)
usable = np.unique(np.concatenate(
    [usable_record_indices(a, np.arange(records.times.size)) for a in records.arrays.values()]
))
traces = trace_connection(
    SVM3DShellGrid.load("svm3d_shell.npz"),
    records.position_km[usable], records.magnetic_field_nT[usable],
)
connection = classify_connection(
    traces, records.times[usable].astype("datetime64[s]").astype(int) // 16
)

rows = []
for window_id, indices in calendar_windows(records.times, day):
    record = window_record(window_id, indices, records)
    record.update(connection.get(window_id, unconnected_window()))
    record["joint_input_diagnostic"] = window_input_diagnostic(indices, records.arrays)
    usable_here = any(usable_record_indices(a, indices).size for a in records.arrays.values())
    reason = "no_records" if not indices.size else None if usable_here else "no_usable_geometry"
    if reason is None and not record["connection_eligible"]:
        reason = "connection_" + record["field_connection_status"]
    if reason:
        record["reason"] = reason
    maps = None if reason else build_paired_map(window_pitch_records(records, indices))
    rows.append(er_batch.window_input_row(record, maps))
er_batch.write_input_days(spn.Store(), "<build>", {"2008-02-10": rows})
```

各部品の規則は次のとおりです。

- `window_record`は、窓の中のLMAGサンプルから磁場方向の最大の偏差を、記録時刻の$B$と$r$の余弦から
  `field_radial_abs_cosine_min`を求めます。
- `build_paired_map`は、各記録をaffected側が低ピッチ角に来る向きにそろえ、20〜1500 eV・24エネルギー×16ピッチ角の格子へ
  ビンの重なりに応じて配り、カウントと露出を足してaffectedとreferenceに折り返します。
  `fit_valid`は、ペアの両側で露出が正でカウントがあり、エネルギー行あたり3セル以上ある範囲です。
- 接続判定は、一様な残差を加えたSVM3Dの磁場を0.5 km刻み・停止高度6.1 km・最大1000 kmで追跡し、
  内向きが殻に届いて逆向きが届かず、その向きが窓の中で変わらない窓を`model_connected`とします。

## 実行を固定して走らせる

`prepare`は、`FiniteBinFitSettings()`の既定に`--fit-setting`の上書きを加えた設定と、入力カタログのチェックサムを`run.json`に記録します。
当てはめのコードとRust拡張のsha256、Python・numpy・scipy・polarsの版も記録します。
`run`は起動時にこれらを今の環境と比べ、違えば止まります。設定を変えるときは別の実行名で`prepare`し直します。

`run`は日を1つずつ処理し、その日の窓をワーカープロセス（spawn）に分けます。
ワーカーは`OMP_NUM_THREADS`などを1に固定します。`--workers`の既定は割り当てられたCPU数（Linuxではaffinity）で、`0`はプロセス内で実行します。
256窓ごとに`work/<day>/part-*.parquet`へ保存し、日が終わると`shards/day=<day>.parquet`と`days/<day>.json`を書きます。
再実行すると完了した日を飛ばし、保存済みのpartは計算し直しません。
実行ディレクトリに`STOP`というファイルを作ると、すべての実行が今の窓の後に保存して終わります。
各実行は自分の日のファイルだけを書くので、配列ジョブを同時に走らせて構いません。
`--groups G`は日を分布の数で均等になるようG組に分け、`run --group i`がi番目の組を処理します。

1窓の処理は、カウント尤度の既定設定による当てはめです。幾何の条件（$B_\mathrm{sc} > 0$、磁場方向の偏差 ≤ 20度、
半径方向との角 < 80度、`model_connected`）を満たし、`field_flags`の立たない窓だけプロファイルを計算します。
プロファイルは$R_m$ ±1 dexの13点で、95%区間と`minimum_fit`を出します。列の意味は`finalize`が書く`schema.json`にあります。

## 京都大学のスーパーコンピューターで動かす

スクリプトは`scripts/hpc/kyoto/`にあります。京都大学のSlurmは独自に拡張されており、資源は
`--rsc p=PROCS:t=THREADS:c=CORES:m=MEMORY`で指定し、`-p`のキュー指定が必須です。プログラムは`srun`で起動します
（[KUDPCのバッチ処理マニュアル](https://web.kudpc.kyoto-u.ac.jp/manual/en/run/batch)）。
雛形はこの書式に合わせていますが、キュー名・上限値・配列ジョブの環境変数は最初のパイロットで確かめてください。

1. **データを運ぶ。** 入力データセットは`managed`なので既定の一覧にも入りますが、ここでは入力だけを名前で選びます。

    ```bash
    sopran-store --data-root /path/to/sopran_data sync-list \
      --dataset experimental.kaguya.er.paired_distributions > files.txt
    rsync -av --delay-updates --files-from=files.txt /path/to/sopran_data/ <host>:$SOPRAN_DATA_ROOT/
    ```

    転送した後、送り先で`sopran-store rebuild`と`verify-inputs`を実行します。

2. **ログインノードで環境を作る。** SOPRANをgitで取得して次を実行すると、uvとRustを`$HOME`に入れ、
   版を固定したvenvにSOPRANを（editableでなく）ビルドします。

    ```bash
    SOPRAN_SRC=$HOME/src/sopran ENV_ROOT=/LARGE0/grXXXXX/$USER/sopran-env \
      bash scripts/hpc/kyoto/setup_env.sh
    ```

    代わりに、CI（`publish.yml`）がビルドしたmanylinux x86_64のwheelを`--no-deps`で入れても構いません。

3. **ログインノードで確認と固定を行う。**

    ```bash
    source $ENV_ROOT/venv/bin/activate
    export SOPRAN_DATA_ROOT=/LARGE0/grXXXXX/$USER/sopran_data
    python -m sopran.experimental.kaguya.er_batch verify-inputs --input-variant <build>
    python -m sopran.experimental.kaguya.er_batch prepare --input-variant <build> \
      --run-variant <run> --groups 16
    ```

4. **パイロットで手元と一致するか確かめる。** 手元で完了した1日だけを`--days`で指定した別の実行を作り、1タスク（`-a 0`）で走らせます。
   手元の実行で完了したその日のParquetを転送し、`compare`で比べます。LinuxとWindowsでは指数・対数関数の実装が違うため、
   完全な一致は前提にしません。目的関数の相対差が小さく、候補が一致することを確かめます。

5. **本番を投入する。** `scripts/hpc/kyoto/er_fit.sbatch`の`-p`、`-t`、`--rsc`、`-a 0-(G-1)`を編集し、
   `ENV_ROOT`、`SOPRAN_DATA_ROOT`、`RUN_VARIANT`をexportして`sbatch`します。時間切れになったタスクは、同じコマンドで投入し直すと続きから処理します。

6. **結果を集める。** `status`で完了を確かめ、`finalize`でカタログに登録します。
   `sopran-store sync-list --dataset experimental.kaguya.er.finite_bin_fits --variant <run>`の一覧で手元へ戻し、手元で`sopran-store rebuild`を実行します。

## 検証

`tests/test_er_batch.py`で、変換で値が失われないこと、prepare→run→finalize→scanの流れ、partからの再開、`STOP`、
コードが変わったときの拒否、日の均等な割り振り、spawnのワーカーとプロセス内実行の一致を確かめています。
実データでの照合は`compare`で行い、その結果は各実行の記録として`working/`に残します。
