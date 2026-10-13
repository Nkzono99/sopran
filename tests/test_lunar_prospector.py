from __future__ import annotations

from datetime import date
from email.message import Message
from io import BytesIO
from urllib.error import HTTPError

import numpy as np
import pytest

import sopran as spn
from sopran.missions.lunar_prospector import files as lp_files
from sopran.missions.lunar_prospector.files import (
    LpFileSource,
    lp_provider_path,
    lp_support_path,
    volume_for,
)

ENERGIES_A = [16680.334, 10813.814, 7010.566, 4544.932, 2946.467, 1910.187, 1238.369, 802.831,
              520.473, 337.421, 218.749, 141.815, 91.938, 59.603, 38.641]
ENERGIES_B = [round(value * 0.9, 3) for value in ENERGIES_A]


def _mag_table() -> str:
    rows = [
        "1998-02-01T00:00:02.5   32.000029   -4.158   6.343   8.718    7.642  -1.145   8.592"
        "    0.039   1749.30   339.58  -441.70   -880.26 -1542.01  -466.69  1",
        "1998-02-01T00:00:07.5   32.000087  999.999 999.999 999.999  999.999 999.999 999.999"
        "  999.999 999999.99 999999.99 999999.99 999999.99 999999.99 999999.99  1",
    ]
    return "\r\n".join(rows) + "\r\n"


def _energy_bins() -> str:
    first = " ".join(f"{value:9.3f}" for value in ENERGIES_A)
    second = " ".join(f"{value:9.3f}" for value in ENERGIES_B)
    return (
        f"     886291200. 1998-02-01T00:00:00Z {first}\r\n"
        f"     886298400. 1998-02-01T02:00:00Z {second}\r\n"
    )


def _er_table() -> str:
    def row(time: str, scale: float) -> str:
        values = [scale * (index + 1) for index in range(15)]
        values[3] = 9.999e-99
        return time + " " + " ".join(f"{value:9.3E}" for value in values)

    return "\r\n".join([row("1998-02-01T01:00:00", 1.0), row("1998-02-01T03:00:00", 2.0)]) + "\r\n"


def _theta() -> str:
    return " ".join(f"{-78.75 + index:6.2f}" for index in range(88)) + "\r\n"


def _three_d_table() -> str:
    rows = []
    for spectrum, seconds, steps in ((1, 886291221, 15), (2, 886291302, 3)):
        for step in range(steps):
            minute = "00:00:21" if spectrum == 1 else "00:01:42"
            flux = " ".join(f"{(spectrum * 100 + step):9.3E}" for _ in range(88))
            phi = " ".join(f"{450.45 + look:6.2f}" for look in range(88))
            rows.append(
                f"1998-02-01T{minute} {seconds:15d}. {ENERGIES_A[step]:9.3f} {spectrum:4d} "
                f"{8.061378:13.6f} {-0.959263:13.6f} {8.025205:13.6f} {flux} {phi}"
            )
    return "\r\n".join(rows) + "\r\n"


def _store_with_day(tmp_path) -> spn.Store:
    store = spn.Store(tmp_path / "store")
    source = LpFileSource(store)
    day = date(1998, 2, 1)
    for dataset, text in (
        ("MAG", _mag_table()),
        ("ER_LO_TS", _er_table()),
        ("ER_3DIST", _three_d_table()),
    ):
        path = source.local_path(str(lp_provider_path(dataset, day)))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="ascii", newline="")
    for dataset, name, text in (
        ("ER_LO_TS", "E_BINS.TAB", _energy_bins()),
        ("ER_3DIST", "THETA.TAB", _theta()),
    ):
        path = source.local_path(lp_support_path(dataset, name))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="ascii", newline="")
    return store


def test_volumes_and_paths_follow_the_ppi_layout() -> None:
    assert volume_for(date(1998, 1, 16)) == "LP_1201"
    assert volume_for(date(1998, 11, 1)) == "LP_1203"
    assert volume_for(date(1999, 7, 30)) is None
    assert lp_provider_path("ER_3DIST", date(1999, 4, 2)) == (
        "LP_1204/DATA/ER_3DIST/99_04APR/3D990402.TAB"
    )


def test_mag_reads_both_frames_and_marks_missing_values(tmp_path) -> None:
    lp = spn.LunarProspector(store=_store_with_day(tmp_path), download="never")
    time = spn.day("1998-02-01")

    sse = lp.mag.magnetic_field.load(time)
    position = lp.mag.position_sel.load(time).to_xarray()

    assert sse.schema.frame == "SSE"
    np.testing.assert_allclose(sse.to_xarray().values[0], [7.642, -1.145, 8.592])
    np.testing.assert_allclose(lp.mag.magnetic_field_sel.load(time).to_xarray().values[0],
                               [-4.158, 6.343, 8.718])
    np.testing.assert_allclose(position.values[0], [1749.30, 339.58, -441.70])
    assert np.isnan(sse.to_xarray().values[1]).all() and np.isnan(position.values[1]).all()
    assert lp.mag.b is lp.mag.magnetic_field


def test_er_flux_uses_the_energy_table_in_effect(tmp_path) -> None:
    lp = spn.LunarProspector(store=_store_with_day(tmp_path), download="never")

    flux = lp.er.electron_flux.load(spn.day("1998-02-01")).to_xarray()

    assert flux.dims == ("time", "energy_bin")
    np.testing.assert_allclose(flux.coords["energy"].values[0], ENERGIES_A)
    np.testing.assert_allclose(flux.coords["energy"].values[1], ENERGIES_B)
    assert np.isnan(flux.values[0, 3])  # 9.999E-99 is the missing constant
    assert flux.values[1, 0] == pytest.approx(2.0)
    assert flux.attrs["units"] == "1/(cm^2 s sr eV)"


def test_er_3d_groups_records_into_spectra(tmp_path) -> None:
    lp = spn.LunarProspector(store=_store_with_day(tmp_path), download="never")

    spectra = lp.er.electron_flux_3d.load(spn.day("1998-02-01")).to_xarray()

    assert spectra.dims == ("time", "energy_bin", "look")
    assert spectra.shape == (2, 15, 88)
    assert str(spectra.time.values[1]) == "1998-02-01T00:01:42.000000000"
    assert spectra.values[0, 2, 0] == pytest.approx(102.0)
    assert np.isnan(spectra.values[1, 3:]).all()  # the second spectrum is incomplete
    assert spectra.coords["theta"].values[1] == pytest.approx(-77.75)
    assert spectra.coords["phi"].values[0, 0, 0] == pytest.approx(450.45)  # not wrapped
    assert spectra.coords["bx_despun"].values[0, 0] == pytest.approx(8.061378)


def test_spectrograms_average_the_3d_flux_over_look_directions(tmp_path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    lp = spn.LunarProspector(store=_store_with_day(tmp_path), download="never")
    time = spn.day("1998-02-01")

    result = spn.stack(
        lp.er.electron_flux.spectrogram(time), lp.er.electron_flux_3d.spectrogram(time)
    ).plot()

    assert [axis.get_ylabel() for axis in result.axes[:2]] == ["energy [eV]", "energy [eV]"]
    assert lp.er.electron_flux_3d.spectrogram(time).data.values[0, 2] == pytest.approx(102.0)


def test_days_outside_the_mission_or_without_files_are_gaps(tmp_path) -> None:
    lp = spn.LunarProspector(store=spn.Store(tmp_path / "store"), download="never")

    empty = lp.mag.magnetic_field.load(spn.day("1997-12-01"))
    online = spn.LunarProspector(store=spn.Store(tmp_path / "s2"), download="missing")
    with pytest.raises(spn.DatasetNotFoundError, match="1998-01-16 to 1999-07-29"):
        # Outside the mission nothing is fetched, not even the energy table.
        online.er.electron_flux.load(spn.day("1997-12-01"), missing="error")
    with pytest.warns(UserWarning, match="download='never'"):
        lp.mag.magnetic_field.load(spn.day("1998-02-01"), missing="warn")

    assert empty.to_xarray().shape == (0, 3)


class _Response(BytesIO):
    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)
        self.headers = Message()
        self.headers["Content-Length"] = str(len(payload))

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def test_tables_are_downloaded_once_and_missing_days_are_gaps(tmp_path, monkeypatch) -> None:
    urls: list[str] = []

    def fake_urlopen(url: str, timeout: float) -> _Response:
        urls.append(url)
        if url.endswith("MA980202.TAB"):
            raise HTTPError(url, 404, "Not Found", Message(), None)
        return _Response(_mag_table().encode())

    monkeypatch.setattr(lp_files, "urlopen", fake_urlopen)
    store = spn.Store(tmp_path / "store")
    endpoint = spn.LunarProspector(store=store, download="missing").mag.magnetic_field
    time = spn.period("1998-02-01", "1998-02-03")

    first = endpoint.load(time)
    endpoint.load(spn.day("1998-02-01"))

    base = "https://pds-ppi.igpp.ucla.edu/volume/LP_1201/DATA/MAG/98_02FEB/"
    assert urls == [base + "MA980201.TAB", base + "MA980202.TAB"]
    assert [path.name for path in first.files] == ["MA980201.TAB"]
    assert store.raw_files(mission="lunar_prospector", provider="pds-ppi").height == 1


def test_lunar_prospector_is_reachable_from_views_and_ids(tmp_path) -> None:
    store = _store_with_day(tmp_path)
    project = spn.Project(tmp_path / "project", store=store)
    view = project.view(time=spn.day("1998-02-01"), download="never")

    from_view = view.lunar_prospector.mag.magnetic_field.load()
    by_id = spn.load(
        "lunar_prospector.er.electron_flux", spn.day("1998-02-01"), store=store, download="never"
    )

    assert from_view.to_xarray().shape == (2, 3)
    assert by_id.to_xarray().shape == (2, 15)
    assert "## lunar_prospector / er" in spn.schema_reference_markdown()
    with pytest.raises(AttributeError, match="Did you mean"):
        _ = view.lunar_prospector.mag.field
