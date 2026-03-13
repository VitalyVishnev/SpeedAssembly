from __future__ import annotations

import re

from .models import PrototypeIdentity


_NON_ASCII_SAFE = re.compile(r"[^A-Za-z0-9_]+")


def make_stable_prim_name(raw_name: str, fallback: str = "Prototype") -> str:
    ascii_name = (raw_name or "").encode("ascii", "ignore").decode("ascii")
    ascii_name = _NON_ASCII_SAFE.sub("_", ascii_name).strip("_")
    if not ascii_name:
        ascii_name = fallback
    if ascii_name[0].isdigit():
        ascii_name = f"_{ascii_name}"
    return ascii_name


def build_prototype_identities(keys: list[str] | tuple[str, ...]) -> tuple[PrototypeIdentity, ...]:
    seen: dict[str, int] = {}
    identities: list[PrototypeIdentity] = []
    for key in keys:
        base = make_stable_prim_name(key, fallback="Prototype")
        count = seen.get(base, 0) + 1
        seen[base] = count
        prim_name = base if count == 1 else f"{base}_{count}"
        identities.append(PrototypeIdentity(source_key=key, prim_name=prim_name))
    return tuple(identities)
