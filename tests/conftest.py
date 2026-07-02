from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _close_matplotlib_figures():
    yield
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return
    plt.close("all")
