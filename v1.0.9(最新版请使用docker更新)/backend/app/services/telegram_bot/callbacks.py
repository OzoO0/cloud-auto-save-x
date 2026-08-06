from __future__ import annotations


def cb(*parts: object) -> str:
    return ":".join([str(x) for x in parts if x is not None and str(x) != ""])


def parse_callback(data: str) -> list[str]:
    return [str(x) for x in str(data or "").split(":") if str(x) != ""]
