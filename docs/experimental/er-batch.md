# ERの全期間バッチ（日別shard・Slurm）

`sopran.experimental.kaguya.er_batch` は、保存済みのpaired分布にfinite-bin fitとRm profileを全期間で行う。
同じコマンドで、手元のPCでも京大スパコンのSlurm array jobでも動く。
入力と出力はStoreのdatasetとして日別Parquetに分かれているため、`rsync`でそのまま運べる。

| dataset | layer | variant | 中身 |
|---|---|---|---|
| `experimental.kaguya.er.paired_distributions` | `features` | 入力のbuild名 | 窓ごとのfold済みcount・exposure・record。1日1 shard |
| `experimental.kaguya.er.finite_bin_fits` | `models` | run名 | 窓ごとのfit・profile・candidate。1日1 shard |

コマンドは `python -m sopran.experimental.kaguya.er_batch [--data-root ROOT] <command>` の形で使う。
`--data-root`を省くと`SOPRAN_DATA_ROOT`（またはsopranの設定）のStoreを使う。
依存は`experimental`と`kaguya`のextra（numpy、scipy、polars）である。

## 流れ

```text
export-catalog -> verify-inputs -> prepare -> run（並列・再開可） -> status -> finalize -> compare
```

| command | 内容 |
|---|---|
| `export-catalog --catalog PATH --input-variant V [--workers N]` | SQLite catalogを日別shardへ変換する。既存の日は飛ばす |
| `verify-inputs --input-variant V` | 転送後に入力shardのchecksumを確かめる |
| `prepare --input-variant V --run-variant R [--groups G] [--fit-setting name=JSON]` | 設定・入力・コードと環境のhashを`run.json`に固定する |
| `run --run-variant R [--group i \| --days D...] [--workers N]` | 指定した日をfitする。未完了の日だけを処理する |
| `status --run-variant R` | 完了日数とheartbeatを表示する |
| `finalize --run-variant R` | 完了shardのchecksumを再計算し、Storeのcatalogに登録する |
| `compare --run-variant R --reference FILE...` | 別runの日別Parquetと、同じ窓の目的関数・Beff・candidateを比べる |

### 入力の契約

入力は、窓ごとのpaired分布を保存したSQLite catalogを変換するか、
下のSOPRANの部品で生データから作ります。catalogは次の形で渡します。

| 列 | 型 | 内容 |
|---|---|---|
| `sample_id` | TEXT | 16 s窓のID |
| `day` | TEXT | UTC日（`YYYY-MM-DD`） |
| `record` | TEXT | 窓のrecord（JSON）。`time`・`b_sc_nT`・`affected_side`・`field_connection_status`・`field_radial_abs_cosine_min`・`magnetic_direction_max_deviation_deg`・`reason`を読む |
| `maps` | BLOB | `.npz`。分布のない窓はNULL |

表名は`windows`です。`maps`には`FLOAT_ARRAYS`・`BOOL_ARRAYS`の配列を入れます。
fold済みの配列は`energy x pitch_folded`、`global_*`は`energy x pitch`の形です。

### 入力の変換

```bash
python -m sopran.experimental.kaguya.er_batch --data-root /path/to/sopran_data export-catalog \
  --catalog /path/to/catalog.sqlite --input-variant <build> --workers 3
```

catalogの窓ごとのnpz blobから、fold済みのcount・exposure・`fit_valid`・`pair_observed`・
全pitchのcount・exposure・energy/pitchのedgeを、row-majorで平坦化したlist列に移す。
変換時に各配列がfloat64・boolで無損失に表せることを確かめる。
旧fitの派生量（`observed_log_ratio`・`fitted_log_ratio`・`beam_ratio`）は持たない。
窓のrecord（JSON）と、record＋blobのsha256（`source_sha256`）も残す。
`days.json`に全日（入力なしの日を含む）の窓数・分布数・checksumを書く。

### SOPRANの部品で入力を作る

SQLite catalogを使わず、生データから入力shardを作る部品もあります。
既定値は2026-09の全期間run（`halekas_mission_v1`）の規則と同じです。
日の並列化・再開・ログなど全期間runの組み立ては、利用者側のスクリプトで行います。

| 段階 | 部品 |
|---|---|
| 1日のnative記録とLMAG幾何 | `KaguyaErInstrument(mission).native_records(day)` |
| 16 s窓の集計と診断 | `er_windows.calendar_windows`・`window_record`・`window_input_diagnostic` |
| SVM3Dによる接続判定 | `moon.connection.trace_connection`・`classify_connection`（`ConnectionPolicy`） |
| paired map | `er_windows.window_pitch_records` → `electron_reflection.maps.build_paired_map` |
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

`window_record`は窓内のLMAGサンプルから磁場方向の最大偏差を、記録時刻のB/r余弦から
`field_radial_abs_cosine_min`を求める。`build_paired_map`は各記録を影響側が低ピッチ側に
来る向きにそろえ、20–1500 eV・24 energy×16 pitchの格子へビンの重なりで配分して
countとexposureを足し、影響側と参照側に折り返す。`fit_valid`はペアの両側でexposureが正で
countがあり、energy行あたり3 cell以上ある範囲である。接続判定は一様残差を足したSVM3D場を
0.5 km刻み・停止高度6.1 km・最大1000 kmで追跡し、内向きがshellに届き逆向きが届かず、
符号が窓内で変わらない窓を`model_connected`とする。

### runの固定と実行

`prepare`は、`FiniteBinFitSettings()`の既定に`--fit-setting`の上書きを加えた設定、入力catalogのchecksumを`run.json`に記録する。
fitコード・native拡張のsha256、Python・numpy・scipy・polarsの版も記録する。
`run`は起動時にこれらを現在の環境と比べ、違えば止まる。同じrun名で設定を変えることはできない。

`run`は日を1つずつ処理し、その日の窓をworkerプロセス（spawn）に分配する。
workerは`OMP_NUM_THREADS`等を1に固定する。`--workers`の既定は割り当てCPU数（Linuxではaffinity）で、`0`はプロセス内実行である。
256窓ごとに`work/<day>/part-*.parquet`へ保存し、日の完了時に`shards/day=<day>.parquet`と`days/<day>.json`を書く。
再実行すると、完了日を飛ばし、保存済みのpartは再計算しない。
run directoryに`STOP`を作ると、全invocationが現在の窓の後に保存して終了する。
各invocationは自分の日のファイルだけを書くので、array jobを同時に走らせてよい。
`--groups G`は、日を分布数で均等になるようG組に分ける。`run --group i`がi番目の組を処理する。

1窓の処理はcount尤度の既定設定によるfitである。
geometry条件（Bsc>0、磁場方向偏差≤20°、半径角<80°、`model_connected`）を満たし、field flagのない窓だけprofileを行う。
profileはRm±1 dexの13点で、95%区間と`minimum_fit`を出す。
列の意味は`finalize`が書く`schema.json`にある。

## 京大スパコンで動かす

スクリプトは `scripts/hpc/kyoto/` にある。京大のSlurmは独自に拡張されている。
資源は`--rsc p=PROCS:t=THREADS:c=CORES:m=MEMORY`で指定し、`-p`のキュー指定は必須である。
プログラムは`srun`で起動する（[KUDPCのバッチ処理マニュアル](https://web.kudpc.kyoto-u.ac.jp/manual/en/run/batch)）。
雛形はこの書式に合わせたが、キュー名・上限値・array jobの環境変数は、最初のパイロットで確かめる。

1. **データを運ぶ。** 入力datasetは`managed`なので、Storeの同期手順でそのまま運べる。

   ```bash
   sopran-store --data-root /path/to/sopran_data sync-list \
     --dataset experimental.kaguya.er.paired_distributions > files.txt
   rsync -av --delay-updates --files-from=files.txt /path/to/sopran_data/ <host>:$SOPRAN_DATA_ROOT/
   ```

   転送後に送り先で`sopran-store rebuild`と`verify-inputs`を行う。
2. **ログインノードで環境を作る。** sopranをgitで取得し、次を実行する。
   uvとRustを`$HOME`に入れ、版を固定したvenvにsopranを非editableでbuildする。

   ```bash
   SOPRAN_SRC=$HOME/src/sopran ENV_ROOT=/LARGE0/grXXXXX/$USER/sopran-env \
     bash scripts/hpc/kyoto/setup_env.sh
   ```

   代わりに、CI（`publish.yml`）がbuildしたmanylinux x86_64のwheelを`--no-deps`で入れてもよい。
3. **ログインノードで確認と固定を行う。**

   ```bash
   source $ENV_ROOT/venv/bin/activate
   export SOPRAN_DATA_ROOT=/LARGE0/grXXXXX/$USER/sopran_data
   python -m sopran.experimental.kaguya.er_batch verify-inputs --input-variant <build>
   python -m sopran.experimental.kaguya.er_batch prepare --input-variant <build> \
     --run-variant <run> --groups 16
   ```

4. **パイロットで手元と一致するか確かめる。** 手元で完了した1日だけを`--days`で指定した別runを作り、1 task（`-a 0`）で実行する。
   手元のrunで完了したその日のParquetを転送し、`compare`で比べる。
   LinuxとWindowsでは指数・対数関数の実装が違うため、完全一致は前提にしない。
   目的関数の相対差が小さく、candidateが一致することを確かめる。
5. **本番を投入する。** `scripts/hpc/kyoto/er_fit.sbatch`の`-p`・`-t`・`--rsc`・`-a 0-(G-1)`を編集し、
   `ENV_ROOT`・`SOPRAN_DATA_ROOT`・`RUN_VARIANT`をexportして`sbatch`する。
   時間切れになったtaskは、同じコマンドで再投入すれば続きから処理する。
6. **集める。** `status`で完了を確かめ、`finalize`でcatalogに登録する。
   `sopran-store sync-list --dataset experimental.kaguya.er.finite_bin_fits --variant <run>`の一覧で手元へ戻し、手元で`sopran-store rebuild`を行う。

## 検証

- `tests/test_er_batch.py`：変換の無損失性、prepare→run→finalize→scan、part再開、STOP、
  コード変更の拒否、日の均等割り、spawn workerとプロセス内実行の一致。
- 実データでの照合は`compare`で行い、結果は各runの記録として`working/`に残す。
