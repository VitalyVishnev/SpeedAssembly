from __future__ import annotations

from xml_to_usda.naming import build_prototype_identities, make_stable_prim_name


def test_make_stable_prim_name_normalizes_unicode_and_symbols() -> None:
    assert make_stable_prim_name("  Twig-Ω/01  ") == "Twig_01"
    assert make_stable_prim_name("123 spruce") == "_123_spruce"


def test_make_stable_prim_name_uses_fallback_when_name_is_empty_after_sanitization() -> None:
    assert make_stable_prim_name("ΩΩΩ", fallback="Fallback") == "Fallback"


def test_build_prototype_identities_adds_deterministic_collision_suffixes() -> None:
    identities = build_prototype_identities(
        ["Mesh_1", "Mesh_2", "Mesh_3"],
        display_names=["Twig_01", "Twig_01", "Twig_01"],
    )

    assert tuple(identity.source_key for identity in identities) == ("Mesh_1", "Mesh_2", "Mesh_3")
    assert tuple(identity.prim_name for identity in identities) == ("Twig_01", "Twig_01_2", "Twig_01_3")
