# ERの全期間バッチ（日別shard・Slurm）

`sopran.experimental.kaguya.er_batch` は、保存済みのpaired分布にfinite-bin fitとRm profileを全期間で行う。
同じコマンドで、手元のPCでも京大スパコンのSlurm array jobでも動く。
入力と出力はStoreのdatasetとして日別Parquetに分かれているため、`rsync`でそのまま運べる。

| dataset | layer | variant | 中身 |
|---|---|---|---|
| `kaguya.er.paired_distributions` | `features` | 入力のbuild名（例 `halekas-mission-20260912`） | 窓ごとのfold済みcount・exposure・record。1日1 shard |
| `kaguya.er.finite_bin_fits` | `models` | run名（例 `bb-default-kyoto`） | 窓ごとのfit・profile・candidate。1日1 shard |

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

### 入力の変換

```powershell
python -m sopran.experimental.kaguya.er_batch --data-root F:/sopran_data export-catalog `
  --catalog C:/.../halekas-mission-20260912/all-period/catalog.sqlite `
  --input-variant halekas-mission-20260912 --workers 3
```

catalogの窓ごとのnpz blobから、fold済みのcount・exposure・`fit_valid`・`pair_observed`・
全pitchのcount・exposure・energy/pitchのedgeを、row-majorで平坦化したlist列に移す。
変換時に各配列がfloat64・boolで無損失に表せることを確かめる。
旧fitの派生量（`observed_log_ratio`・`fitted_log_ratio`・`beam_ratio`）は持たない。
窓のrecord（JSON）と、record＋blobのsha256（`source_sha256`）も残す。
`days.json`に全日（入力なしの日を含む）の窓数・分布数・checksumを書く。

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

1. **データを運ぶ。** 入力datasetは`managed`なので、Storeの同期手順でそのまま運べる（約13 GB）。

   ```bash
   sopran-store --data-root F:/sopran_data sync-list --dataset kaguya.er.paired_distributions > files.txt
   rsync -av --delay-updates --files-from=files.txt F:/sopran_data/ <host>:$SOPRAN_DATA_ROOT/
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
   python -m sopran.experimental.kaguya.er_batch verify-inputs --input-variant halekas-mission-20260912
   python -m sopran.experimental.kaguya.er_batch prepare --input-variant halekas-mission-20260912 \
     --run-variant bb-default-kyoto --groups 16
   ```

4. **パイロットで手元と一致するか確かめる。** `--days 2009-02-17`だけの別runを作り、1 task（`-a 0`）で実行する。
   手元のrunで完了したその日のParquetを転送し、`compare`で比べる。
   LinuxとWindowsでは指数・対数関数の実装が違うため、完全一致は前提にしない。
   目的関数の相対差が小さく、candidateが一致することを確かめる。
5. **本番を投入する。** `scripts/hpc/kyoto/er_fit.sbatch`の`-p`・`-t`・`--rsc`・`-a 0-(G-1)`を編集し、
   `ENV_ROOT`・`SOPRAN_DATA_ROOT`・`RUN_VARIANT`をexportして`sbatch`する。
   時間切れになったtaskは、同じコマンドで再投入すれば続きから処理する。
6. **集める。** `status`で完了を確かめ、`finalize`でcatalogに登録する。
   `sopran-store sync-list --dataset kaguya.er.finite_bin_fits --variant <run>`の一覧で手元へ戻し、手元で`sopran-store rebuild`を行う。

## 検証

- `tests/test_er_batch.py`：変換の無損失性、prepare→run→finalize→scan、part再開、STOP、
  コード変更の拒否、日の均等割り、spawn workerとプロセス内実行の一致。
- 2026-10-10に、手元の全期間run（catalogを直接読む実装）で完了した2009-02-17から46窓を選んで照合した。
  本モジュールで日別shard経由でfitした結果と、Beff・目的関数・profile区間・candidateが完全に一致した。
