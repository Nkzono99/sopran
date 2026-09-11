import numpy as np
import pandas as pd

from sopran.analysis.electron_reflection.upstream import match_omni_hourly, read_omni_hourly


def test_fill_and_half_open_hour_join(tmp_path):
    rows = np.zeros((2, 42))
    rows[:, :3] = [[2008, 60, 1], [2008, 60, 2]]
    rows[:, 28] = [1.5, 99.99]
    path = tmp_path / "omni.dat"
    np.savetxt(path, rows)
    hourly = read_omni_hourly(path)
    assert hourly.index[0] == pd.Timestamp("2008-02-29T01:00Z")
    times = pd.to_datetime(["2008-02-29T01:59:59Z", "2008-02-29T02:00:00Z", "2008-02-29T03:00:00Z"])
    matched = match_omni_hourly(times, hourly)
    assert matched.omni_pressure_nPa.iloc[0] == 1.5
    assert matched.omni_pressure_nPa.iloc[1:].isna().all()
    assert matched.upstream_pressure_available.tolist() == [True, False, False]
    assert set(matched.lunar_plasma_regime) == {"undetermined"}
