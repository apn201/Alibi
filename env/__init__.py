"""Environmental data (Copernicus Marine): fetch into a read-through cache, sample, and model the sea's effect on a ship."""
from .cache import EnvCache, get_cache

__all__ = ["EnvCache", "get_cache"]
