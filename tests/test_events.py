from __future__ import annotations

import polars as pl
import pytest

import sopran as spn
from sopran import Store


def test_store_event_catalog_writes_events_and_counts_by_month(tmp_path) -> None:
    store = Store(tmp_path / "store")
    catalog = store.event_catalog("lunar_wake", create=True)
    time = spn.period("2008-02-01", "2008-04-01")
    events = pl.DataFrame(
        {
            "time_start": [
                "2008-02-01T00:00:00Z",
                "2008-02-15T00:00:00Z",
                "2008-03-01T00:00:00Z",
            ],
            "time_stop": [
                "2008-02-01T00:10:00Z",
                "2008-02-15T00:10:00Z",
                "2008-03-01T00:10:00Z",
            ],
            "mission": ["kaguya", "kaguya", "kaguya"],
            "instrument": ["esa1", "esa1", "lmag"],
            "phenomenon": ["lunar_wake", "lunar_wake", "lunar_wake"],
            "confidence": [1.0, 0.8, 0.9],
            "detector": ["manual", "manual", "manual"],
            "detector_version": ["1", "1", "1"],
        }
    )

    record = catalog.write_events(events, time_coverage=time, overwrite=True)
    counts = catalog.counts(freq="month", by=("instrument",))

    assert record.manifest()["parameters"]["catalog"] == {
        "type": "event_catalog",
        "name": "lunar_wake",
        "time_column": "time_start",
    }
    assert counts.select("bin_start", "instrument", "event_count").to_dicts() == [
        {
            "bin_start": "2008-02-01T00:00:00Z",
            "instrument": "esa1",
            "event_count": 2,
        },
        {
            "bin_start": "2008-03-01T00:00:00Z",
            "instrument": "lmag",
            "event_count": 1,
        },
    ]
    assert store.database("lunar_wake").products()[0].dataset_id == "lunar_wake.events"


@pytest.mark.parametrize(
    ("time_stop", "confidence", "message"),
    [
        ("2008-01-01T00:00:00Z", 0.5, "time_stop > time_start"),
        ("2008-01-01T00:01:00Z", 1.1, "confidence"),
        ("2008-01-01T00:01:00Z", float("nan"), "confidence"),
    ],
)
def test_event_catalog_rejects_invalid_interval_and_confidence(
    tmp_path,
    time_stop,
    confidence,
    message,
) -> None:
    catalog = Store(tmp_path / "store").event_catalog("waves", create=True)
    events = _event_frame(
        time_start="2008-01-01T00:00:00Z",
        time_stop=time_stop,
        confidence=confidence,
    )

    with pytest.raises(ValueError, match=message):
        catalog.write_events(
            events,
            time_coverage=spn.period("2008-01-01", "2008-01-02"),
            overwrite=True,
        )


def test_event_catalog_normalizes_utc_and_counts_event_onsets(tmp_path) -> None:
    catalog = Store(tmp_path / "store").event_catalog("waves", create=True)
    events = _event_frame(
        time_start="2008-01-01T01:55:00+01:00",
        time_stop="2008-01-01T02:05:00+01:00",
        confidence=0.75,
    )
    catalog.write_events(
        events,
        time_coverage=spn.period("2008-01-01", "2008-01-02"),
        overwrite=True,
    )

    stored = catalog.scan().collect().to_dicts()[0]
    counts = catalog.counts(
        freq="day",
        time=spn.period("2008-01-01T01:00:00Z", "2008-01-01T01:01:00Z"),
    )

    assert stored["time_start"] == "2008-01-01T00:55:00Z"
    assert stored["time_stop"] == "2008-01-01T01:05:00Z"
    assert counts.is_empty()


def test_event_catalog_rates_keep_zero_events_and_null_zero_exposure(tmp_path) -> None:
    catalog = Store(tmp_path / "store").event_catalog("waves", create=True)
    events = _event_frame(
        time_start="2008-01-01T00:10:00Z",
        time_stop="2008-01-01T00:11:00Z",
        confidence=0.8,
    ).with_columns(
        pl.lit("bbn").alias("phenomenon"),
        pl.lit("run-1").alias("detector_run_id"),
    )
    catalog.write_events(
        events,
        time_coverage=spn.period("2008-01-01", "2008-01-03"),
        overwrite=True,
    )
    exposure = pl.DataFrame(
        {
            "bin_start": ["2008-01-01", "2008-01-02"],
            "bin_stop": ["2008-01-02", "2008-01-03"],
            "phenomenon": ["bbn", "bbn"],
            "detector_run_id": ["run-1", "run-1"],
            "eligible_window_count": [60, 0],
            "exposure_seconds": [3600.0, 0.0],
        }
    )

    rates = catalog.rates(exposure, freq="day", by=("phenomenon",))

    assert rates.select(
        "bin_start",
        "event_count",
        "exposure_seconds",
        "events_per_exposure_hour",
    ).to_dicts() == [
        {
            "bin_start": "2008-01-01T00:00:00Z",
            "event_count": 1,
            "exposure_seconds": 3600.0,
            "events_per_exposure_hour": 1.0,
        },
        {
            "bin_start": "2008-01-02T00:00:00Z",
            "event_count": 0,
            "exposure_seconds": 0.0,
            "events_per_exposure_hour": None,
        },
    ]


def test_event_catalog_rates_do_not_mix_detector_runs(tmp_path) -> None:
    catalog = Store(tmp_path / "store").event_catalog("waves", create=True)
    events = pl.concat(
        [
            _event_frame(
                time_start="2008-01-01T00:10:00Z",
                time_stop="2008-01-01T00:11:00Z",
                confidence=0.8,
            ).with_columns(pl.lit("run-1").alias("detector_run_id")),
            _event_frame(
                time_start="2008-01-02T00:10:00Z",
                time_stop="2008-01-02T00:11:00Z",
                confidence=0.8,
            ).with_columns(pl.lit("run-2").alias("detector_run_id")),
        ]
    )
    catalog.write_events(
        events,
        time_coverage=spn.period("2008-01-01", "2008-01-03"),
        overwrite=True,
    )
    exposure = pl.DataFrame(
        {
            "bin_start": ["2008-01-01"],
            "bin_stop": ["2008-01-02"],
            "phenomenon": ["lunar_wake"],
            "detector_run_id": ["run-1"],
            "exposure_seconds": [3600.0],
        }
    )

    with pytest.raises(ValueError, match="cannot mix detector runs"):
        catalog.rates(exposure, freq="day", by=("phenomenon",))


def test_event_catalog_rates_scope_detector_runs_to_exposure_groups(tmp_path) -> None:
    catalog = Store(tmp_path / "store").event_catalog("waves", create=True)
    first = _event_frame(
        time_start="2008-01-01T00:10:00Z",
        time_stop="2008-01-01T00:11:00Z",
        confidence=0.8,
    ).with_columns(
        pl.lit("bbn").alias("phenomenon"),
        pl.lit("run-1").alias("detector_run_id"),
    )
    second = _event_frame(
        time_start="2008-01-01T00:20:00Z",
        time_stop="2008-01-01T00:21:00Z",
        confidence=0.8,
    ).with_columns(
        pl.lit("radio").alias("phenomenon"),
        pl.lit("run-2").alias("detector_run_id"),
    )
    catalog.write_events(
        pl.concat([first, second]),
        time_coverage=spn.period("2008-01-01", "2008-01-02"),
        overwrite=True,
    )
    exposure = pl.DataFrame(
        {
            "bin_start": ["2008-01-01"],
            "bin_stop": ["2008-01-02"],
            "phenomenon": ["bbn"],
            "detector_run_id": ["run-1"],
            "exposure_seconds": [3600.0],
        }
    )

    rates = catalog.rates(exposure, freq="day", by=("phenomenon",))

    assert rates.select("phenomenon", "event_count").to_dicts() == [
        {"phenomenon": "bbn", "event_count": 1}
    ]


def test_event_catalog_rates_require_run_id_on_both_sides(tmp_path) -> None:
    catalog = Store(tmp_path / "store").event_catalog("waves", create=True)
    catalog.write_events(
        _event_frame(
            time_start="2008-01-01T00:10:00Z",
            time_stop="2008-01-01T00:11:00Z",
            confidence=0.8,
        ),
        time_coverage=spn.period("2008-01-01", "2008-01-02"),
        overwrite=True,
    )
    exposure = pl.DataFrame(
        {
            "bin_start": ["2008-01-01"],
            "bin_stop": ["2008-01-02"],
            "phenomenon": ["lunar_wake"],
            "detector_run_id": ["run-1"],
            "exposure_seconds": [3600.0],
        }
    )

    with pytest.raises(ValueError, match="in both events and exposure"):
        catalog.rates(exposure, freq="day", by=("phenomenon",))


def test_event_catalog_schema_describes_required_event_columns(tmp_path) -> None:
    schema = Store(tmp_path / "store").event_catalog("waves", create=True).schema()

    assert {variable.name for variable in schema.variables}.issuperset(
        {
            "time_start",
            "time_stop",
            "mission",
            "instrument",
            "phenomenon",
            "confidence",
            "detector",
            "detector_version",
        }
    )


def test_event_catalog_append_is_idempotent_by_event_id(tmp_path) -> None:
    store = Store(tmp_path / "store")
    catalog = store.event_catalog("waves", create=True)
    events = _event_frame(
        time_start="2008-01-01T00:00:00Z",
        time_stop="2008-01-01T00:01:00Z",
        confidence=0.8,
    ).with_columns(pl.lit("event-1").alias("event_id"))
    coverage = spn.period("2008-01-01", "2008-01-02")

    catalog.write_events(events, time_coverage=coverage, overwrite=True)
    catalog.write_events(events, time_coverage=coverage, append=True)

    assert catalog.scan().collect().height == 1


def test_event_catalog_append_rejects_schema_changes_and_id_conflicts(tmp_path) -> None:
    store = Store(tmp_path / "store")
    catalog = store.event_catalog("waves", create=True)
    coverage = spn.period("2008-01-01", "2008-01-02")
    initial = _event_frame(
        time_start="2008-01-01T00:00:00Z",
        time_stop="2008-01-01T00:01:00Z",
        confidence=0.8,
    ).with_columns(pl.lit("event-1").alias("event_id"))
    catalog.write_events(initial, time_coverage=coverage, overwrite=True)

    with pytest.raises(ValueError, match="append schema mismatch"):
        catalog.write_events(
            initial.drop("event_id"),
            time_coverage=coverage,
            append=True,
        )
    with pytest.raises(ValueError, match="conflicts with an existing event payload"):
        catalog.write_events(
            initial.with_columns(pl.lit(0.7).alias("confidence")),
            time_coverage=coverage,
            append=True,
        )
    assert catalog.scan().collect().height == 1


@pytest.mark.parametrize("bad_exposure", [None, -1.0, float("nan"), float("inf")])
def test_event_catalog_rates_reject_invalid_raw_exposure(tmp_path, bad_exposure) -> None:
    catalog = Store(tmp_path / "store").event_catalog("waves", create=True)
    events = _event_frame(
        time_start="2008-01-01T00:10:00Z",
        time_stop="2008-01-01T00:11:00Z",
        confidence=0.8,
    )
    catalog.write_events(
        events,
        time_coverage=spn.period("2008-01-01", "2008-01-02"),
        overwrite=True,
    )
    exposure = pl.DataFrame(
        {
            "bin_start": ["2008-01-01"],
            "bin_stop": ["2008-01-02"],
            "phenomenon": ["lunar_wake"],
            "exposure_seconds": [bad_exposure],
        }
    )

    with pytest.raises(ValueError, match="exposure_seconds"):
        catalog.rates(exposure, freq="day")


def test_event_catalog_rates_require_complete_time_bins(tmp_path) -> None:
    catalog = Store(tmp_path / "store").event_catalog("waves", create=True)
    events = _event_frame(
        time_start="2008-01-01T00:10:00Z",
        time_stop="2008-01-01T00:11:00Z",
        confidence=0.8,
    )
    catalog.write_events(
        events,
        time_coverage=spn.period("2008-01-01", "2008-01-02"),
        overwrite=True,
    )
    exposure = pl.DataFrame(
        {
            "bin_start": ["2008-01-01"],
            "bin_stop": ["2008-01-02"],
            "phenomenon": ["lunar_wake"],
            "exposure_seconds": [3600.0],
        }
    )

    with pytest.raises(ValueError, match="complete calendar bins"):
        catalog.rates(
            exposure,
            freq="day",
            time=spn.period("2008-01-01T00:00:00Z", "2008-01-01T01:00:00Z"),
        )


def _event_frame(*, time_start: str, time_stop: str, confidence: float) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "time_start": [time_start],
            "time_stop": [time_stop],
            "mission": ["kaguya"],
            "instrument": ["lrs_wfc"],
            "phenomenon": ["lunar_wake"],
            "confidence": [confidence],
            "detector": ["manual"],
            "detector_version": ["1"],
        }
    )
