"""Proxy mesh preview dialog.

Layer: UI.

This is a lightweight GPU 3D viewport for the same mesh object that export uses.
"""

from __future__ import annotations

import math
from array import array
from queue import Empty, Queue
import threading
import time

import numpy as np

from PySide6.QtCore import QPoint, Qt, QSignalBlocker, QTimer
from PySide6.QtGui import QMatrix4x4, QSurfaceFormat, QVector3D
from PySide6.QtOpenGL import QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram, QOpenGLVertexArrayObject
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
)

from ..models import GeometryBuffer, Vector3
from ..proxy_mesh_service import (
    DEFAULT_PROXY_POLYCOUNT,
    PROXY_METHOD_DENSITY_FIELD,
    ProxyMeshResult,
    ProxyMeshSettings,
    ProxyMeshJobResult,
)


GL_COLOR_BUFFER_BIT = 0x00004000
GL_DEPTH_BUFFER_BIT = 0x00000100
GL_DEPTH_TEST = 0x0B71
GL_BLEND = 0x0BE2
GL_FLOAT = 0x1406
GL_LINES = 0x0001
GL_ONE_MINUS_SRC_ALPHA = 0x0303
GL_SRC_ALPHA = 0x0302
GL_TRIANGLES = 0x0004
PROCESS_PREVIEW_STATUS_SECONDS = 10.0


class ProxyPreviewDialog(QDialog):
    def __init__(
        self,
        *,
        settings: ProxyMeshSettings,
        start_preview,
        run_preview_locally,
        drain_queue,
        close_queue,
        use_local_preview: bool = False,
        preview_mesh: GeometryBuffer | None = None,
        initial_proxy: ProxyMeshResult | None = None,
        report_preview_error=None,
        on_preview_ready=None,
        on_preview_closed=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._start_preview = start_preview
        self._run_preview_locally = run_preview_locally
        self._drain_queue = drain_queue
        self._close_queue = close_queue
        self._report_preview_error = report_preview_error or (lambda message: None)
        self._use_local_preview = use_local_preview
        self._preview_mesh = preview_mesh
        self._current_proxy: ProxyMeshResult | None = initial_proxy
        self._on_preview_ready = on_preview_ready or (lambda proxy: None)
        self._on_preview_closed = on_preview_closed or (lambda settings, proxy: None)
        self._process = None
        self._queue = None
        self._cancel_event = None
        self._local_queue: Queue[ProxyMeshJobResult] | None = None
        self._local_thread: threading.Thread | None = None
        self._started_at = 0.0
        self._fallback_started = False
        self._process_retry_count = 0
        self._preview_error_retry_count = 0
        self._result_received = False
        self._error_traceback: str | None = None
        self.setWindowTitle("Proxy Mesh Preview")
        self.resize(1040, 720)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(100)
        self._poll_timer.timeout.connect(self._poll_worker)

        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.viewport = ProxyViewport(self)
        layout.addWidget(self.viewport, 0, 0)
        if initial_proxy is not None:
            self.viewport.set_mesh(initial_proxy.mesh)

        settings_panel = QFrame(self)
        settings_panel.setObjectName("PanelCard")
        settings_panel.setFixedWidth(260)
        settings_layout = QVBoxLayout(settings_panel)
        settings_layout.setContentsMargins(14, 14, 14, 14)
        settings_layout.setSpacing(8)

        title = QLabel("Proxy Mesh", settings_panel)
        title.setStyleSheet("font-weight: 700;")
        settings_layout.addWidget(title)

        self.method_combo = QComboBox(settings_panel)
        self.method_combo.addItem("Density Field", PROXY_METHOD_DENSITY_FIELD)
        self.method_combo.setCurrentIndex(self.method_combo.findData(settings.method))
        settings_layout.addWidget(QLabel("Method", settings_panel))
        settings_layout.addWidget(self.method_combo)

        self.polycount_slider, self.polycount_spin = _build_int_slider_row(
            settings_panel,
            minimum=6,
            maximum=500_000,
            value=int(settings.final_polycount or DEFAULT_PROXY_POLYCOUNT),
            step=100,
        )
        self.polycount_spin.setValue(int(settings.final_polycount or DEFAULT_PROXY_POLYCOUNT))
        settings_layout.addWidget(QLabel("Final Polycount", settings_panel))
        settings_layout.addLayout(_slider_row(self.polycount_slider, self.polycount_spin))

        self.inflation_slider, self.inflation_spin = _build_float_slider_row(
            settings_panel,
            minimum=0.1,
            maximum=5.0,
            value=float(settings.bounds_inflation),
            step=0.01,
            scale=100,
        )
        settings_layout.addWidget(QLabel("Bounds Inflation", settings_panel))
        settings_layout.addLayout(_slider_row(self.inflation_slider, self.inflation_spin))

        self.density_resolution_slider, self.density_resolution_spin = _build_int_slider_row(
            settings_panel,
            minimum=2,
            maximum=128,
            value=int(settings.density_resolution),
            step=1,
        )
        settings_layout.addWidget(QLabel("Density Resolution", settings_panel))
        settings_layout.addLayout(_slider_row(self.density_resolution_slider, self.density_resolution_spin))

        self.base_priority_slider, self.base_priority_spin = _build_float_slider_row(
            settings_panel,
            minimum=0.0,
            maximum=1.0,
            value=float(settings.base_mesh_priority),
            step=0.01,
            scale=100,
        )
        settings_layout.addWidget(QLabel("Base Mesh Priority", settings_panel))
        settings_layout.addLayout(_slider_row(self.base_priority_slider, self.base_priority_spin))

        self.status_label = QLabel("", settings_panel)
        self.status_label.setWordWrap(True)
        settings_layout.addWidget(self.status_label)
        settings_layout.addStretch(1)
        if initial_proxy is not None:
            self.status_label.setText(
                f"{initial_proxy.mesh.face_count} polygons / {initial_proxy.mesh.point_count} points"
            )

        layout.addWidget(settings_panel, 0, 1)
        layout.setColumnStretch(0, 1)

        self.method_combo.currentIndexChanged.connect(lambda _index: self.regenerate())
        self.polycount_slider.sliderReleased.connect(self.regenerate)
        self.polycount_spin.editingFinished.connect(self.regenerate)
        self.inflation_slider.sliderReleased.connect(self.regenerate)
        self.inflation_spin.editingFinished.connect(self.regenerate)
        self.density_resolution_slider.sliderReleased.connect(self.regenerate)
        self.density_resolution_spin.editingFinished.connect(self.regenerate)
        self.base_priority_slider.sliderReleased.connect(self.regenerate)
        self.base_priority_spin.editingFinished.connect(self.regenerate)
        QTimer.singleShot(0, self.regenerate)

    @property
    def current_proxy(self) -> ProxyMeshResult | None:
        return self._current_proxy

    def settings(self) -> ProxyMeshSettings:
        return ProxyMeshSettings(
            method=str(self.method_combo.currentData() or PROXY_METHOD_DENSITY_FIELD),
            final_polycount=int(self.polycount_spin.value()),
            bounds_inflation=float(self.inflation_spin.value()),
            density_resolution=int(self.density_resolution_spin.value()),
            base_mesh_priority=float(self.base_priority_spin.value()),
        )

    def regenerate(self) -> None:
        settings = self.settings()
        self._close_worker()
        if self._preview_mesh is not None:
            self._set_current_proxy(ProxyMeshResult(
                mesh=self._preview_mesh,
                settings=settings,
                method="viewport_cube",
                source_instance_count=0,
                included_base_mesh=False,
            ))
            self.status_label.setText(
                f"Viewport cube preview: {self._preview_mesh.face_count} polygons / "
                f"{self._preview_mesh.point_count} points"
            )
            return
        self.status_label.setText("Updating..." if self._current_proxy is not None else "Generating...")
        self._started_at = time.monotonic()
        self._fallback_started = False
        self._process_retry_count = 0
        self._preview_error_retry_count = 0
        if self._use_local_preview:
            self._start_local_preview("Generating locally...")
            self._poll_timer.start()
            return
        self._start_process_preview(settings, status="")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._close_worker()
        self._on_preview_closed(self.settings(), self._current_proxy)
        super().closeEvent(event)

    def _poll_worker(self) -> None:
        keep_polling = False
        local_queue = self._local_queue
        if local_queue is not None:
            while True:
                try:
                    result = local_queue.get_nowait()
                except Empty:
                    break
                keep_polling = True
                self._result_received = True
                if self._handle_worker_result(result):
                    return
                break
        if self._local_thread is not None and self._local_thread.is_alive():
            keep_polling = True
        if self._queue is not None:
            for event_name, payload in self._drain_queue(self._queue):
                keep_polling = True
                if event_name == "error_traceback":
                    self._error_traceback = str(payload)
                elif event_name == "result":
                    self._result_received = True
                    if self._handle_worker_result(payload):
                        return
        if self._process is not None and self._process.is_alive():
            keep_polling = True
            if not self._fallback_started and time.monotonic() - self._started_at >= PROCESS_PREVIEW_STATUS_SECONDS:
                self._fallback_started = True
                self.status_label.setText("Generating in isolated worker process...")
        elif self._process is not None and not self._result_received:
            keep_polling = self._handle_worker_crash()
        if not keep_polling:
            self._poll_timer.stop()

    def _handle_worker_result(self, result) -> bool:
        self._poll_timer.stop()
        error_traceback = self._error_traceback
        if result.error_message:
            message = result.error_message
            if error_traceback:
                message = f"{message}\n\n{error_traceback}"
            self._report_preview_error(message)
            if self._preview_error_retry_count < 1 and _is_retryable_preview_error(message):
                self._preview_error_retry_count += 1
                self._close_process_handles()
                self._start_process_preview(
                    self.settings(),
                    status="Proxy preview worker returned a transient error. Retrying in a fresh process...",
                )
                return True
            self._close_worker()
            self.status_label.setText(message)
            return False
        self._close_worker()
        if result.proxy is None:
            self.status_label.setText("Proxy Mesh worker finished without a preview mesh.")
            return False
        self._set_current_proxy(result.proxy)
        self.status_label.setText(f"{result.proxy.mesh.face_count} polygons / {result.proxy.mesh.point_count} points")
        return False

    def _set_current_proxy(self, proxy: ProxyMeshResult) -> None:
        had_mesh = self.viewport.has_mesh()
        self._current_proxy = proxy
        self.viewport.set_mesh(proxy.mesh, frame_camera=not had_mesh)
        self._on_preview_ready(proxy)

    def _handle_worker_crash(self) -> bool:
        exit_code = self._process.exitcode if self._process is not None else None
        if self._process_retry_count < 1:
            self._process_retry_count += 1
            self._report_preview_error(f"Proxy Mesh worker crashed once (exit code {exit_code}).")
            self._close_process_handles()
            self._start_process_preview(
                self.settings(),
                status=f"Proxy worker crashed once (exit code {exit_code}). Retrying in a fresh process...",
            )
            return True
        message = f"Proxy Mesh worker process crashed unexpectedly (exit code {exit_code})"
        if self._error_traceback:
            message = f"{message}\n\n{self._error_traceback}"
        self._report_preview_error(message)
        self._close_worker()
        self.status_label.setText(message)
        return False

    def _close_worker(self) -> None:
        self._poll_timer.stop()
        if self._cancel_event is not None:
            try:
                self._cancel_event.set()
            except Exception:
                pass
        if self._process is not None and self._process.is_alive():
            try:
                self._process.join(timeout=0.1)
            except Exception:
                pass
            if self._process.is_alive():
                try:
                    self._process.terminate()
                    self._process.join(timeout=0.1)
                except Exception:
                    pass
        self._close_queue(self._queue)
        self._process = None
        self._queue = None
        self._cancel_event = None
        self._local_queue = None
        self._local_thread = None
        self._fallback_started = False
        self._result_received = False
        self._error_traceback = None
        self._preview_error_retry_count = 0

    def _close_process_handles(self) -> None:
        if self._cancel_event is not None:
            try:
                self._cancel_event.set()
            except Exception:
                pass
        if self._process is not None and self._process.is_alive():
            try:
                self._process.terminate()
                self._process.join(timeout=0.1)
            except Exception:
                pass
        self._close_queue(self._queue)
        self._process = None
        self._queue = None
        self._cancel_event = None
        self._result_received = False
        self._error_traceback = None

    def _start_process_preview(self, settings: ProxyMeshSettings, *, status: str) -> None:
        if status:
            self.status_label.setText(status)
        try:
            process, queue, cancel_event = self._start_preview(settings)
        except Exception as exc:
            self.status_label.setText(str(exc))
            return
        self._process = process
        self._queue = queue
        self._cancel_event = cancel_event
        self._result_received = False
        self._error_traceback = None
        self._poll_timer.start()

    def _start_local_preview(self, status: str) -> None:
        self.status_label.setText(status)
        self._local_queue = Queue()
        self._local_thread = threading.Thread(
            target=self._run_local_preview_worker,
            kwargs={"settings": self.settings(), "queue": self._local_queue},
            daemon=True,
        )
        self._local_thread.start()

    def _run_local_preview_worker(self, *, settings: ProxyMeshSettings, queue: Queue[ProxyMeshJobResult]) -> None:
        try:
            queue.put(ProxyMeshJobResult(proxy=self._run_preview_locally(settings)))
        except Exception as exc:
            queue.put(ProxyMeshJobResult(error_message=str(exc)))


def _build_int_slider_row(
    parent,
    *,
    minimum: int,
    maximum: int,
    value: int,
    step: int,
) -> tuple[QSlider, QSpinBox]:
    slider = QSlider(Qt.Orientation.Horizontal, parent)
    slider.setRange(minimum, maximum)
    slider.setSingleStep(step)
    slider.setPageStep(step * 4)
    slider.setValue(value)

    spin = QSpinBox(parent)
    spin.setRange(minimum, maximum)
    spin.setSingleStep(step)
    spin.setValue(value)
    spin.setKeyboardTracking(False)
    spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    spin.setFixedWidth(70)

    slider.valueChanged.connect(lambda raw: _sync_int_spin(spin, raw, step))
    spin.editingFinished.connect(lambda: _sync_int_slider(slider, spin.value()))
    return slider, spin


def _build_float_slider_row(
    parent,
    *,
    minimum: float,
    maximum: float,
    value: float,
    step: float,
    scale: int,
) -> tuple[QSlider, QDoubleSpinBox]:
    slider = QSlider(Qt.Orientation.Horizontal, parent)
    slider.setRange(int(round(minimum * scale)), int(round(maximum * scale)))
    slider.setSingleStep(max(1, int(round(step * scale))))
    slider.setPageStep(max(1, int(round(step * scale * 4))))
    slider.setValue(int(round(value * scale)))

    spin = QDoubleSpinBox(parent)
    spin.setRange(minimum, maximum)
    spin.setSingleStep(step)
    spin.setDecimals(2)
    spin.setValue(value)
    spin.setKeyboardTracking(False)
    spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    spin.setFixedWidth(70)

    slider.valueChanged.connect(lambda raw: _sync_float_spin(spin, raw, scale))
    spin.editingFinished.connect(lambda: _sync_float_slider(slider, spin.value(), scale))
    return slider, spin


def _slider_row(slider: QSlider, spin) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    row.addWidget(slider, 1)
    row.addWidget(spin, 0)
    return row


def _sync_int_spin(spin: QSpinBox, value: int, step: int) -> None:
    snapped = max(spin.minimum(), min(spin.maximum(), int(round(value / step) * step)))
    with QSignalBlocker(spin):
        spin.setValue(snapped)


def _sync_int_slider(slider: QSlider, value: int) -> None:
    with QSignalBlocker(slider):
        slider.setValue(value)


def _sync_float_spin(spin: QDoubleSpinBox, value: int, scale: int) -> None:
    with QSignalBlocker(spin):
        spin.setValue(value / scale)


def _sync_float_slider(slider: QSlider, value: float, scale: int) -> None:
    with QSignalBlocker(slider):
        slider.setValue(int(round(value * scale)))


def _is_retryable_preview_error(message: str) -> bool:
    deterministic_fragments = (
        "Unsupported proxy mesh method",
        "Proxy final polycount must be greater than zero",
        "Proxy bounds inflation must be greater than zero",
        "Proxy density resolution must be greater than zero",
        "Missing resolved prototype",
        "has no resolved polygon payload",
        "requires base geometry or at least one repeated part instance",
        "malformed orientation quaternion",
        "zero-length orientation quaternion",
        "zero scale component",
        "Proxy mesh generation supports exactly one input XML",
        "Proxy mesh generation requires a source XML path",
        "Proxy source resolution failed",
    )
    return not any(fragment in message for fragment in deterministic_fragments)


def build_preview_cube_mesh() -> GeometryBuffer:
    return GeometryBuffer(
        name="ViewportCubePreview",
        point_components=array(
            "f",
            (
                -0.5,
                -0.5,
                -0.5,
                0.5,
                -0.5,
                -0.5,
                0.5,
                0.5,
                -0.5,
                -0.5,
                0.5,
                -0.5,
                -0.5,
                -0.5,
                0.5,
                0.5,
                -0.5,
                0.5,
                0.5,
                0.5,
                0.5,
                -0.5,
                0.5,
                0.5,
            ),
        ),
        face_vertex_counts=array("i", (4, 4, 4, 4, 4, 4)),
        face_vertex_indices=array(
            "i",
            (
                0,
                3,
                2,
                1,
                4,
                5,
                6,
                7,
                0,
                1,
                5,
                4,
                1,
                2,
                6,
                5,
                2,
                3,
                7,
                6,
                3,
                0,
                4,
                7,
            ),
        ),
    )


class ProxyViewport(QOpenGLWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(480, 360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        format_ = QSurfaceFormat()
        format_.setDepthBufferSize(24)
        format_.setSamples(4)
        self.setFormat(format_)
        self._mesh: GeometryBuffer | None = None
        self._target = Vector3(0.0, 0.0, 0.0)
        self._radius = 1.0
        self._distance = 3.0
        self._yaw = math.radians(38.0)
        self._pitch = math.radians(18.0)
        self._last_mouse: QPoint | None = None
        self._program: QOpenGLShaderProgram | None = None
        self._vertex_buffer: QOpenGLBuffer | None = None
        self._vao: QOpenGLVertexArrayObject | None = None
        self._grid_program: QOpenGLShaderProgram | None = None
        self._grid_buffer: QOpenGLBuffer | None = None
        self._grid_vao: QOpenGLVertexArrayObject | None = None
        self._vertex_count = 0
        self._grid_vertex_count = 0
        self._mesh_dirty = False
        self._grid_dirty = False
        self._ground_y = 0.0

    def has_mesh(self) -> bool:
        return self._mesh is not None and self._mesh.point_count > 0

    def set_mesh(self, mesh: GeometryBuffer | None, *, frame_camera: bool = True) -> None:
        self._mesh = mesh
        self._update_mesh_metrics(frame_camera=frame_camera)
        self._mesh_dirty = True
        self._grid_dirty = True
        if self.isValid():
            self.makeCurrent()
            try:
                self._upload_mesh()
                self._upload_grid()
            finally:
                self.doneCurrent()
        self.update()

    def initializeGL(self) -> None:  # type: ignore[override]
        functions = self.context().functions()
        functions.initializeOpenGLFunctions()
        functions.glClearColor(0.0, 0.0, 0.0, 1.0)
        functions.glEnable(GL_DEPTH_TEST)
        self._program = _build_matcap_program()
        self._grid_program = _build_grid_program()
        self._vao = QOpenGLVertexArrayObject(self)
        self._vao.create()
        self._vertex_buffer = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self._vertex_buffer.create()
        self._grid_vao = QOpenGLVertexArrayObject(self)
        self._grid_vao.create()
        self._grid_buffer = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self._grid_buffer.create()
        self._mesh_dirty = True
        self._grid_dirty = True
        self._upload_mesh()
        self._upload_grid()

    def resizeGL(self, width: int, height: int) -> None:  # type: ignore[override]
        self.context().functions().glViewport(0, 0, max(1, width), max(1, height))

    def paintGL(self) -> None:  # type: ignore[override]
        functions = self.context().functions()
        functions.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        if self._mesh_dirty:
            self._upload_mesh()
        if self._grid_dirty:
            self._upload_grid()
        view = self._view_matrix()
        projection = self._projection_matrix()
        self._draw_grid(functions, projection * view)
        if self._program is None or self._vao is None or self._vertex_count <= 0:
            return
        self._program.bind()
        self._program.setUniformValue("mvp", projection * view)
        self._program.setUniformValue("normalMatrix", view.normalMatrix())
        self._vao.bind()
        functions.glDrawArrays(GL_TRIANGLES, 0, self._vertex_count)
        self._vao.release()
        self._program.release()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._last_mouse = event.position().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._last_mouse is not None and event.buttons() & Qt.MouseButton.LeftButton:
            current = event.position().toPoint()
            delta = current - self._last_mouse
            self._last_mouse = current
            self._yaw -= delta.x() * 0.01
            self._pitch = max(math.radians(-82.0), min(math.radians(82.0), self._pitch + delta.y() * 0.01))
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        self._last_mouse = None
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        steps = event.angleDelta().y() / 120.0
        self._distance = max(self._radius * 0.35, self._distance * (0.88 ** steps))
        self.update()
        event.accept()

    def _update_mesh_metrics(self, *, frame_camera: bool) -> None:
        if self._mesh is None or self._mesh.point_count == 0:
            if frame_camera:
                self._target = Vector3(0.0, 0.0, 0.0)
                self._radius = 1.0
                self._distance = 3.0
            self._ground_y = 0.0
            return
        points = list(_points(self._mesh))
        min_x = min(point.x for point in points)
        min_y = min(point.y for point in points)
        min_z = min(point.z for point in points)
        max_x = max(point.x for point in points)
        max_y = max(point.y for point in points)
        max_z = max(point.z for point in points)
        self._ground_y = float(min_y)
        self._radius = max(
            0.001,
            math.sqrt((max_x - min_x) ** 2 + (max_y - min_y) ** 2 + (max_z - min_z) ** 2) * 0.5,
        )
        if frame_camera:
            self._target = Vector3((min_x + max_x) * 0.5, (min_y + max_y) * 0.5, (min_z + max_z) * 0.5)
            self._distance = self._radius * 3.0

    def _upload_mesh(self) -> None:
        if self._program is None or self._vertex_buffer is None or self._vao is None:
            return
        vertices = _build_viewport_vertices(self._mesh)
        self._vertex_count = int(len(vertices) // 6)
        self._vao.bind()
        self._vertex_buffer.bind()
        self._vertex_buffer.allocate(vertices.tobytes(), vertices.nbytes)
        self._program.bind()
        stride = 6 * 4
        position_location = self._program.attributeLocation("position")
        normal_location = self._program.attributeLocation("normal")
        self._program.enableAttributeArray(position_location)
        self._program.setAttributeBuffer(position_location, GL_FLOAT, 0, 3, stride)
        self._program.enableAttributeArray(normal_location)
        self._program.setAttributeBuffer(normal_location, GL_FLOAT, 12, 3, stride)
        self._program.release()
        self._vertex_buffer.release()
        self._vao.release()
        self._mesh_dirty = False

    def _upload_grid(self) -> None:
        if self._grid_program is None or self._grid_buffer is None or self._grid_vao is None:
            return
        vertices = _build_grid_vertices(self._target, self._radius, self._ground_y)
        self._grid_vertex_count = int(len(vertices) // 4)
        self._grid_vao.bind()
        self._grid_buffer.bind()
        self._grid_buffer.allocate(vertices.tobytes(), vertices.nbytes)
        self._grid_program.bind()
        stride = 4 * 4
        position_location = self._grid_program.attributeLocation("position")
        alpha_location = self._grid_program.attributeLocation("alpha")
        self._grid_program.enableAttributeArray(position_location)
        self._grid_program.setAttributeBuffer(position_location, GL_FLOAT, 0, 3, stride)
        self._grid_program.enableAttributeArray(alpha_location)
        self._grid_program.setAttributeBuffer(alpha_location, GL_FLOAT, 12, 1, stride)
        self._grid_program.release()
        self._grid_buffer.release()
        self._grid_vao.release()
        self._grid_dirty = False

    def _draw_grid(self, functions, mvp: QMatrix4x4) -> None:
        if self._grid_program is None or self._grid_vao is None or self._grid_vertex_count <= 0:
            return
        functions.glEnable(GL_BLEND)
        functions.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        functions.glLineWidth(1.35)
        self._grid_program.bind()
        self._grid_program.setUniformValue("mvp", mvp)
        self._grid_vao.bind()
        functions.glDrawArrays(GL_LINES, 0, self._grid_vertex_count)
        self._grid_vao.release()
        self._grid_program.release()
        functions.glDisable(GL_BLEND)

    def _view_matrix(self) -> QMatrix4x4:
        eye = self._camera_eye()
        matrix = QMatrix4x4()
        matrix.lookAt(
            QVector3D(float(eye.x), float(eye.y), float(eye.z)),
            QVector3D(float(self._target.x), float(self._target.y), float(self._target.z)),
            QVector3D(0.0, 1.0, 0.0),
        )
        return matrix

    def _projection_matrix(self) -> QMatrix4x4:
        matrix = QMatrix4x4()
        aspect = max(0.001, self.width() / max(1, self.height()))
        matrix.perspective(42.0, aspect, max(0.001, self._radius * 0.01), max(10.0, self._radius * 20.0))
        return matrix

    def _camera_eye(self) -> Vector3:
        cos_pitch = math.cos(self._pitch)
        offset = Vector3(
            self._distance * math.sin(self._yaw) * cos_pitch,
            self._distance * math.sin(self._pitch),
            self._distance * math.cos(self._yaw) * cos_pitch,
        )
        return Vector3(self._target.x + offset.x, self._target.y + offset.y, self._target.z + offset.z)


def _build_viewport_vertices(mesh: GeometryBuffer | None) -> np.ndarray:
    if mesh is None or mesh.point_count == 0:
        return np.asarray([], dtype=np.float32)
    points = list(_points(mesh))
    vertices: list[float] = []
    offset = 0
    for count in mesh.face_vertex_counts:
        indices = [int(mesh.face_vertex_indices[offset + index]) for index in range(count)]
        offset += count
        if count < 3:
            continue
        for index in range(1, count - 1):
            triangle = (points[indices[0]], points[indices[index]], points[indices[index + 1]])
            normal = _face_normal(triangle)
            for point in triangle:
                vertices.extend((point.x, point.y, point.z, normal.x, normal.y, normal.z))
    return np.asarray(vertices, dtype=np.float32)


def _build_grid_vertices(target: Vector3, radius: float, ground_y: float) -> np.ndarray:
    step = 1.0
    half_extent = int(max(8, min(80, math.ceil(radius * 5.0))))
    origin_x = math.floor(target.x)
    origin_z = math.floor(target.z)
    y = float(ground_y) - max(0.002, radius * 0.001)
    fade_radius = max(1.0, float(half_extent))
    vertices: list[float] = []

    def alpha_at(x: float, z: float) -> float:
        distance = math.sqrt((x - target.x) ** 2 + (z - target.z) ** 2)
        fade = max(0.0, 1.0 - distance / fade_radius)
        return 0.28 * fade * fade

    def add_vertex(x: float, z: float) -> None:
        vertices.extend((x, y, z, alpha_at(x, z)))

    for ix in range(-half_extent, half_extent + 1):
        x = origin_x + ix * step
        for iz in range(-half_extent, half_extent):
            z0 = origin_z + iz * step
            z1 = z0 + step
            add_vertex(x, z0)
            add_vertex(x, z1)

    for iz in range(-half_extent, half_extent + 1):
        z = origin_z + iz * step
        for ix in range(-half_extent, half_extent):
            x0 = origin_x + ix * step
            x1 = x0 + step
            add_vertex(x0, z)
            add_vertex(x1, z)

    return np.asarray(vertices, dtype=np.float32)


def _build_matcap_program() -> QOpenGLShaderProgram:
    program = QOpenGLShaderProgram()
    if not program.addShaderFromSourceCode(
        QOpenGLShader.ShaderTypeBit.Vertex,
        """
        attribute vec3 position;
        attribute vec3 normal;
        uniform mat4 mvp;
        uniform mat3 normalMatrix;
        varying vec3 viewNormal;
        void main() {
            viewNormal = normalize(normalMatrix * normal);
            gl_Position = mvp * vec4(position, 1.0);
        }
        """,
    ):
        raise RuntimeError(program.log())
    if not program.addShaderFromSourceCode(
        QOpenGLShader.ShaderTypeBit.Fragment,
        """
        varying vec3 viewNormal;
        void main() {
            vec3 n = normalize(viewNormal);
            vec2 uv = n.xy * 0.5 + 0.5;
            float facing = clamp(n.z * 0.5 + 0.5, 0.0, 1.0);
            float upper = smoothstep(0.15, 0.95, uv.y);
            float side = 1.0 - smoothstep(0.45, 1.0, abs(uv.x - 0.5) * 2.0);
            float rim = pow(1.0 - abs(n.z), 2.35);
            vec3 shadow = vec3(0.10, 0.105, 0.11);
            vec3 mid = vec3(0.55, 0.55, 0.51);
            vec3 high = vec3(0.96, 0.94, 0.82);
            vec3 color = mix(shadow, mid, facing);
            color = mix(color, high, upper * side * 0.74);
            color += rim * vec3(0.15, 0.16, 0.18);
            color = pow(color, vec3(0.88));
            gl_FragColor = vec4(color, 1.0);
        }
        """,
    ):
        raise RuntimeError(program.log())
    if not program.link():
        raise RuntimeError(program.log())
    return program


def _build_grid_program() -> QOpenGLShaderProgram:
    program = QOpenGLShaderProgram()
    if not program.addShaderFromSourceCode(
        QOpenGLShader.ShaderTypeBit.Vertex,
        """
        attribute vec3 position;
        attribute float alpha;
        uniform mat4 mvp;
        varying float gridAlpha;
        void main() {
            gridAlpha = alpha;
            gl_Position = mvp * vec4(position, 1.0);
        }
        """,
    ):
        raise RuntimeError(program.log())
    if not program.addShaderFromSourceCode(
        QOpenGLShader.ShaderTypeBit.Fragment,
        """
        varying float gridAlpha;
        void main() {
            gl_FragColor = vec4(0.48, 0.56, 0.58, gridAlpha);
        }
        """,
    ):
        raise RuntimeError(program.log())
    if not program.link():
        raise RuntimeError(program.log())
    return program


def _points(mesh: GeometryBuffer):
    for index in range(0, len(mesh.point_components), 3):
        yield Vector3(mesh.point_components[index], mesh.point_components[index + 1], mesh.point_components[index + 2])


def _face_normal(points: tuple[Vector3, Vector3, Vector3]) -> Vector3:
    a, b, c = points
    ux = b.x - a.x
    uy = b.y - a.y
    uz = b.z - a.z
    vx = c.x - a.x
    vy = c.y - a.y
    vz = c.z - a.z
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length <= 0.0:
        return Vector3(0.0, 0.0, 1.0)
    return Vector3(nx / length, ny / length, nz / length)
