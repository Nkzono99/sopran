# Storeを別マシンへ運ぶ

手元のPCで作った入力をスーパーコンピューターへ送る、計算結果を手元へ戻す、といった移動は、
Storeのファイルを`rsync`で写して索引を作り直すだけで済みます。このページはその手順と、成り立たせている約束をまとめます。

## 手順

```bash
# 送り元：送るファイルの一覧を作る
sopran-store --data-root /path/to/sopran_data sync-list > files.txt

# 転送する
rsync -av --delay-updates --files-from=files.txt /path/to/sopran_data/ host:/data/sopran_data/

# 送り先：索引を作り直し、欠けや破損を確かめる
ssh host sopran-store --data-root /data/sopran_data rebuild
ssh host sopran-store --data-root /data/sopran_data verify
```

`--delay-updates`は、転送したファイルを最後にまとめて置き換えるrsyncのオプションです。
転送途中のStoreを別のジョブが読んでも、ファイルが半端な状態になりません。

## 送るものを選ぶ

`sync-list`は既定で、SOPRANが自動で作り再利用するデータセット（`managed=True`）だけを並べます。
軌道幾何・磁力線の接続・LRS・ピッチ角スペクトルのキャッシュ、データの有無の集計がこれに当たります。

```bash
# データセットIDやその先頭部分を指定する（managedでなくても対象になる）
sopran-store --data-root /path/to/sopran_data sync-list \
  --dataset experimental.kaguya.er.paired_distributions > files.txt

# 元ファイルの一部も加える
sopran-store --data-root /path/to/sopran_data sync-list --raw spice > files.txt
```

`--layer`、`--variant`で層と計算条件を絞れます。`--all`は試行錯誤中のものを含む全データセットを対象にします。

## 運べる理由

Storeは次の約束を守るように書いています。送り先のルートのパスが違っても、同じデータセットとして使えます。

- **参照はルートからの相対パス。** マニフェストやカタログに絶対パスを書きません。Storeの外にあるファイルは、
  チェックサムと元の場所の手がかりとして記録するだけで、探索には使いません。
- **キャッシュのIDは内容から決まる。** `variant_id`は設定と入力（元ファイルのチェックサムやSPICEカーネルの名前・ハッシュ・サイズ）から作ります。
  同じ処理はどの計算機でも同じIDになり、運んだ結果がそのまま再利用されます。
- **シャードの付属JSONが正本。** 各シャードは一時ファイルに書いてから名前を変え、隣に`<shard>.sopran.json`を置きます。
  `catalog.parquet`はそこから作り直せる索引です。別の計算機やジョブが同じデータセットの別シャードを書いても、
  運んだ後に`rebuild`すれば合流します。
- **計算機ごとのものは運ばない。** `registry/`、`cache/`、データセットの`work/`、`*.sopran-tmp*`、`*.sopran-bak*`は
  同期の対象外です。`registry/`はマニフェストの変化を検知して自動で作り直されます。
  除外パターンは`sopran-store excludes`で表示でき、`rsync --exclude-from`に渡せます。

`rebuild`は、付属JSONの無い古いデータセットにも付属JSONを作ります（移行）。

## Pythonから行う

| コマンド | Python |
|---|---|
| `rebuild` | `store.rebuild()`、`record.rebuild_catalog()` |
| `verify` | `record.verify_shards()` |
| Store外のファイルの参照を作る | `store.file_reference(path)` |

コマンドのオプションは[コマンドライン](../reference/cli.md)にまとめています。
