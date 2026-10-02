from __future__ import annotations


def normalize_prototype_source_key(raw_key: str) -> str:
    key = raw_key.strip()
    if not key:
        return ""
    lower_key = key.lower()
    for prefix in ("mesh_", "meshid:", "mesh_id:"):
        if lower_key.startswith(prefix) and key[len(prefix):].strip().isdigit():
            return f"Mesh_{int(key[len(prefix):].strip())}"
    if key.isdigit():
        return f"Mesh_{int(key)}"
    return key
