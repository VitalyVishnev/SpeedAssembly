"""Standalone Qt viewer for the isolated Boolean fracture prototype."""

from __future__ import annotations

import argparse
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..boolean_fracture_prototype import (
    SYNTHETIC_CYLINDER_CUT_TOKEN,
    BooleanCutPrototypeResult,
    BooleanCutPrototypeSession,
    BooleanCutPrototypeSettings,
    BooleanMultiPrototypeResult,
    BooleanMultiPrototypeSession,
    BooleanMultiPrototypeSettings,
    build_synthetic_boolean_cylinder_model,
    prepare_boolean_cut_prototype,
    prepare_boolean_multi_prototype,
)
from ..canonical_loader import load_source_tree_model
from ..geometry_buffers import geometry_buffer_from_mesh
from ..fracture_service import format_manual_segment_cut_token, source_bone_segment_positions
from ..models import CanonicalTreeModel, Color4, Vector3
from ..viewport_scene import (
    ViewportBoneSegment,
    ViewportDrawCall,
    ViewportMarker,
    ViewportMeshBatch,
    ViewportScene,
    ViewportStats,
    geometry_bounds,
    geometry_triangle_count,
)
from .entry import application_icon_path, configure_windows_taskbar_identity
from .viewport import MatcapViewport


BOOLEAN_PROTOTYPE_COMMAND = "boolean-prototype"
BOOLEAN_MULTI_PROTOTYPE_COMMAND = "boolean-multi-prototype"


def build_boolean_prototype_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"XMLtoUSDAConverter.exe {BOOLEAN_PROTOTYPE_COMMAND}")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="SpeedTree Raw XML source.")
    source.add_argument(
        "--synthetic-cylinder",
        action="store_true",
        help="Use the built-in open cylinder with one manual skeleton segment.",
    )
    parser.add_argument("--cut-token", default=None, help="Joint or manual segment cut token.")
    parser.add_argument("--intensity", type=float, default=0.35)
    parser.add_argument("--chip-scale", type=float, default=0.65)
    parser.add_argument("--remesh-density", type=int, default=24)
    parser.add_argument("--max-bend-angle", type=float, default=30.0)
    parser.add_argument("--smoke-exit-ms", type=int, default=0, help=argparse.SUPPRESS)
    return parser


def build_boolean_multi_prototype_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"XMLtoUSDAConverter.exe {BOOLEAN_MULTI_PROTOTYPE_COMMAND}")
    parser.add_argument("--input", required=True, help="SpeedTree Raw XML source.")
    parser.add_argument("--auto-branches", type=int, default=5)
    parser.add_argument("--intensity", type=float, default=0.35)
    parser.add_argument("--chip-scale", type=float, default=0.65)
    parser.add_argument("--remesh-density", type=int, default=24)
    parser.add_argument("--max-bend-angle", type=float, default=30.0)
    parser.add_argument("--force-stump-piece", action="store_true")
    parser.add_argument("--separate-stems", action="store_true")
    parser.add_argument("--smoke-exit-ms", type=int, default=0, help=argparse.SUPPRESS)
    return parser


def run_boolean_prototype_cli(argv: list[str]) -> int:
    args = build_boolean_prototype_parser().parse_args(argv)
    configure_windows_taskbar_identity()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Boolean Fracture Prototype")
    app.setWindowIcon(QIcon(application_icon_path()))
    try:
        if args.synthetic_cylinder:
            model = build_synthetic_boolean_cylinder_model()
            cut_token = args.cut_token or SYNTHETIC_CYLINDER_CUT_TOKEN
            source_label = "Synthetic Open Cylinder"
        else:
            if not args.cut_token:
                raise ValueError("--cut-token is required with --input.")
            _report, model, _diagnostics = load_source_tree_model(args.input)
            cut_token = args.cut_token
            source_label = args.input
        settings = BooleanCutPrototypeSettings(
            cut_token=cut_token,
            intensity=args.intensity,
            chip_scale=args.chip_scale,
            remesh_density=args.remesh_density,
            max_bend_angle_degrees=args.max_bend_angle,
        )
        session = prepare_boolean_cut_prototype(model, settings.cut_token)
        result = session.build(settings, include_preparation_timings=True)
    except Exception as exc:
        QMessageBox.critical(None, "Boolean Fracture Prototype failed", str(exc))
        return 1

    window = BooleanPrototypeWindow(model, result, settings, source_label=source_label, session=session)
    window.show()
    if args.smoke_exit_ms > 0:
        from PySide6.QtCore import QTimer

        QTimer.singleShot(args.smoke_exit_ms, app.quit)
    return app.exec()


def run_boolean_multi_prototype_cli(argv: list[str]) -> int:
    args = build_boolean_multi_prototype_parser().parse_args(argv)
    configure_windows_taskbar_identity()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Boolean Multi-Cut Prototype")
    app.setWindowIcon(QIcon(application_icon_path()))
    settings = BooleanMultiPrototypeSettings(
        auto_branch_count=args.auto_branches,
        intensity=args.intensity,
        chip_scale=args.chip_scale,
        remesh_density=args.remesh_density,
        max_bend_angle_degrees=args.max_bend_angle,
        force_stump_piece=args.force_stump_piece,
        separate_stems=args.separate_stems,
    )
    try:
        _report, model, _diagnostics = load_source_tree_model(args.input)
        session = prepare_boolean_multi_prototype(model, settings)
        result = session.build(settings, include_preparation_timings=True)
    except Exception as exc:
        QMessageBox.critical(None, "Boolean Multi-Cut Prototype failed", str(exc))
        return 1

    window = BooleanMultiPrototypeWindow(
        model,
        result,
        settings,
        source_label=args.input,
        session=session,
    )
    window.show()
    if args.smoke_exit_ms > 0:
        from PySide6.QtCore import QTimer

        QTimer.singleShot(args.smoke_exit_ms, app.quit)
    return app.exec()


class BooleanPrototypeWindow(QMainWindow):
    def __init__(
        self,
        model: CanonicalTreeModel,
        result: BooleanCutPrototypeResult,
        settings: BooleanCutPrototypeSettings,
        *,
        source_label: str,
        session: BooleanCutPrototypeSession | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Boolean Fracture Prototype")
        self.resize(1280, 820)
        self._model = model
        self._result = result
        self._settings = settings
        self._session = session or prepare_boolean_cut_prototype(model, settings.cut_token)
        self._layers = (
            ("Original Shell", result.original_shell),
            ("Closed Solid", result.closed_solid),
            ("Cutter Surface", result.cutter_surface),
            ("Parent Stub", result.parent_result),
            ("Detached Branch", result.child_result),
        )
        self._checks: dict[str, QCheckBox] = {}

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.viewport = MatcapViewport()
        self.viewport.set_show_bones(True)
        self.viewport.set_bone_pick_requires_control(False)
        self.viewport.set_shortcut_hints(
            ("LMB: orbit", "MMB: pan", "Double LMB: focus", "F: frame all", "Wheel: zoom")
        )
        splitter.addWidget(self.viewport)
        splitter.addWidget(self._build_panel(source_label))
        splitter.setStretchFactor(0, 1)
        splitter.setSizes((900, 360))
        self.setCentralWidget(splitter)
        self._refresh_scene(frame_camera=True)

    def _build_panel(self, source_label: str) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        title = QLabel("Boolean Fracture Prototype")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title)

        form = QFormLayout()
        form.addRow("Source", QLabel(source_label))
        self._cut_token_label = QLabel(self._settings.cut_token)
        self._cut_token_label.setWordWrap(True)
        form.addRow("Cut Token", self._cut_token_label)

        manual_position = self._manual_cut_position()
        self._cut_position = QDoubleSpinBox()
        self._cut_position.setRange(0.001, 0.999)
        self._cut_position.setSingleStep(0.025)
        self._cut_position.setDecimals(3)
        self._cut_position.setValue(manual_position or 0.5)
        self._cut_position.setEnabled(manual_position is not None)
        self._cut_position.setToolTip("Position along the physical child bone, from 0 to 1.")
        form.addRow("Cut Position", self._cut_position)

        self._intensity = QDoubleSpinBox()
        self._intensity.setRange(0.0, 100.0)
        self._intensity.setSingleStep(0.05)
        self._intensity.setDecimals(3)
        self._intensity.setValue(self._settings.intensity)
        self._intensity.setToolTip("One-sided displacement depth relative to branch radius.")
        form.addRow("Intensity", self._intensity)

        self._chip_scale = QDoubleSpinBox()
        self._chip_scale.setRange(0.05, 4.0)
        self._chip_scale.setSingleStep(0.05)
        self._chip_scale.setDecimals(3)
        self._chip_scale.setValue(self._settings.chip_scale)
        self._chip_scale.setToolTip("Noise wavelength relative to branch radius.")
        form.addRow("Chip Scale", self._chip_scale)

        self._remesh_density = QSpinBox()
        self._remesh_density.setRange(4, 64)
        self._remesh_density.setValue(self._settings.remesh_density)
        self._remesh_density.setToolTip("Triangular lattice edges across the local branch diameter.")
        form.addRow("Remesh Density", self._remesh_density)

        self._max_bend_angle = QDoubleSpinBox()
        self._max_bend_angle.setRange(1.0, 180.0)
        self._max_bend_angle.setSingleStep(1.0)
        self._max_bend_angle.setDecimals(1)
        self._max_bend_angle.setSuffix(" deg")
        self._max_bend_angle.setValue(self._settings.max_bend_angle_degrees)
        self._max_bend_angle.setToolTip("Stop noise before a physical bone bend above this angle.")
        form.addRow("Max Bend Angle", self._max_bend_angle)
        layout.addLayout(form)

        self._regenerate_button = QPushButton("Regenerate")
        self._regenerate_button.clicked.connect(self._regenerate)
        layout.addWidget(self._regenerate_button)

        layer_title = QLabel("Layers")
        layer_title.setStyleSheet("font-weight: 700; margin-top: 8px;")
        layout.addWidget(layer_title)
        for name, _mesh in self._layers:
            check = QCheckBox(name)
            check.setChecked(name in {"Parent Stub", "Detached Branch"})
            check.toggled.connect(lambda _checked=False: self._refresh_scene(frame_camera=False))
            self._checks[name] = check
            layout.addWidget(check)

        layout.addWidget(QLabel("Diagnostics"))
        self._amplitude_diagnostics = QLabel()
        self._amplitude_diagnostics.setWordWrap(True)
        layout.addWidget(self._amplitude_diagnostics)
        self._stage_table = QTableWidget(0, 4)
        self._stage_table.setHorizontalHeaderLabels(("Stage", "Faces", "Boundaries", "Volume"))
        self._stage_table.setMinimumHeight(190)
        layout.addWidget(self._stage_table)

        layout.addWidget(QLabel("Stage timings"))
        self._timing_table = QTableWidget(0, 2)
        self._timing_table.setHorizontalHeaderLabels(("Stage", "ms"))
        self._timing_table.setMinimumHeight(180)
        layout.addWidget(self._timing_table)
        self._update_diagnostics()
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        scroll.setMinimumWidth(340)
        return scroll

    def _manual_cut_position(self) -> float | None:
        token = self._settings.cut_token
        if "->" not in token or "@" not in token:
            return None
        try:
            return float(token.rsplit("@", 1)[1])
        except ValueError:
            return None

    def _regenerate(self) -> None:
        cut_token = self._settings.cut_token
        if self._manual_cut_position() is not None:
            segment, _separator, _position = cut_token.rpartition("@")
            parent, child = segment.split("->", 1)
            cut_token = format_manual_segment_cut_token(parent, child, self._cut_position.value())
        settings = BooleanCutPrototypeSettings(
            cut_token=cut_token,
            intensity=self._intensity.value(),
            chip_scale=self._chip_scale.value(),
            remesh_density=self._remesh_density.value(),
            max_bend_angle_degrees=self._max_bend_angle.value(),
        )
        self._regenerate_button.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            cut_changed = settings.cut_token != self._session.cut_token
            if cut_changed:
                self._session = prepare_boolean_cut_prototype(self._model, settings.cut_token)
            result = self._session.build(settings, include_preparation_timings=cut_changed)
        except Exception as exc:
            QMessageBox.critical(self, "Boolean Fracture Prototype failed", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
            self._regenerate_button.setEnabled(True)

        self._settings = settings
        self._result = result
        self._layers = (
            ("Original Shell", result.original_shell),
            ("Closed Solid", result.closed_solid),
            ("Cutter Surface", result.cutter_surface),
            ("Parent Stub", result.parent_result),
            ("Detached Branch", result.child_result),
        )
        self._cut_token_label.setText(settings.cut_token)
        self._update_diagnostics()
        self._refresh_scene(frame_camera=True)

    def _update_diagnostics(self) -> None:
        diagnostics = self._result.diagnostics
        self._amplitude_diagnostics.setText(
            f"Amplitude: {diagnostics.effective_amplitude:.5g} / {diagnostics.requested_amplitude:.5g} requested\n"
            f"Limit: {diagnostics.amplitude_limit_reason} at {diagnostics.amplitude_limit_joint_token} "
            f"({diagnostics.amplitude_limit_distance:.5g})"
        )
        stages = diagnostics.stages
        self._stage_table.setRowCount(len(stages))
        for row, (name, diagnostics) in enumerate(stages):
            values = (
                name,
                str(diagnostics.face_count),
                str(diagnostics.boundary_count),
                "-" if diagnostics.volume is None else f"{diagnostics.volume:.7g}",
            )
            for column, value in enumerate(values):
                self._stage_table.setItem(row, column, QTableWidgetItem(value))
        self._stage_table.resizeColumnsToContents()

        timings = self._result.stage_timings
        self._timing_table.setRowCount(len(timings))
        for row, (name, seconds) in enumerate(timings):
            self._timing_table.setItem(row, 0, QTableWidgetItem(name))
            self._timing_table.setItem(row, 1, QTableWidgetItem(f"{seconds * 1000.0:.3f}"))
        self._timing_table.resizeColumnsToContents()

    def _refresh_scene(self, *, frame_camera: bool) -> None:
        batches: list[ViewportMeshBatch] = []
        draws: list[ViewportDrawCall] = []
        for index, (name, mesh) in enumerate(self._layers):
            if not self._checks[name].isChecked():
                continue
            batch_id = f"layer_{index}"
            buffer = geometry_buffer_from_mesh(mesh)
            batches.append(ViewportMeshBatch(batch_id=batch_id, name=name, mesh=buffer))
            draws.append(ViewportDrawCall(draw_id=batch_id, batch_id=batch_id))
        buffers = tuple(batch.mesh for batch in batches)
        bounds = geometry_bounds(buffers)
        triangle_count = sum(geometry_triangle_count(buffer) for buffer in buffers)
        scene = ViewportScene(
            scene_id="boolean-prototype",
            mesh_batches=tuple(batches),
            draw_calls=tuple(draws),
            bounds=bounds,
            stats=ViewportStats(
                uploaded_triangles=triangle_count,
                logical_triangles=triangle_count,
                batch_count=len(batches),
                draw_call_count=len(draws),
            ),
            bone_segments=self._bone_segments(),
            markers=(self._cut_marker(),),
        )
        self.viewport.set_scene(scene, frame_camera=frame_camera)

    def _bone_segments(self) -> tuple[ViewportBoneSegment, ...]:
        joints = {joint.name: joint for joint in self._model.skeleton}
        token = self._settings.cut_token
        child_token = token.rsplit("->", 1)[-1].split("@", 1)[0] if "->" in token else token
        child = joints.get(child_token)
        parent = joints.get(child.parent or "") if child is not None else None
        if child is None or parent is None:
            return ()
        start, end = source_bone_segment_positions(child, parent)
        return (
            ViewportBoneSegment(
                segment_id=f"{parent.name}->{child.name}",
                parent_token=parent.name,
                child_token=child.name,
                start=start,
                end=end,
                color=Color4(0.95, 0.82, 0.12, 1.0),
                selected=True,
            ),
        )

    def _cut_marker(self) -> ViewportMarker:
        return ViewportMarker(
            marker_id="boolean-cut",
            position=self._result.diagnostics.cut_origin,
            color=Color4(0.15, 1.0, 0.40, 1.0),
            radius=0.04,
            label=self._settings.cut_token,
        )

    def closeEvent(self, event) -> None:
        self._session = None
        super().closeEvent(event)


class BooleanMultiPrototypeWindow(QMainWindow):
    def __init__(
        self,
        model: CanonicalTreeModel,
        result: BooleanMultiPrototypeResult,
        settings: BooleanMultiPrototypeSettings,
        *,
        source_label: str,
        session: BooleanMultiPrototypeSession,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Boolean Multi-Cut Prototype")
        self.resize(1400, 860)
        self._model = model
        self._result = result
        self._settings = settings
        self._session = session
        self._piece_checks: dict[int, QCheckBox] = {}

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.viewport = MatcapViewport()
        self.viewport.set_show_bones(True)
        self.viewport.set_bone_pick_requires_control(False)
        self.viewport.set_shortcut_hints(
            ("LMB: orbit", "MMB: pan", "Double LMB: focus", "F: frame all", "Wheel: zoom")
        )
        splitter.addWidget(self.viewport)
        splitter.addWidget(self._build_panel(source_label))
        splitter.setStretchFactor(0, 1)
        splitter.setSizes((1020, 380))
        self.setCentralWidget(splitter)
        self._refresh_scene(frame_camera=True)

    def _build_panel(self, source_label: str) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        title = QLabel("Boolean Multi-Cut Prototype")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title)

        form = QFormLayout()
        source = QLabel(source_label)
        source.setWordWrap(True)
        form.addRow("Source", source)
        self._auto_branches = QSpinBox()
        self._auto_branches.setRange(0, 64)
        self._auto_branches.setValue(self._settings.auto_branch_count)
        form.addRow("Auto Branches", self._auto_branches)
        self._intensity = QDoubleSpinBox()
        self._intensity.setRange(0.0, 100.0)
        self._intensity.setDecimals(3)
        self._intensity.setValue(self._settings.intensity)
        form.addRow("Intensity", self._intensity)
        self._chip_scale = QDoubleSpinBox()
        self._chip_scale.setRange(0.05, 4.0)
        self._chip_scale.setDecimals(3)
        self._chip_scale.setValue(self._settings.chip_scale)
        form.addRow("Chip Scale", self._chip_scale)
        self._remesh_density = QSpinBox()
        self._remesh_density.setRange(4, 64)
        self._remesh_density.setValue(self._settings.remesh_density)
        form.addRow("Remesh Density", self._remesh_density)
        self._max_bend_angle = QDoubleSpinBox()
        self._max_bend_angle.setRange(1.0, 180.0)
        self._max_bend_angle.setSuffix(" deg")
        self._max_bend_angle.setValue(self._settings.max_bend_angle_degrees)
        form.addRow("Max Bend Angle", self._max_bend_angle)
        self._force_stump = QCheckBox()
        self._force_stump.setChecked(self._settings.force_stump_piece)
        form.addRow("Force Stump Piece", self._force_stump)
        self._separate_stems = QCheckBox()
        self._separate_stems.setChecked(self._settings.separate_stems)
        form.addRow("Separate Stems", self._separate_stems)
        self._exploded = QDoubleSpinBox()
        self._exploded.setRange(0.0, 2.0)
        self._exploded.setSingleStep(0.05)
        self._exploded.valueChanged.connect(self.viewport.set_exploded_view_strength)
        form.addRow("Exploded View", self._exploded)
        layout.addLayout(form)

        self._regenerate_button = QPushButton("Regenerate")
        self._regenerate_button.clicked.connect(self._regenerate)
        layout.addWidget(self._regenerate_button)

        layout.addWidget(QLabel("Pieces"))
        self._piece_host = QWidget()
        self._piece_layout = QVBoxLayout(self._piece_host)
        self._piece_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._piece_host)
        self._rebuild_piece_checks()

        self._summary = QLabel()
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)
        self._cut_table = QTableWidget(0, 5)
        self._cut_table.setHorizontalHeaderLabels(("Cut", "Component", "Faces", "Amplitude", "ms"))
        self._cut_table.setMinimumHeight(220)
        layout.addWidget(self._cut_table)
        self._timing_table = QTableWidget(0, 2)
        self._timing_table.setHorizontalHeaderLabels(("Stage", "ms"))
        self._timing_table.setMinimumHeight(170)
        layout.addWidget(self._timing_table)
        self._update_diagnostics()
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        scroll.setMinimumWidth(370)
        return scroll

    def _current_settings(self) -> BooleanMultiPrototypeSettings:
        return BooleanMultiPrototypeSettings(
            auto_branch_count=self._auto_branches.value(),
            intensity=self._intensity.value(),
            chip_scale=self._chip_scale.value(),
            remesh_density=self._remesh_density.value(),
            max_bend_angle_degrees=self._max_bend_angle.value(),
            force_stump_piece=self._force_stump.isChecked(),
            separate_stems=self._separate_stems.isChecked(),
        )

    def _regenerate(self) -> None:
        settings = self._current_settings()
        plan_changed = (
            settings.auto_branch_count != self._settings.auto_branch_count
            or settings.force_stump_piece != self._settings.force_stump_piece
            or settings.separate_stems != self._settings.separate_stems
        )
        self._regenerate_button.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if plan_changed:
                self._session = prepare_boolean_multi_prototype(
                    self._model,
                    settings,
                    previous_session=self._session,
                )
            result = self._session.build(settings, include_preparation_timings=plan_changed)
        except Exception as exc:
            QMessageBox.critical(self, "Boolean Multi-Cut Prototype failed", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
            self._regenerate_button.setEnabled(True)

        self._settings = settings
        self._result = result
        if plan_changed:
            self._rebuild_piece_checks()
        self._update_diagnostics()
        self._refresh_scene(frame_camera=plan_changed)

    def _rebuild_piece_checks(self) -> None:
        while self._piece_layout.count():
            item = self._piece_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._piece_checks.clear()
        for piece in self._result.pieces:
            label = f"{piece.index:02d}  {piece.cut_token or 'Root'}"
            check = QCheckBox(label)
            check.setChecked(True)
            check.toggled.connect(lambda _checked=False: self._refresh_scene(frame_camera=False))
            self._piece_checks[piece.index] = check
            self._piece_layout.addWidget(check)

    def _update_diagnostics(self) -> None:
        self._summary.setText(
            f"Pieces: {len(self._result.pieces)}   Cuts: {len(self._result.cuts)}   "
            f"Mesh parts: {sum(len(piece.meshes) for piece in self._result.pieces)}"
        )
        self._cut_table.setRowCount(len(self._result.cuts))
        for row, (cut_site, result) in enumerate(zip(self._result.cut_sites, self._result.cuts)):
            diagnostics = result.diagnostics
            values = (
                cut_site.joint_token,
                str(diagnostics.selected_component_index),
                str(diagnostics.source_face_count),
                f"{diagnostics.effective_amplitude:.5g}/{diagnostics.requested_amplitude:.5g}",
                f"{sum(seconds for _name, seconds in result.stage_timings) * 1000.0:.3f}",
            )
            for column, value in enumerate(values):
                self._cut_table.setItem(row, column, QTableWidgetItem(value))
        self._cut_table.resizeColumnsToContents()

        self._timing_table.setRowCount(len(self._result.stage_timings))
        for row, (name, seconds) in enumerate(self._result.stage_timings):
            self._timing_table.setItem(row, 0, QTableWidgetItem(name))
            self._timing_table.setItem(row, 1, QTableWidgetItem(f"{seconds * 1000.0:.3f}"))
        self._timing_table.resizeColumnsToContents()

    def _refresh_scene(self, *, frame_camera: bool) -> None:
        centers = {piece.index: _multi_piece_center(piece.meshes) for piece in self._result.pieces}
        global_center = _average_point(tuple(centers.values()))
        directions = {index: _explode_direction(center, global_center) for index, center in centers.items()}
        batches: list[ViewportMeshBatch] = []
        draws: list[ViewportDrawCall] = []
        for piece in self._result.pieces:
            if not self._piece_checks[piece.index].isChecked():
                continue
            for mesh_index, mesh in enumerate(piece.meshes):
                batch_id = f"piece_{piece.index}_{mesh_index}"
                buffer = geometry_buffer_from_mesh(mesh)
                batches.append(ViewportMeshBatch(batch_id=batch_id, name=piece.name, mesh=buffer, color=piece.color))
                draws.append(
                    ViewportDrawCall(
                        draw_id=batch_id,
                        batch_id=batch_id,
                        tint=piece.color,
                        explode_direction=directions[piece.index],
                    )
                )
        buffers = tuple(batch.mesh for batch in batches)
        triangle_count = sum(geometry_triangle_count(buffer) for buffer in buffers)
        scene = ViewportScene(
            scene_id="boolean-multi-prototype",
            mesh_batches=tuple(batches),
            draw_calls=tuple(draws),
            bounds=geometry_bounds(buffers),
            stats=ViewportStats(
                uploaded_triangles=triangle_count,
                logical_triangles=triangle_count,
                batch_count=len(batches),
                draw_call_count=len(draws),
            ),
            bone_segments=self._bone_segments(),
            markers=tuple(
                ViewportMarker(
                    marker_id=f"boolean-cut-{index}",
                    position=result.diagnostics.cut_origin,
                    color=Color4(0.15, 1.0, 0.40, 1.0),
                    radius=0.04,
                    label=cut.joint_token,
                )
                for index, (cut, result) in enumerate(zip(self._result.cut_sites, self._result.cuts))
            ),
        )
        self.viewport.set_scene(scene, frame_camera=frame_camera)

    def _bone_segments(self) -> tuple[ViewportBoneSegment, ...]:
        joints = {joint.name: joint for joint in self._model.skeleton}
        segments = []
        for cut in self._result.cut_sites:
            child = joints.get(cut.child_joint_token or cut.joint_token)
            parent = joints.get(child.parent or "") if child is not None else None
            if child is None or parent is None:
                continue
            start, end = source_bone_segment_positions(child, parent)
            segments.append(
                ViewportBoneSegment(
                    segment_id=f"{parent.name}->{child.name}",
                    parent_token=parent.name,
                    child_token=child.name,
                    start=start,
                    end=end,
                    color=Color4(0.95, 0.82, 0.12, 1.0),
                    selected=True,
                )
            )
        return tuple(segments)

    def closeEvent(self, event) -> None:
        self._session = None
        super().closeEvent(event)


def _multi_piece_center(meshes) -> Vector3:
    points = tuple(point for mesh in meshes for point in mesh.points)
    return _average_point(points)


def _average_point(points: tuple[Vector3, ...]) -> Vector3:
    if not points:
        return Vector3(0.0, 0.0, 0.0)
    scale = 1.0 / len(points)
    return Vector3(
        sum(point.x for point in points) * scale,
        sum(point.y for point in points) * scale,
        sum(point.z for point in points) * scale,
    )


def _explode_direction(center: Vector3, global_center: Vector3) -> Vector3:
    x = center.x - global_center.x
    y = center.y - global_center.y
    z = center.z - global_center.z
    length = (x * x + y * y + z * z) ** 0.5
    return Vector3(0.0, 0.0, 0.0) if length <= 1e-9 else Vector3(x / length, y / length, z / length)
