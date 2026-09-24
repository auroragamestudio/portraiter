"""Petit éditeur d'image : redimensionnement de canvas + masque circulaire en fondu.

Dépendances : PySide6, Pillow, numpy (voir requirements.txt).
Lancement :   python main.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QDragEnterEvent, QDragMoveEvent, QDropEvent, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
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

from image_ops import apply_circular_fade_mask, resize_canvas

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".webp"}


def _dropped_image_path(event) -> Path | None:
    """Retourne le chemin de fichier si le drag contient une image supportée,
    sinon None."""
    if not event.mimeData().hasUrls():
        return None
    path = Path(event.mimeData().urls()[0].toLocalFile())
    return path if path.suffix.lower() in SUPPORTED_EXTENSIONS else None


def _widen(spin: QDoubleSpinBox | QSpinBox) -> None:
    """Donne aux champs numériques une largeur minimale confortable et les
    laisse grandir avec le panneau (au lieu de rester à leur largeur mini)."""
    spin.setMinimumWidth(70)
    spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


def pil_to_qpixmap(image: Image.Image) -> QPixmap:
    """Convertit une image PIL (peu importe le mode) en QPixmap affichable."""
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimage = QImage(data, rgba.width, rgba.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimage.copy())  # copy() : QImage ne possède pas `data`


class ImageView(QLabel):
    """Affiche l'image courante. Le drag-and-drop est géré par la fenêtre
    principale (voir MainWindow) : un widget enfant sans acceptDrops laisse
    l'événement remonter automatiquement jusqu'à elle."""

    def __init__(self) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(300, 300)
        self.setStyleSheet("background-color: #3a3a3a; color: #cccccc;")
        self.setText("Glissez-déposez une image ici\nou utilisez « Charger une image… »")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Éditeur d'image — canvas & masque circulaire")
        self.resize(1100, 700)

        self.original_image: Image.Image | None = None
        self.working_image: Image.Image | None = None
        self.canvas_background = QColor(255, 255, 255, 255)  # blanc opaque par défaut

        self.setAcceptDrops(True)
        self._build_ui()

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

        # Un QSplitter (plutôt qu'un simple layout à largeur fixe) permet à
        # l'utilisateur de faire glisser la séparation pour élargir le
        # panneau de droite.
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- Zone d'affichage (avec ascenseurs pour les grandes images) ---
        self.image_view = ImageView()
        scroll = QScrollArea()
        scroll.setWidget(self.image_view)
        # widgetResizable=True : le label occupe tout l'espace visible quand
        # il n'y a pas (encore) d'image, ce qui donne une vraie zone de
        # drop sur toute la surface plutôt que seulement 300x300 px.
        scroll.setWidgetResizable(True)
        splitter.addWidget(scroll)

        # --- Panneau de contrôle ---
        panel = QVBoxLayout()
        panel.addWidget(self._build_load_group())
        panel.addWidget(self._build_canvas_group())
        panel.addWidget(self._build_mask_group())
        panel.addStretch()
        panel.addWidget(self._build_save_group())

        panel_widget = QWidget()
        panel_widget.setLayout(panel)
        panel_widget.setMinimumWidth(240)
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

    def _build_canvas_group(self) -> QGroupBox:
        box = QGroupBox("Redimensionner le canvas")
        layout = QVBoxLayout(box)

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
        self.canvas_width_percent.valueChanged.connect(self._update_canvas_preview)
        self.canvas_height_percent.valueChanged.connect(self._update_canvas_preview)

        bg_btn = QPushButton("Couleur de fond…")
        bg_btn.clicked.connect(self._choose_background_color)
        layout.addWidget(bg_btn)

        apply_btn = QPushButton("Appliquer le redimensionnement")
        apply_btn.clicked.connect(self._on_resize_canvas_clicked)
        layout.addWidget(apply_btn)
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
        _widen(self.mask_feather_spin)
        feather_row.addWidget(QLabel("Fondu (px)"))
        feather_row.addWidget(self.mask_feather_spin)
        layout.addLayout(feather_row)

        center_row = QHBoxLayout()
        self.mask_center_x_spin = QSpinBox()
        self.mask_center_x_spin.setRange(0, 20000)
        _widen(self.mask_center_x_spin)
        self.mask_center_y_spin = QSpinBox()
        self.mask_center_y_spin.setRange(0, 20000)
        _widen(self.mask_center_y_spin)
        center_row.addWidget(QLabel("Centre X"))
        center_row.addWidget(self.mask_center_x_spin)
        center_row.addWidget(QLabel("Centre Y"))
        center_row.addWidget(self.mask_center_y_spin)
        layout.addLayout(center_row)

        center_btn = QPushButton("Centrer sur l'image")
        center_btn.clicked.connect(self._center_mask)
        layout.addWidget(center_btn)

        apply_btn = QPushButton("Appliquer le masque")
        apply_btn.clicked.connect(self._on_apply_mask_clicked)
        layout.addWidget(apply_btn)
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
        except Exception as exc:  # noqa: BLE001 - toute erreur de chargement est affichée
            QMessageBox.critical(self, "Erreur", f"Impossible de charger l'image :\n{exc}")
            return

        self.original_image = image.convert("RGBA")
        self.working_image = self.original_image.copy()
        self._sync_controls_to_image()
        self._refresh_view()

    def reset_to_original(self) -> None:
        if self.original_image is None:
            return
        self.working_image = self.original_image.copy()
        self._sync_controls_to_image()
        self._refresh_view()

    def _sync_controls_to_image(self) -> None:
        assert self.working_image is not None
        w, h = self.working_image.size

        # Le pourcentage repart de 100 % (= taille de l'image tout juste
        # chargée/réinitialisée), sans déclencher l'aperçu deux fois.
        self.canvas_width_percent.blockSignals(True)
        self.canvas_height_percent.blockSignals(True)
        self.canvas_width_percent.setValue(100.0)
        self.canvas_height_percent.setValue(100.0)
        self.canvas_width_percent.blockSignals(False)
        self.canvas_height_percent.blockSignals(False)
        self._update_canvas_preview()

        self.mask_center_x_spin.setRange(0, w)
        self.mask_center_y_spin.setRange(0, h)
        self.mask_center_x_spin.setValue(w // 2)
        self.mask_center_y_spin.setValue(h // 2)
        self.mask_radius_spin.setValue(min(w, h) // 3 or 1)

    def _target_canvas_size(self) -> tuple[int, int]:
        """Taille de canvas en pixels, calculée à partir des pourcentages
        et de la taille de l'image d'origine (chargée/réinitialisée)."""
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

    def _choose_background_color(self) -> None:
        color = QColorDialog.getColor(
            self.canvas_background,
            self,
            "Couleur de fond du canvas",
            QColorDialog.ColorDialogOption.ShowAlphaChannel,
        )
        if color.isValid():
            self.canvas_background = color

    def _on_resize_canvas_clicked(self) -> None:
        if self.working_image is None:
            QMessageBox.information(self, "Aucune image", "Chargez d'abord une image.")
            return
        bg = self.canvas_background
        background = (bg.red(), bg.green(), bg.blue(), bg.alpha())
        new_w, new_h = self._target_canvas_size()
        self.working_image = resize_canvas(self.working_image, new_w, new_h, background=background)
        self.mask_center_x_spin.setRange(0, self.working_image.width)
        self.mask_center_y_spin.setRange(0, self.working_image.height)
        self._refresh_view()

    def _center_mask(self) -> None:
        if self.working_image is None:
            return
        w, h = self.working_image.size
        self.mask_center_x_spin.setValue(w // 2)
        self.mask_center_y_spin.setValue(h // 2)

    def _on_apply_mask_clicked(self) -> None:
        if self.working_image is None:
            QMessageBox.information(self, "Aucune image", "Chargez d'abord une image.")
            return
        self.working_image = apply_circular_fade_mask(
            self.working_image,
            radius=self.mask_radius_spin.value(),
            feather=self.mask_feather_spin.value(),
            center=(self.mask_center_x_spin.value(), self.mask_center_y_spin.value()),
        )
        self._refresh_view()

    def _on_save_clicked(self) -> None:
        if self.working_image is None:
            QMessageBox.information(self, "Aucune image", "Rien à enregistrer.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Enregistrer l'image sous",
            "image_modifiee.png",
            "PNG (*.png);;JPEG (*.jpg *.jpeg);;BMP (*.bmp);;TIFF (*.tiff)",
        )
        if not path:
            return
        image_to_save = self.working_image
        if Path(path).suffix.lower() in {".jpg", ".jpeg", ".bmp"}:
            # Ces formats ne supportent pas la transparence.
            image_to_save = image_to_save.convert("RGB")
        try:
            image_to_save.save(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Erreur", f"Impossible d'enregistrer l'image :\n{exc}")

    def _refresh_view(self) -> None:
        assert self.working_image is not None
        self.image_view.setPixmap(pil_to_qpixmap(self.working_image))
        w, h = self.working_image.size
        self.dimensions_label.setText(f"Dimensions actuelles : {w} × {h} px")


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
