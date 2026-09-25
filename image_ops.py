"""Fonctions de traitement d'image pures (aucune dépendance à Qt).

Séparées de l'interface graphique pour rester simples à lire, tester et
réutiliser indépendamment du lancement de l'application.
"""
from __future__ import annotations

from enum import Enum

import numpy as np
from PIL import Image, ImageFilter

# Taille max (en pixels de large) utilisée pour l'aperçu à l'écran.
PREVIEW_MAX_WIDTH = 1920


class FillMode(Enum):
    """Stratégie de remplissage des zones ajoutées lors d'un agrandissement
    de canvas."""
    COLOR = "color"                # bordure unie
    BLUR_EXTEND = "blur_extend"    # prolongation floue des bords


def _edge_stretch(image: Image.Image, new_width: int, new_height: int) -> Image.Image:
    """Prolonge les bords de `image` (dernière ligne/colonne répétée) pour
    atteindre la taille cible.

    Le positionnement est centré : si `new_width < image.width`, la fonction
    recadre au centre (équivalent à un crop). Voir resize_canvas pour la
    logique complète.
    """
    arr = np.asarray(image)
    h, w = arr.shape[:2]

    ys = np.clip(np.arange(new_height) - (new_height - h) // 2, 0, h - 1)
    xs = np.clip(np.arange(new_width) - (new_width - w) // 2, 0, w - 1)

    out = arr[ys[:, None], xs[None, :]]
    return Image.fromarray(out, mode=image.mode)


def _blur_extend_fill(
    source: Image.Image,
    new_width: int,
    new_height: int,
    blur_radius: float,
) -> Image.Image:
    """Remplit un canvas de taille (new_width, new_height) en étirant les
    bords de `source` (edge stretch) puis en floutant le résultat.

    Optimisation : l'edge stretch et le flou sont faits sur une version
    downscalée, puis upscalés. Beaucoup plus rapide sur de grandes images,
    et visuellement identique puisque le résultat est flou.
    """
    blur_radius = max(0.5, float(blur_radius))
    # Un flou de rayon R ne peut pas révéler plus de détails qu'une image
    # d'échelle R/4 : on réduit d'autant avant de travailler.
    factor = max(1.0, blur_radius / 4.0)

    small_w = max(1, int(round(new_width / factor)))
    small_h = max(1, int(round(new_height / factor)))
    small_source_w = max(1, int(round(source.width / factor)))
    small_source_h = max(1, int(round(source.height / factor)))

    small_source = source.resize(
        (small_source_w, small_source_h), Image.Resampling.BILINEAR
    )
    small_stretched = _edge_stretch(small_source, small_w, small_h)
    small_blurred = small_stretched.filter(
        ImageFilter.GaussianBlur(blur_radius / factor)
    )
    return small_blurred.resize((new_width, new_height), Image.Resampling.BILINEAR)


def resize_canvas(
    image: Image.Image,
    new_width: int,
    new_height: int,
    fill_mode: FillMode = FillMode.COLOR,
    background: tuple[int, int, int, int] = (0, 0, 0, 0),
    blur_radius: float = 50.0,
) -> Image.Image:
    """Retourne un nouveau canvas de taille (new_width, new_height) avec
    `image` centrée dessus.

    Agrandir ajoute une bordure, réduire recadre au centre (le contenu de
    l'image ne change jamais d'échelle).

    Le remplissage des zones ajoutées dépend de `fill_mode` :
      - FillMode.COLOR : bordure unie de couleur `background` ;
      - FillMode.BLUR_EXTEND : prolongation floue des bords (le rayon du
        flou est donné par `blur_radius`, en pixels de l'image cible).

    En mode BLUR_EXTEND, si le canvas est plus petit que l'image sur les
    deux axes, on retombe naturellement sur un crop (rien à remplir).
    """
    image = image.convert("RGBA")
    new_width = max(1, int(round(new_width)))
    new_height = max(1, int(round(new_height)))

    offset_x = (new_width - image.width) // 2
    offset_y = (new_height - image.height) // 2

    # Si on réduit, on recadre d'abord la source pour ne jamais donner de
    # coordonnées négatives à paste().
    crop_left = max(0, -offset_x)
    crop_top = max(0, -offset_y)
    crop_right = crop_left + min(new_width, image.width)
    crop_bottom = crop_top + min(new_height, image.height)
    source = image.crop((crop_left, crop_top, crop_right, crop_bottom))

    needs_extend = new_width > image.width or new_height > image.height

    if fill_mode == FillMode.BLUR_EXTEND and needs_extend:
        base = _blur_extend_fill(source, new_width, new_height, blur_radius)
    else:
        base = Image.new("RGBA", (new_width, new_height), background)

    base.paste(source, (max(0, offset_x), max(0, offset_y)), source)
    return base


def canvas_offset(
    image_size: tuple[int, int],
    canvas_size: tuple[int, int],
) -> tuple[int, int]:
    """Décalage (dx, dy) de l'image à l'intérieur du canvas centré."""
    return (
        (canvas_size[0] - image_size[0]) // 2,
        (canvas_size[1] - image_size[1]) // 2,
    )


def _ease_out_sine(t: np.ndarray) -> np.ndarray:
    """Easing « sine out » : monte vite au début puis ralentit en douceur
    vers 1, plutôt qu'une progression linéaire."""
    return np.sin(t * (np.pi / 2))


def _build_overlay_alpha(
    size: tuple[int, int],
    radius: float,
    feather: float,
    center: tuple[float, float],
) -> np.ndarray:
    """Construit un canal alpha (uint8) de la taille `size`.

    alpha = 0 à l'intérieur du cercle de rayon `radius`
    alpha = 1 à l'extérieur de `radius + feather`
    transition en ease-out-sine entre les deux.

    Optimisation clé : on ne calcule QUE le bounding-box du disque élargi
    (radius + feather). Le reste est laissé à alpha=1.
    """
    width, height = size
    cx, cy = center
    feather = max(float(feather), 1e-3)

    outer_r = radius + feather
    x0 = max(0, int(np.floor(cx - outer_r)))
    x1 = min(width, int(np.ceil(cx + outer_r)))
    y0 = max(0, int(np.floor(cy - outer_r)))
    y1 = min(height, int(np.ceil(cy + outer_r)))

    alpha = np.ones((height, width), dtype=np.uint8) * 255
    if x1 <= x0 or y1 <= y0:
        return alpha

    y, x = np.mgrid[y0:y1, x0:x1]
    distance = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)

    t = np.clip((distance - radius) / feather, 0.0, 1.0)
    local_alpha = (_ease_out_sine(t) * 255.0).astype(np.uint8)

    alpha[y0:y1, x0:x1] = local_alpha
    return alpha


def render_composite(
    image: Image.Image,
    background: tuple[int, int, int, int],
    radius: float,
    feather: float,
    center: tuple[float, float],
) -> Image.Image:
    """Assemble les 3 couches en une image RGBA finale :

    1. un canvas uni de couleur `background` ;
    2. `image` collée par-dessus ;
    3. un overlay de la couleur `background`, opaque à l'extérieur du
       cercle (radius + feather) et transparent au centre.
    """
    image = image.convert("RGBA")
    width, height = image.size

    canvas = Image.new("RGBA", (width, height), background)
    composed = Image.alpha_composite(canvas, image)

    overlay_alpha = _build_overlay_alpha((width, height), radius, feather, center)
    overlay = Image.new("RGBA", (width, height), background)
    overlay.putalpha(Image.fromarray(overlay_alpha, mode="L"))

    return Image.alpha_composite(composed, overlay)


def downscale_for_preview(
    image: Image.Image,
    max_width: int = PREVIEW_MAX_WIDTH,
) -> tuple[Image.Image, float]:
    """Retourne (image_réduite, facteur_d_échelle)."""
    if image.width <= max_width:
        return image, 1.0
    scale = max_width / image.width
    new_size = (max_width, max(1, round(image.height * scale)))
    return image.resize(new_size, Image.Resampling.LANCZOS), scale