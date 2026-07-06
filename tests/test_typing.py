from __future__ import annotations

import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any

import sopran as spn
from sopran.core.data import SopranArray
from sopran.missions.artemis.mission import ArtemisVariableEndpoint
from sopran.missions.kaguya.mission import VariableEndpoint as KaguyaVariableEndpoint


def test_sopran_array_is_exported_for_public_api_completion() -> None:
    assert spn.SopranArray is SopranArray


def test_package_declares_inline_types_for_type_checkers() -> None:
    package_root = Path(spn.__file__).parent

    assert (package_root / "py.typed").exists()


def test_py_typed_marker_is_included_in_packaging_metadata() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert 'path = "src/sopran/py.typed"' in pyproject
    assert 'format = "wheel"' in pyproject


def test_top_level_shortcuts_have_type_checking_declarations() -> None:
    source = Path(spn.__file__).read_text(encoding="utf-8")

    assert "if TYPE_CHECKING:" in source
    assert "kaguya: Kaguya" in source
    assert "artemis: Artemis" in source
    assert "moon: Moon" in source


def test_primary_mission_tree_attributes_have_source_annotations() -> None:
    root = Path(spn.__file__).parent
    kaguya_source = (root / "missions" / "kaguya" / "mission.py").read_text(
        encoding="utf-8"
    )
    artemis_source = (root / "missions" / "artemis" / "mission.py").read_text(
        encoding="utf-8"
    )

    assert "self.esa1: PaceInstrument" in kaguya_source
    assert "self.energy_flux: VariableEndpoint" in kaguya_source
    assert "self.counts: VariableEndpoint" in kaguya_source
    assert "self.p1: ArtemisProbe" in artemis_source
    assert "self.ion_energy_flux: ArtemisVariableEndpoint" in artemis_source


def test_main_plotting_api_return_annotations_are_concrete() -> None:
    targets = (
        SopranArray.plot,
        SopranArray.spectrogram,
        SopranArray.quicklook,
        KaguyaVariableEndpoint.plot,
        KaguyaVariableEndpoint.spectrogram,
        ArtemisVariableEndpoint.spectrogram,
    )

    for target in targets:
        assert _return_annotation(target) not in {
            inspect.Signature.empty,
            Any,
            "Any",
            "typing.Any",
        }


def _return_annotation(target: Callable[..., object]) -> object:
    return inspect.signature(target).return_annotation
