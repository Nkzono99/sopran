from __future__ import annotations

from .models import SurfaceSource

#: Google Drive folder of the Tsunakawa et al. (2023) supplement that holds the ver. 2 bundle.
TSUNAKAWA_SVM_V02_FOLDER = (
    "https://drive.google.com/drive/folders/108u0-lGucZ5yXKA-rVksGPGR8sj0SF8U"
)

SURFACE_SOURCES = {
    "dem": (
        "lro.lola.dem_118m",
        "lro.lola.sldem2015_59m",
        "lro.lola.dem",
        "kaguya.tc.dem",
    ),
    "svm": (
        "kaguya.lmag.svm_tsunakawa2015",
        "svm_tsunakawa2015",
        "kaguya.lism.svm",
        "ravat2020.l1",
    ),
    "shadow": ("computed.terrain_ray", "legacy.shadowmap_sza"),
    "illumination": (),
    "sza": ("computed.spice.sza",),
}

SURFACE_SOURCE_INFO = {
    "lro.lola.dem_118m": SurfaceSource(
        source_id="lro.lola.dem_118m",
        product="dem",
        provider="usgs_astrogeology",
        filename="Lunar_LRO_LOLA_Global_LDEM_118m_Mar2014.tif",
        description="LRO LOLA global lunar DEM, 256 pixels per degree, 118 m at equator.",
        url=(
            "https://planetarymaps.usgs.gov/mosaic/"
            "Lunar_LRO_LOLA_Global_LDEM_118m_Mar2014.tif"
        ),
        landing_page="https://astrogeology.usgs.gov/search/map/moon_lro_lola_dem_118m",
        size="8 GB",
        version="2014-03-11",
        scale=0.5,
        offset=0.0,
    ),
    "lro.lola.sldem2015_59m": SurfaceSource(
        source_id="lro.lola.sldem2015_59m",
        product="dem",
        provider="usgs_astrogeology",
        filename="Lunar_LRO_LOLAKaguya_DEMmerge_60N60S_512ppd.tif",
        description="SLDEM2015 LOLA + SELENE/Kaguya TC merged DEM, 512 ppd, 60S-60N.",
        url=(
            "https://planetarymaps.usgs.gov/mosaic/LolaKaguya_Topo/"
            "Lunar_LRO_LOLAKaguya_DEMmerge_60N60S_512ppd.tif"
        ),
        landing_page=(
            "https://astrogeology.usgs.gov/search/map/"
            "moon_lro_lola_selene_kaguya_tc_dem_merge_60n60s_59m"
        ),
        size="22 GB",
        version="2015",
    ),
    "kaguya.lmag.svm_tsunakawa2015": SurfaceSource(
        source_id="kaguya.lmag.svm_tsunakawa2015",
        product="svm",
        provider="kaguya_lmag_tsunakawa",
        filename="LunarSVM_000_02_v02.dat",
        description=(
            "Tsunakawa et al. lunar magnetic anomaly surface vector map, ver. 2 "
            "(Tsunakawa et al. 2023, revised from Tsunakawa et al. 2015): Be, Bn, Br, Bt "
            "and their standard errors on a 0.2 degree grid at R = 1737.4 km."
        ),
        url=(
            "https://drive.usercontent.google.com/download"
            "?id=1cWK1JlLpYeXUd6TI6drRXaq_QNf1H0n1&export=download&confirm=t"
        ),
        landing_page=TSUNAKAWA_SVM_V02_FOLDER,
        original_url="http://www.geo.titech.ac.jp/lab/tsunakawa/Kaguya_LMAG",
        size="165 MB",
        version="v02 (2023)",
        sha256="577b248d37b73876815e13a1d531a500bdb81ae4389fc4f87c5991be960cc2de",
        manual_note=(
            "The original Tokyo Tech site is offline. SOPRAN downloads the copy that the "
            "LMAG team distributes as a supplement of Tsunakawa et al. (2023), "
            "doi:10.20637/00049167. The same folder holds the spherical harmonic "
            "coefficients (LunarSVM_SHC_v02.dat) and the Fortran forward code."
        ),
        license_note=(
            "No license is stated by the distributor. SOPRAN links to and downloads the "
            "author-distributed file and does not redistribute it; cite Tsunakawa et al. "
            "(2015, 2023) when you use it."
        ),
    ),
    "ravat2020.l1": SurfaceSource(
        source_id="ravat2020.l1",
        product="svm",
        provider="uknowledge_uky",
        filename="Ravatetal_JGR2020_LunarL1MagneticModelFields_LPgrad.dat",
        description=(
            "Ravat, Purucker & Olsen (2020) L1-norm lunar crustal field model from Lunar "
            "Prospector and SELENE/Kaguya along-track gradients: Br, Btheta, Bphi and total "
            "field on a 0.1 degree grid at the lunar ellipsoid surface (CC0)."
        ),
        landing_page="https://doi.org/10.13023/9wpe-tt68",
        size="88 MB",
        version="2020",
        manual_note=(
            "The University of Kentucky repository answers scripts with a browser check, so "
            "SOPRAN cannot download it. Download the main .dat file in a web browser from the "
            "landing page and place it under the store raw/moon/svm directory or pass path=."
        ),
    ),
}

SOURCE_ALIASES = {
    "lro.lola.dem": "lro.lola.dem_118m",
    "kaguya.tc.dem": "lro.lola.sldem2015_59m",
    "svm_tsunakawa2015": "kaguya.lmag.svm_tsunakawa2015",
    "tsunakawa2015": "kaguya.lmag.svm_tsunakawa2015",
    "kaguya.lism.svm": "kaguya.lmag.svm_tsunakawa2015",
    "ravat2020": "ravat2020.l1",
}


def canonical_source_id(source: str | None) -> str:
    if source is None:
        raise ValueError("source is required")
    source_id = str(source)
    return SOURCE_ALIASES.get(source_id, source_id)


def surface_source_info(source: str | None) -> SurfaceSource:
    source_id = canonical_source_id(source)
    info = SURFACE_SOURCE_INFO.get(source_id)
    if info is None:
        raise ValueError(f"Unknown Moon surface source: {source!r}")
    return info
