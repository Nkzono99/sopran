# Python API

主な公開クラスと関数のリファレンスです。本文はソースのdocstringから生成しているため英語です。
使い方の説明は「ガイド」と「データ」の各ページを参照してください。

## 入口と設定

::: sopran.config.use

::: sopran.config.using

::: sopran.config.save_user

::: sopran.core.config.resolve_store_roots

::: sopran.core.config.resolve_download_mode

::: sopran.core.config.default_project_root

::: sopran.core.view.view

::: sopran.core.loaders.load

## 期間

::: sopran.core.time.TimeRange

::: sopran.core.time.period

::: sopran.core.time.day

::: sopran.core.time.month

::: sopran.core.time.year

## 解析条件

::: sopran.core.view.View

::: sopran.core.view.ViewSelection

::: sopran.core.view.ViewContext

::: sopran.core.project.Project

::: sopran.core.project.Case

::: sopran.core.project.ProjectArtifact

::: sopran.core.project.ProjectCaseRecord

## データ

::: sopran.core.data.SopranArray

::: sopran.missions.kaguya.mission.Kaguya

::: sopran.missions.kaguya.data.KaguyaPaceData

::: sopran.missions.artemis.mission.Artemis

::: sopran.missions.lunar_prospector.mission.LunarProspector

::: sopran.missions.omni.hourly.Omni

::: sopran.bodies.moon.Moon

::: sopran.maps.Region

## 可視化

::: sopran.core.plotting.PlotItem

::: sopran.core.plotting.PlotStack

::: sopran.core.plotting.PlotResult

::: sopran.core.plotting.QuicklookResult

::: sopran.core.pages.InfoPage

::: sopran.core.pages.GuidePage

## 時刻合わせ

::: sopran.core.alignment.TimeBins

::: sopran.core.alignment.SampleTable

::: sopran.core.alignment.SampleSpec

::: sopran.core.alignment.AlignmentResult

::: sopran.core.alignment.FeatureMatrix

## 座標変換

::: sopran.frames.FrameContext

::: sopran.frames.FrameTransformPlan

::: sopran.frames.normalize_frame

## Store

::: sopran.core.store.Store

::: sopran.core.store.DatasetRecord

::: sopran.core.database.Database

::: sopran.core.database.ProductRef

::: sopran.core.events.EventCatalog

## バッチ処理

::: sopran.core.pipeline.Pipeline

::: sopran.core.pipeline.PipelineBackend

::: sopran.core.pipeline.PipelineResult

## スキーマ

::: sopran.core.schema.InstrumentSchema

::: sopran.core.schema.VariableSchema

::: sopran.core.schema.validate_schema

::: sopran.schema_docs.builtin_schemas

::: sopran.schema_docs.schema_reference_markdown

## データ源の登録

::: sopran.core.sources.register_source

::: sopran.core.sources.source_names

## 例外

::: sopran.core.errors
