from __future__ import annotations

from pathlib import Path

from xml_to_usda import canonical_loader


BIG_SPRUCE = (
    Path(__file__).resolve().parents[1]
    / "samples"
    / "speedtree"
    / "BigSpruce"
    / "SkeletalAssemblyTest_Spruce_Big_low.xml"
)


def test_load_source_tree_model_reuses_on_disk_cache(monkeypatch, tmp_path: Path) -> None:
    cache_root = tmp_path / "cache" / "source_models"
    monkeypatch.setattr(canonical_loader, "_source_model_cache_root", lambda: cache_root)

    first_report, first_model, first_diagnostics = canonical_loader.load_source_tree_model(str(BIG_SPRUCE))
    cache_files = list(cache_root.glob("*.pkl"))
    assert len(cache_files) == 1
    assert cache_files[0].stat().st_size > 0

    def fail_read_source_xml(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("source XML should not be reread when the cache is warm")

    monkeypatch.setattr(canonical_loader, "read_source_xml", fail_read_source_xml)

    second_report, second_model, second_diagnostics = canonical_loader.load_source_tree_model(str(BIG_SPRUCE))

    assert second_report == first_report
    assert second_model == first_model
    assert second_diagnostics == first_diagnostics
