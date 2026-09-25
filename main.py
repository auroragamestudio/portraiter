"""Petit éditeur d'image : redimensionnement de canvas + masque circulaire en fondu.

Dépendances : PySide6, Pillow, numpy (voir requirements.txt).
Lancement :   python main.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from image_ops import (
    FillMode,
    canvas_offset,
    downscale_for_preview,
    render_composite,
    resize_canvas,
)

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".webp"}

CENTER_MIN = -50000
CENTER_MAX = 50000


def _dropped_image_path(event) -> Path | None:
    if not event.mimeData().hasUrls():
        return None
    path = Path(event.mimeData().urls()[0].toLocalFile())
    return path if path.suffix.lower() in SUPPORTED_EXTENSIONS else None


def _widen(spin: QDoubleSpinBox | QSpinBox) -> None:
    spin.setMinimumWidth(70)
    spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


def pil_to_qpixmap(image: Image.Image) -> QPixmap:
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimage = QImage(data, rgba.width, rgba.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimage.copy())


class ImageView(QLabel):
    mask_center_dragged = Signal(float, float)
    view_resized = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(300, 300)
        self.setStyleSheet("background-color: #3a3a3a; color: #cccccc;")
        self.setText("Glissez-déposez une image ici\nou utilisez « Charger une image… »")
        self._dragging_mask = False

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.view_resized.emit()

    def _to_pixmap_coords(self, pos) -> tuple[float, float] | None:
        pixmap = self.pixmap()
        if pixmap is None or pixmap.isNull():
            return None
        offset_x = (self.width() - pixmap.width()) / 2
        offset_y = (self.height() - pixmap.height()) / 2
        x = pos.x() - offset_x
        y = pos.y() - offset_y
        if 0 <= x <= pixmap.width() and 0 <= y <= pixmap.height():
            return x, y
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            coords = self._to_pixmap_coords(event.position())
            if coords is not None:
                self._dragging_mask = True
                self.mask_center_dragged.emit(*coords)
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging_mask:
            coords = self._to_pixmap_coords(event.position())
            if coords is not None:
                self.mask_center_dragged.emit(*coords)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging_mask = False
        super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Éditeur d'image — canvas & masque circulaire")
        self.resize(1100, 700)

        self.original_image: Image.Image | None = None
        self._preview_base: Image.Image | None = None
        self._preview_scale: float = 1.0
        self._display_scale: float = 1.0

        self.canvas_background = QColor(255, 255, 255, 255)

        self.setAcceptDrops(True)
        self._build_ui()

    # ---------------------------------------------------------- Clavier
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self.original_image is not None and event.modifiers() & Qt.KeyboardModifier.KeypadModifier:
            if event.key() == Qt.Key.Key_Plus:
                self.mask_feather_spin.stepUp()
                return
            if event.key() == Qt.Key.Key_Minus:
                self.mask_feather_spin.stepDown()
                return
        super().keyPressEvent(event)

    # -------------------------------------------------------- Drag & drop
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if _dropped_image_path(event) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if _dropped_image_path(event) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        path = _dropped_image_path(event)
        if path is None:
            event.ignore()
            return
        event.acceptProposedAction()
        self.load_image(str(path))

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        central = QWidget()
        outer_layout = QHBoxLayout(central)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.image_view = ImageView()
        self.image_view.mask_center_dragged.connect(self._on_mask_dragged)
        self.image_view.view_resized.connect(self._refresh_view)

        scroll = QScrollArea()
        scroll.setWidget(self.image_view)
        scroll.setWidgetResizable(True)
        splitter.addWidget(scroll)

        panel = QVBoxLayout()
        panel.addWidget(self._build_load_group())
        panel.addWidget(self._build_background_group())
        panel.addWidget(self._build_canvas_group())
        panel.addWidget(self._build_mask_group())
        panel.addStretch()
        panel.addWidget(self._build_save_group())

        panel_widget = QWidget()
        panel_widget.setLayout(panel)
        panel_widget.setMinimumWidth(260)
        splitter.addWidget(panel_widget)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([800, 320])

        outer_layout.addWidget(splitter)
        self.setCentralWidget(central)

    def _build_load_group(self) -> QGroupBox:
        box = QGroupBox("Image")
        layout = QVBoxLayout(box)

        load_btn = QPushButton("Charger une image…")
        load_btn.clicked.connect(self._on_load_clicked)
        layout.addWidget(load_btn)

        reset_btn = QPushButton("Réinitialiser")
        reset_btn.clicked.connect(self.reset_to_original)
        layout.addWidget(reset_btn)

        self.dimensions_label = QLabel("Aucune image chargée")
        layout.addWidget(self.dimensions_label)
        return box

    def _build_background_group(self) -> QGroupBox:
        box = QGroupBox("Fond")
        layout = QVBoxLayout(box)

        self.bg_swatch = QLabel()
        self.bg_swatch.setFixedHeight(24)
        self._update_bg_swatch()
        layout.addWidget(self.bg_swatch)

        bg_btn = QPushButton("Couleur de fond…")
        bg_btn.clicked.connect(self._choose_background_color)
        layout.addWidget(bg_btn)
        return box

    def _build_canvas_group(self) -> QGroupBox:
        box = QGroupBox("Redimensionner le canvas")
        layout = QVBoxLayout(box)

        # --- Dimensions cibles ---
        size_row = QHBoxLayout()
        self.canvas_width_percent = QDoubleSpinBox()
        self.canvas_width_percent.setRange(1.0, 1000.0)
        self.canvas_width_percent.setDecimals(0)
        self.canvas_width_percent.setSingleStep(5.0)
        self.canvas_width_percent.setValue(100.0)
        self.canvas_width_percent.setSuffix(" %")
        _widen(self.canvas_width_percent)

        self.canvas_height_percent = QDoubleSpinBox()
        self.canvas_height_percent.setRange(1.0, 1000.0)
        self.canvas_height_percent.setDecimals(0)
        self.canvas_height_percent.setSingleStep(5.0)
        self.canvas_height_percent.setValue(100.0)
        self.canvas_height_percent.setSuffix(" %")
        _widen(self.canvas_height_percent)

        size_row.addWidget(QLabel("Largeur"))
        size_row.addWidget(self.canvas_width_percent)
        size_row.addWidget(QLabel("Hauteur"))
        size_row.addWidget(self.canvas_height_percent)
        layout.addLayout(size_row)

        self.canvas_preview_label = QLabel("—")
        layout.addWidget(self.canvas_preview_label)

        # --- Mode de remplissage ---
        fill_row = QHBoxLayout()
        fill_row.addWidget(QLabel("Remplissage"))
        self.fill_mode_combo = QComboBox()
        self.fill_mode_combo.addItem("Couleur unie", FillMode.COLOR)
        self.fill_mode_combo.addItem("Flou étendu", FillMode.BLUR_EXTEND)
        self.fill_mode_combo.currentIndexChanged.connect(self._on_fill_mode_changed)
        fill_row.addWidget(self.fill_mode_combo, 1)
        layout.addLayout(fill_row)

        # --- Rayon du flou (n'agit qu'en mode « Flou étendu ») ---
        blur_row = QHBoxLayout()
        self.blur_radius_label = QLabel("Rayon flou")
        self.blur_radius_spin = QSpinBox()
        self.blur_radius_spin.setRange(1, 500)
        self.blur_radius_spin.setValue(50)
        self.blur_radius_spin.setSingleStep(5)
        self.blur_radius_spin.setSuffix(" px")
        _widen(self.blur_radius_spin)
        self.blur_radius_spin.valueChanged.connect(self._on_blur_radius_changed)
        blur_row.addWidget(self.blur_radius_label)
        blur_row.addWidget(self.blur_radius_spin)
        layout.addLayout(blur_row)

        # État initial : spinbox désactivé si mode = couleur unie.
        self._on_fill_mode_changed()

        self.canvas_width_percent.valueChanged.connect(self._on_canvas_percent_changed)
        self.canvas_height_percent.valueChanged.connect(self._on_canvas_percent_changed)
        return box

    def _build_mask_group(self) -> QGroupBox:
        box = QGroupBox("Masque circulaire (fondu)")
        layout = QVBoxLayout(box)

        radius_row = QHBoxLayout()
        self.mask_radius_spin = QSpinBox()
        self.mask_radius_spin.setRange(1, 20000)
        self.mask_radius_spin.setValue(150)
        _widen(self.mask_radius_spin)
        radius_row.addWidget(QLabel("Rayon"))
        radius_row.addWidget(self.mask_radius_spin)
        layout.addLayout(radius_row)

        feather_row = QHBoxLayout()
        self.mask_feather_spin = QSpinBox()
        self.mask_feather_spin.setRange(0, 2000)
        self.mask_feather_spin.setValue(40)
        self.mask_feather_spin.setSingleStep(5)
        _widen(self.mask_feather_spin)
        feather_row.addWidget(QLabel("Fondu (px)"))
        feather_row.addWidget(self.mask_feather_spin)
        layout.addLayout(feather_row)

        center_row = QHBoxLayout()
        self.mask_center_x_spin = QSpinBox()
        self.mask_center_x_spin.setRange(CENTER_MIN, CENTER_MAX)
        _widen(self.mask_center_x_spin)
        self.mask_center_y_spin = QSpinBox()
        self.mask_center_y_spin.setRange(CENTER_MIN, CENTER_MAX)
        _widen(self.mask_center_y_spin)
        center_row.addWidget(QLabel("Centre X"))
        center_row.addWidget(self.mask_center_x_spin)
        center_row.addWidget(QLabel("Centre Y"))
        center_row.addWidget(self.mask_center_y_spin)
        layout.addLayout(center_row)

        for spin in (
            self.mask_radius_spin,
            self.mask_feather_spin,
            self.mask_center_x_spin,
            self.mask_center_y_spin,
        ):
            spin.valueChanged.connect(self._on_mask_param_changed)

        center_btn = QPushButton("Centrer sur l'image")
        center_btn.clicked.connect(self._center_mask)
        layout.addWidget(center_btn)
        return box

    def _build_save_group(self) -> QGroupBox:
        box = QGroupBox("Export")
        layout = QVBoxLayout(box)
        save_btn = QPushButton("Enregistrer l'image sous…")
        save_btn.clicked.connect(self._on_save_clicked)
        layout.addWidget(save_btn)
        return box

    # ------------------------------------------------------------- Actions
    def _on_load_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Charger une image", "", "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tiff *.webp)"
        )
        if path:
            self.load_image(path)

    def load_image(self, path: str) -> None:
        try:
            image = Image.open(path)
            image.load()
        except Exception as exc:
            QMessageBox.critical(self, "Erreur", f"Impossible de charger l'image :\n{exc}")
            return

        self.original_image = image.convert("RGBA")
        self._preview_base, self._preview_scale = downscale_for_preview(self.original_image)
        self._sync_controls_to_image()
        self._refresh_view()

    def reset_to_original(self) -> None:
        if self.original_image is None:
            return
        self._sync_controls_to_image()
        self._refresh_view()

    def _sync_controls_to_image(self) -> None:
        assert self.original_image is not None
        w, h = self.original_image.size

        self.canvas_width_percent.blockSignals(True)
        self.canvas_height_percent.blockSignals(True)
        self.canvas_width_percent.setValue(100.0)
        self.canvas_height_percent.setValue(100.0)
        self.canvas_width_percent.blockSignals(False)
        self.canvas_height_percent.blockSignals(False)
        self._update_canvas_preview()

        self.mask_center_x_spin.blockSignals(True)
        self.mask_center_y_spin.blockSignals(True)
        self.mask_radius_spin.blockSignals(True)
        self.mask_center_x_spin.setValue(w // 2)
        self.mask_center_y_spin.setValue(h // 2)
        self.mask_radius_spin.setValue(min(w, h) // 3 or 1)
        self.mask_center_x_spin.blockSignals(False)
        self.mask_center_y_spin.blockSignals(False)
        self.mask_radius_spin.blockSignals(False)

    def _target_canvas_size(self) -> tuple[int, int]:
        assert self.original_image is not None
        base_w, base_h = self.original_image.size
        new_w = max(1, round(base_w * self.canvas_width_percent.value() / 100))
        new_h = max(1, round(base_h * self.canvas_height_percent.value() / 100))
        return new_w, new_h

    def _update_canvas_preview(self) -> None:
        if self.original_image is None:
            self.canvas_preview_label.setText("—")
            return
        w, h = self._target_canvas_size()
        self.canvas_preview_label.setText(f"Nouveau canvas : {w} × {h} px")

    def _current_fill_mode(self) -> FillMode:
        data = self.fill_mode_combo.currentData()
        return data if isinstance(data, FillMode) else FillMode.COLOR

    def _on_fill_mode_changed(self) -> None:
        """Active/désactive le spinbox du rayon selon le mode, puis
        rafraîchit l'aperçu."""
        is_blur = self._current_fill_mode() == FillMode.BLUR_EXTEND
        self.blur_radius_spin.setEnabled(is_blur)
        self.blur_radius_label.setEnabled(is_blur)
        if self.original_image is not None:
            self._refresh_view()

    def _on_blur_radius_changed(self) -> None:
        if self.original_image is None:
            return
        if self._current_fill_mode() != FillMode.BLUR_EXTEND:
            return
        self._refresh_view()

    def _on_canvas_percent_changed(self) -> None:
        self._update_canvas_preview()
        self._refresh_view()

    def _choose_background_color(self) -> None:
        color = QColorDialog.getColor(
            self.canvas_background,
            self,
            "Couleur de fond",
            QColorDialog.ColorDialogOption.ShowAlphaChannel,
        )
        if color.isValid():
            self.canvas_background = color
            self._update_bg_swatch()
            self._refresh_view()

    def _update_bg_swatch(self) -> None:
        c = self.canvas_background
        self.bg_swatch.setStyleSheet(
            f"background-color: rgba({c.red()},{c.green()},{c.blue()},{c.alpha()});"
            "border: 1px solid #666;"
        )

    def _center_mask(self) -> None:
        if self.original_image is None:
            return
        w, h = self.original_image.size
        self.mask_center_x_spin.setValue(w // 2)
        self.mask_center_y_spin.setValue(h // 2)

    def _on_mask_param_changed(self) -> None:
        if self.original_image is None:
            return
        self._refresh_view()

    def _on_mask_dragged(self, x: float, y: float) -> None:
        if self.original_image is None or self._display_scale <= 0:
            return

        img_w, img_h = self.original_image.size
        canvas_w, canvas_h = self._target_canvas_size()
        offset_x, offset_y = canvas_offset((img_w, img_h), (canvas_w, canvas_h))

        x_image = x / self._display_scale - offset_x
        y_image = y / self._display_scale - offset_y

        self.mask_center_x_spin.blockSignals(True)
        self.mask_center_y_spin.blockSignals(True)
        self.mask_center_x_spin.setValue(round(x_image))
        self.mask_center_y_spin.setValue(round(y_image))
        self.mask_center_x_spin.blockSignals(False)
        self.mask_center_y_spin.blockSignals(False)
        self._on_mask_param_changed()

    # ---- Rendu -------------------------------------------------------------

    def _refresh_view(self) -> None:
        if self.original_image is None or self._preview_base is None:
            return

        img_w, img_h = self.original_image.size
        canvas_w_full, canvas_h_full = self._target_canvas_size()

        avail_w = max(1, self.image_view.width())
        avail_h = max(1, self.image_view.height())

        display_scale = min(
            1.0,
            avail_w / canvas_w_full,
            avail_h / canvas_h_full,
        )

        # Source à l'échelle de travail + facteur associé.
        extra = display_scale / self._preview_scale if self._preview_scale > 0 else 1.0
        if extra >= 1.0:
            source = self._preview_base
            work_scale = self._preview_scale
        else:
            new_w = max(1, round(self._preview_base.width * extra))
            new_h = max(1, round(self._preview_base.height * extra))
            source = self._preview_base.resize((new_w, new_h), Image.Resampling.BILINEAR)
            work_scale = display_scale

        canvas_w_work = max(1, round(canvas_w_full * work_scale))
        canvas_h_work = max(1, round(canvas_h_full * work_scale))

        bg = self.canvas_background
        background = (bg.red(), bg.green(), bg.blue(), bg.alpha())

        # Paramètres de remplissage : le rayon du flou est exprimé en px de
        # l'image pleine résolution, on le remet à l'échelle du travail.
        resized = resize_canvas(
            source,
            canvas_w_work,
            canvas_h_work,
            fill_mode=self._current_fill_mode(),
            background=background,
            blur_radius=self.blur_radius_spin.value() * work_scale,
        )

        offset_x, offset_y = canvas_offset(source.size, (canvas_w_work, canvas_h_work))
        center = (
            self.mask_center_x_spin.value() * work_scale + offset_x,
            self.mask_center_y_spin.value() * work_scale + offset_y,
        )

        composite = render_composite(
            resized,
            background=background,
            radius=self.mask_radius_spin.value() * work_scale,
            feather=self.mask_feather_spin.value() * work_scale,
            center=center,
        )

        self._display_scale = work_scale
        self.image_view.setPixmap(pil_to_qpixmap(composite))

        self.dimensions_label.setText(
            f"Dimensions export : {canvas_w_full} × {canvas_h_full} px"
        )

    def _build_full_composite(self) -> Image.Image:
        assert self.original_image is not None
        img_w, img_h = self.original_image.size
        new_w, new_h = self._target_canvas_size()
        bg = self.canvas_background
        background = (bg.red(), bg.green(), bg.blue(), bg.alpha())

        resized = resize_canvas(
            self.original_image,
            new_w,
            new_h,
            fill_mode=self._current_fill_mode(),
            background=background,
            blur_radius=self.blur_radius_spin.value(),
        )

        offset_x, offset_y = canvas_offset((img_w, img_h), (new_w, new_h))
        center = (
            self.mask_center_x_spin.value() + offset_x,
            self.mask_center_y_spin.value() + offset_y,
        )
        return render_composite(
            resized,
            background=background,
            radius=self.mask_radius_spin.value(),
            feather=self.mask_feather_spin.value(),
            center=center,
        )

    # ---- Export ------------------------------------------------------------

    def _on_save_clicked(self) -> None:
        if self.original_image is None:
            QMessageBox.information(self, "Aucune image", "Rien à enregistrer.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Enregistrer l'image sous",
            "image_modifiee.png",
            "PNG (*.png)",
        )
        if not path:
            return
        image_to_save = self._build_full_composite().convert("RGB")
        try:
            image_to_save.save(path, format="PNG")
        except Exception as exc:
            QMessageBox.critical(self, "Erreur", f"Impossible d'enregistrer l'image :\n{exc}")


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()