# ESAのmodeと入力フィルター

## 17/18を一括除外しない

PACEヘッダーの `mode` は機器共通のコマンド番号、`mode2` はセンサーの
sub-data mode、`type` は収録形式、`svs_tbl` は掃引RAMテーブルです。
**コマンド名が校正用でも、すべてのセンサーが校正信号を測っているとは限りません。**

| `mode` (hex) | 10進数 | 共通コマンド | ESAでの扱い |
|---|---:|---|---|
| `0x11` | 17 | TOFCAL | ESAはEC-N、type 0の角度別カウント。採用可能 |
| `0x12` | 18 | POSCAL | ESAは同じEC-N。採用可能 |
| `0x14` / `0x24` | 20 / 36 | 3D MASS Solarwind / Wake | 対応するlook形式なら採用 |
| `0x17` / `0x18` | 23 / 24 | 非圧縮Lunar Ion / ER Lunar Ion | 10進17/18とは別コマンド。形式で判定 |
| `0x29` | 41 | ER Lunar Ion Wake Backup | `type=1, svs_tbl=0` の組合せだけ既知の無効条件 |

公式仕様のMODE 11/12では、ESA-S1/S2のデータ構造はともに
`TYPE00_EC_N`、イオン側がそれぞれTOF/Position Checkです。
EC-Nは32エネルギー×16×64方向、収録時間16秒です。
これをESAまで一括除外していた `exclude_calibration_v1` は過剰なフィルターでした。
[公式PACE形式説明](https://data.darts.isas.jaxa.jp/pub/pds3/sln-l-pace-3-pbf1-v3.0/20071107/document/PACE_Format_en_V01.pdf)、
[公式ヘッダー定義](https://data.darts.isas.jaxa.jp/pub/pds3/sln-l-pace-3-pbf1-v3.0/20071107/software/paceql_outputdata_090805.h)

`Solarwind` / `Wake` というコマンド名自体は、衛星の実際の上流環境の判定ではありません。
環境分類は座標やプラズマ・上流観測から別途行います。

## 現在の判定

`esa_look_quality_v2` は、rawデータではなく**検出器視線から作るpitch spectrumの適格性**を判定します。
counts/energy fluxのpitch生成、S1/S2の組合せ、ER入力に同じ規則を適用します。

| 条件 | 結果・理由 |
|---|---|
| 通常コマンド、ESA type 0/1 | 採用可能。17/18も含む |
| `mode=0x29, type=1, svs_tbl=0` | `spedas_mode29_type1_ram0_invalid` |
| 共通modeに内部カウントの `0x80` ビットあり | `internal_count_mode` |
| 通常コマンド表にない特殊・未確認コマンド | `unvalidated_command`。物理的に無効と確定した意味ではない |
| type 2 | `onboard_pitch_sorted_not_supported`。搭載側pitch集約済みで、検出器視線からの再構築には未対応 |
| その他のESA type | `unsupported_esa_look_type`。type 3には対応する角度校正経路がない |

0x29の条件はSPEDASのESA-S1/S2 `get3d` の `valid=0` と一致します。
0x29全体やRAM 0全体を除外するものではありません。
SPEDASはtype 0/1を読み込み、type 2のget3dは未対応扱いです。
[SPEDAS ESA-S1](https://raw.githubusercontent.com/spedas/bleeding_edge/master/idl/projects/kaguya/map/pace/kgy_esa1_get3d.pro)、
[ESA-S2](https://raw.githubusercontent.com/spedas/bleeding_edge/master/idl/projects/kaguya/map/pace/kgy_esa2_get3d.pro)

特殊コマンドの中にはイオン側だけの操作もあり得ます。まだ通常ESA観測と同等とは検証できないため
保留にしており、TOFスキャン等を一律「ESAの校正データ」と断定しません。
`data_quality` のビット意味も公開資料で確定していません。実データには `0xFFFFFFFF` があり、
非ゼロという理由だけでは除外せず `pace_data_quality` 座標にそのまま残します。

この判定を通っても、角度・感度校正、有限磁場、姿勢、S1/S2時刻整合、fitのsupport検査は必要です。
「採用可能」はロスコーン検出成功を意味しません。生のゼロカウントや低カウントも、
有効なexposureがある限り、このmode判定では捨てません。

## 観測メタデータとcache

`pace_data_mode`、`pace_data_type`、`pace_submode`、`pace_svs_tbl`、
`pace_data_quality`、`record_duration_seconds`をpitch配列とStoreに残します。
全除外は`excluded_by_record_policy`として、未取得やSPICE失敗と区別します。

`record_duration_seconds=16`は1レコードの収録時間で、各検出器視線の
`integration_time_seconds=16/sampl_time`とは異なります。
時間窓への割当・積分やfit supportは解析側の別条件です。

自動variantと明示variantの検査に品質policyを含めます。異なるpolicyで作った
pitch cacheを同じものとして再利用しません。元ファイルは変更しません。
