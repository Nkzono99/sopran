# PACE ESAのmode判定

ピッチ角スペクトルを作るとき、SOPRANはPACEの各記録を観測モードから「検出器の視線から再構成してよいか」で選別します。
このページはその規則（`esa_look_quality_v2`）と根拠をまとめます。

## 結論：mode 17/18も採用する

PACEヘッダーの`mode`は全センサー共通のコマンド番号、`mode2`はセンサーごとのサブモード、`type`は収録形式、
`svs_tbl`は電圧掃引テーブルです。**コマンド名が校正用でも、すべてのセンサーが校正信号を測っているとは限りません。**

| `mode`（16進） | 10進 | 共通コマンド | ESAでの扱い |
|---|---:|---|---|
| `0x11` | 17 | TOFCAL | ESAはEC-N（type 0）の角度別カウント。採用する |
| `0x12` | 18 | POSCAL | ESAは同じEC-N。採用する |
| `0x14` / `0x24` | 20 / 36 | 3D MASS Solarwind / Wake | 対応する視線形式なら採用する |
| `0x17` / `0x18` | 23 / 24 | 非圧縮Lunar Ion / ER Lunar Ion | 10進の17/18とは別のコマンド。形式で判定する |
| `0x29` | 41 | ER Lunar Ion Wake Backup | `type=1, svs_tbl=0`の組み合わせだけが既知の無効条件 |

公式仕様のMODE 11/12では、ESA-S1/S2のデータ構造はどちらも`TYPE00_EC_N`で、イオン側がそれぞれTOF/Position Checkです。
EC-Nは32エネルギー×16×64方向、収録時間16秒です。これをESAまで一括で除外していた旧規則
`exclude_calibration_v1`は過剰でした。

`Solarwind`・`Wake`というコマンド名は、探査機が実際に太陽風中やウェイク中にいたことを意味しません。
環境の分類は、位置・プラズマ・上流の観測から別に行います。

## 判定の規則

`esa_look_quality_v2`は、生データではなく**検出器の視線から作るピッチ角スペクトルの適格性**を判定します。
カウントとエネルギーフラックスのピッチ角スペクトル、S1/S2の組み合わせ、電子反射法の入力に同じ規則を使います。

| 条件 | 結果と理由コード |
|---|---|
| 通常のコマンドで、ESAのtype 0/1 | 採用。17/18も含む |
| `mode=0x29, type=1, svs_tbl=0` | 除外：`spedas_mode29_type1_ram0_invalid` |
| 共通modeに内部カウントを示す`0x80`ビット | 除外：`internal_count_mode` |
| 通常のコマンド表に無い特殊・未確認のコマンド | 除外：`unvalidated_command`（物理的に無効と確定した意味ではない） |
| type 2 | 除外：`onboard_pitch_sorted_not_supported`（機上でピッチ角に集約済みで、視線からの再構成に未対応） |
| その他のtype | 除外：`unsupported_esa_look_type`（type 3には対応する角度校正の経路が無い） |

0x29の条件は、SPEDASのESA-S1/S2の`get3d`が`valid=0`とする条件と一致します。0x29全体やRAM 0全体を除外するものではありません。
SPEDASもtype 0/1を読み、type 2の`get3d`は未対応です。

特殊コマンドにはイオン側だけの操作もあり得ますが、通常のESA観測と同等だとはまだ確かめられていないため保留にしています。
TOFスキャンなどを一律に「ESAの校正データ」とは扱いません。

## この判定が保証しないこと

採用は、角度・感度の校正、有限の磁場、姿勢、S1/S2の時刻整合、当てはめに必要なデータ点の有無を確かめたことを意味しません。
ロスコーンが検出できることも意味しません。生のゼロカウントや少ないカウントも、有効な露出時間がある限りこの判定では捨てません。

`data_quality`のビットの意味は公開資料で確定していません。実データには`0xFFFFFFFF`も現れますが、
非ゼロというだけでは除外せず、値を`pace_data_quality`座標にそのまま残します。

## 記録とキャッシュ

`pace_data_mode`、`pace_data_type`、`pace_submode`、`pace_svs_tbl`、`pace_data_quality`、`record_duration_seconds`を
ピッチ角スペクトルとStoreに残します。すべての記録が除外された時刻は`excluded_by_record_policy`として、
未取得やSPICEの失敗と区別します。

`record_duration_seconds=16`は1記録の収録時間で、各視線の`integration_time_seconds = 16 / sampl_time`とは異なります。
時間窓への割り当てや当てはめに使うデータ点の条件は、解析側で別に決めます。

キャッシュの識別には品質の規則も含めます。異なる規則で作ったピッチ角スペクトルを同じものとして再利用せず、
元ファイルも変更しません。

## 出典

- [PACE形式説明（JAXA DARTS）](https://data.darts.isas.jaxa.jp/pub/pds3/sln-l-pace-3-pbf1-v3.0/20071107/document/PACE_Format_en_V01.pdf)
- [PACEヘッダー定義](https://data.darts.isas.jaxa.jp/pub/pds3/sln-l-pace-3-pbf1-v3.0/20071107/software/paceql_outputdata_090805.h)
- SPEDAS [`kgy_esa1_get3d.pro`](https://raw.githubusercontent.com/spedas/bleeding_edge/master/idl/projects/kaguya/map/pace/kgy_esa1_get3d.pro)、
  [`kgy_esa2_get3d.pro`](https://raw.githubusercontent.com/spedas/bleeding_edge/master/idl/projects/kaguya/map/pace/kgy_esa2_get3d.pro)
