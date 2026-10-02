"""Release version and portable identity of the running build.

Packaging embeds build_identity.json here; source previews require neither Git
nor the developer's local build_info.json.
"""

from __future__ import annotations

import json
import sys
from importlib.resources import files

__version__ = "0.5.0-beta"


def application_title() -> str:
    suffix = "" if getattr(sys, "frozen", False) else " DEV"
    return f"SpeedAssembly v{__version__}{suffix}"


def build_identity() -> dict[str, object]:
    if not getattr(sys, "frozen", False):
        return {
            "version": __version__,
            "build_mode": "dev",
            "git_commit": None,
            "git_dirty": None,
            "built_at": None,
        }
    identity = json.loads(files("xml_to_usda").joinpath("build_identity.json").read_text(encoding="utf-8"))
    if identity["version"] != __version__ or identity["build_mode"] != "package":
        raise RuntimeError("Embedded build identity does not match this application.")
    return identity


def build_details() -> str:
    identity = build_identity()
    if identity["build_mode"] == "dev":
        return "Source preview"
    dirty = " (local changes)" if identity["git_dirty"] else ""
    return f"Commit: {identity['git_commit']}{dirty}\nBuilt: {identity['built_at']}"
