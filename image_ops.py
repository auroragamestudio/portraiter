"""Fonctions de traitement d'image pures (aucune dépendance à Qt).

Séparées de l'interface graphique pour rester simples à lire, tester et
réutiliser indépendamment du lancement de l'application.
"""
from __future__ import annotations

import numpy as np
from PIL import Image


def resize_canvas(
    image: Image.Image,
    new_width: int,
    new_height: int,
    background: tuple[int, int, int, int] = (0, 0, 0, 0),
) -> Image.Image:
    """Retourne un nouveau canvas de taille (new_width, new_height) avec
    `image` centrée dessus.

    Agrandir une dimension ajoute une bordure de couleur `background` tout
    autour de l'image. Réduire une dimension recadre l'image (toujours
    centrée) plutôt que de la redimensionner elle-même : le contenu de
    l'image ne change jamais d'échelle.
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

    canvas = Image.new("RGBA", (new_width, new_height), background)
    canvas.paste(source, (max(0, offset_x), max(0, offset_y)), source)
    return canvas


def apply_circular_fade_mask(
    image: Image.Image,
    radius: float,
    feather: float,
    center: tuple[float, float] | None = None,
) -> Image.Image:
    """Retourne une copie de `image` masquée par un cercle.

    Les pixels situés à moins de `radius` du centre restent totalement
    opaques. Au-delà, l'opacité diminue linéairement jusqu'à zéro sur une
    distance de `feather` pixels ; au-delà de `radius + feather`, les
    pixels sont entièrement transparents.
    """
    image = image.convert("RGBA")
    width, height = image.size
    cx, cy = center if center is not None else (width / 2, height / 2)
    feather = max(float(feather), 1e-3)  # évite une division par zéro

    y, x = np.mgrid[0:height, 0:width]
    distance = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
    fade = 1.0 - (distance - radius) / feather
    mask = np.clip(fade, 0.0, 1.0)

    alpha = np.asarray(image.getchannel("A"), dtype=np.float32) / 255.0
    combined_alpha = (alpha * mask * 255.0).astype(np.uint8)

    result = image.copy()
    result.putalpha(Image.fromarray(combined_alpha, mode="L"))
    return result
