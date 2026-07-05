from __future__ import annotations

from .models import SurfaceSource

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
        description="Tsunakawa et al. lunar magnetic anomaly surface vector map.",
        landing_page=(
            "https://stereo-ssc.nascom.nasa.gov/instruments/software/impact/"
            "TDAS/socware/spedas_5_0/idl/projects/kaguya/map/lmag_spd_doc_list.html"
        ),
        original_url="http://www.geo.titech.ac.jp/lab/tsunakawa/Kaguya_LMAG",
        version="2015",
        manual_note=(
            "A stable public direct download URL is not registered in SOPRAN. "
            "Place the file under the store raw/moon/svm directory or pass path= explicitly."
        ),
    ),
}

SOURCE_ALIASES = {
    "lro.lola.dem": "lro.lola.dem_118m",
    "kaguya.tc.dem": "lro.lola.sldem2015_59m",
    "svm_tsunakawa2015": "kaguya.lmag.svm_tsunakawa2015",
    "tsunakawa2015": "kaguya.lmag.svm_tsunakawa2015",
    "kaguya.lism.svm": "kaguya.lmag.svm_tsunakawa2015",
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
