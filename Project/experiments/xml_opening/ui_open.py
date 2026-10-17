"""Time a real offscreen Qt paste through discovery and Wind worker completion.

Only worker executable selection and modal acknowledgement are instrumented.
The production process supervisor, authentication, timers and result IPC run.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
sys.path.insert(0, str(PROJECT / 'src'))


def configure(variant, cache):
    from xml_to_usda import canonical_loader, discovery_service
    if cache == 'off':
        canonical_loader._source_model_cache_path = lambda _path: None
    if variant == 'baseline':
        path = PROJECT / 'tmp/xml-opening/baseline_discovery.py'
        exec(compile(path.read_text(encoding='utf-8-sig'), str(path), 'exec'),
             discovery_service.__dict__)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--worker':
        configure(sys.argv[2], sys.argv[3])
        from xml_to_usda.cli import main as cli
        return cli(sys.argv[4:])

    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--variant', choices=('baseline', 'candidate'), required=True)
    parser.add_argument('--cache', choices=('off', 'enabled'), default='off')
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    (runtime / 'temp').mkdir(parents=True, exist_ok=True)
    os.environ['LOCALAPPDATA'] = str(runtime / 'local')
    os.environ['TMP'] = os.environ['TEMP'] = str(runtime / 'temp')
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    configure(args.variant, args.cache)
    from xml_to_usda import conversion_process
    conversion_process.resolve_worker_command = lambda command, request: [
        sys.executable, str(Path(__file__).resolve()), '--worker', args.variant,
        args.cache, command, '--request', str(request)]

    from PySide6.QtWidgets import QApplication, QMessageBox
    from xml_to_usda.qt_ui.dependencies import build_default_dependencies
    from xml_to_usda.qt_ui.persistence import UiShellState
    from xml_to_usda.qt_ui.theme import load_theme
    from xml_to_usda.qt_ui.window import MainWindow
    from xml_to_usda.settings_service import GuiSettingsSnapshot, save_gui_settings

    app = QApplication([])
    warnings = []
    QMessageBox.warning = lambda _parent, title, message, *_: warnings.append([title, message])
    # Warm only the source cache. A restored input must not start work before
    # the timed paste when repeating a run in the same private cache root.
    save_gui_settings(runtime / 'settings.json', GuiSettingsSnapshot())
    window = MainWindow(load_theme(), UiShellState(help_prompt_dismissed=True),
                        dependencies=build_default_dependencies(),
                        state_path=runtime / 'state.json',
                        operator_settings_path=runtime / 'settings.json',
                        theme_overrides_path=runtime / 'theme.json')
    window.show()
    app.processEvents()
    times = {}
    original = window._apply_source_discovery
    def applied(**kwargs):
        original(**kwargs)
        times['rows'] = time.perf_counter() - start
        times['joints'] = kwargs['skeleton_joint_count']
    window._apply_source_discovery = applied
    start = time.perf_counter()
    window.source_input.setText(str(args.input.resolve()))
    # Keep the real input handler and its discovery/Wind debounce timers.
    while time.perf_counter() - start < 240:
        app.processEvents()
        if window._current_dynamic_wind is not None and 'rows' in times:
            times['ready'] = time.perf_counter() - start
            break
        time.sleep(0.005)
    else:
        raise RuntimeError('XML/Wind opening did not finish within 240 seconds')
    times.update(variant=args.variant, cache=args.cache, input=str(args.input),
                 warnings=warnings, wind_groups=len(window._current_dynamic_wind.simulation_groups))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(times, indent=2), encoding='utf-8')
    print(json.dumps(times))
    window.close()
    app.processEvents()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
