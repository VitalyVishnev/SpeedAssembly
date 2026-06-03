import importlib
import sys
from contextlib import contextmanager


def test_importing_package_does_not_load_worker_services():
    """GUI/worker entrypoints must not import unrelated heavy worker services."""
    with _fresh_xml_to_usda_imports():
        package = importlib.import_module("xml_to_usda")

        assert package.__name__ == "xml_to_usda"
        assert "xml_to_usda.cli" not in sys.modules
        assert "xml_to_usda.proxy_mesh_service" not in sys.modules
        assert "xml_to_usda.proxy_mesh_worker_subprocess" not in sys.modules


def test_importing_qt_entry_does_not_load_proxy_mesh_service():
    """The packaged GUI shell must route helper modes without importing proxy generation."""
    with _fresh_xml_to_usda_imports():
        entry = importlib.import_module("xml_to_usda.qt_ui.entry")

        assert entry.__name__ == "xml_to_usda.qt_ui.entry"
        assert "xml_to_usda.proxy_mesh_service" not in sys.modules
        assert "xml_to_usda.proxy_mesh_worker_subprocess" not in sys.modules


@contextmanager
def _fresh_xml_to_usda_imports():
    previous = {
        name: module
        for name, module in sys.modules.items()
        if name == "xml_to_usda" or name.startswith("xml_to_usda.")
    }
    for name in previous:
        del sys.modules[name]
    try:
        yield
    finally:
        for name in tuple(sys.modules):
            if name == "xml_to_usda" or name.startswith("xml_to_usda."):
                del sys.modules[name]
        sys.modules.update(previous)
