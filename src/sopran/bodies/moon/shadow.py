from __future__ import annotations

from typing import Any

import numpy as np

from sopran.maps.raster import RasterLayer

from .sza import sza_layer_from_parameters


def legacy_shadowmap_filename(sza: float | int | str) -> str:
    return f"is_shadow_{sza}deg_0.tif"


def compute_shadow_layer(endpoint: Any, plan: Any) -> RasterLayer:
    parameters = dict(plan.parameters)
    method = str(parameters.get("method", "sza_threshold"))
    if method != "sza_threshold":
        raise NotImplementedError("Moon.shadow.compute currently supports method='sza_threshold'")
    threshold = float(parameters.get("threshold_deg", 90.0))
    sza = sza_layer_from_parameters(
        parameters,
        body=endpoint.body.name,
        metadata=plan.to_metadata()["parameters"],
    )
    values = np.where(np.isnan(sza.values), np.nan, (sza.values > threshold).astype(float))
    return RasterLayer(
        values,
        lon=sza.lon,
        lat=sza.lat,
        product="shadow",
        variable="shadow",
        source="computed.sza_threshold",
        units="fraction",
        body=endpoint.body.name,
        metadata={
            **plan.to_metadata()["parameters"],
            "method": method,
            "threshold_deg": threshold,
            "sza": sza.spec.to_metadata(),
            "legacy_shadowmap_pattern": legacy_shadowmap_filename("{sza}"),
        },
    )
