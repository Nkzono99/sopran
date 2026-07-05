from __future__ import annotations

import polars as pl

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
