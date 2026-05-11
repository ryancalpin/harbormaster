from __future__ import annotations


def parse_ttl(value: str) -> int:
    """Parse '2h', '1d', '30m', '90s' → seconds. Raises ValueError on bad input."""
    units = {"h": 3600, "d": 86400, "m": 60, "s": 1}
    if value and value[-1] in units:
        try:
            return int(value[:-1]) * units[value[-1]]
        except ValueError:
            pass
    raise ValueError(f"Invalid TTL format: {value!r}. Use e.g. 1h, 8h, 24h, 30m.")
