from sopran.core.sources import register_source
from sopran.missions.artemis.mission import Artemis

register_source("artemis", "sopran.missions.artemis.mission:Artemis.from_view")

__all__ = ["Artemis"]
