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


def _ease_out_sine(t: np.ndarray) -> np.ndarray:
    """Easing « sine out » : monte vite au début puis ralentit en douceur
    vers 1, plutôt qu'une progression linéaire."""
    return np.sin(t * (np.pi / 2))


def apply_circular_fade_mask(
    image: Image.Image,
    radius: float,
    feather: float,
    center: tuple[float, float] | None = None,
) -> Image.Image:
    """Retourne une copie de `image` masquée par un cercle.

    Les pixels situés à moins de `radius` du centre restent totalement
    opaques. Au-delà, l'opacité diminue jusqu'à zéro sur une distance de
    `feather` pixels en suivant une courbe d'easing sine-out (plutôt qu'un
    dégradé linéaire) ; au-delà de `radius + feather`, les pixels sont
    entièrement transparents.
    """
    image = image.convert("RGBA")
    width, height = image.size
    cx, cy = center if center is not None else (width / 2, height / 2)
    feather = max(float(feather), 1e-3)  # évite une division par zéro

    y, x = np.mgrid[0:height, 0:width]
    distance = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
    # t = 0 pile au rayon (encore opaque), t = 1 à radius + feather (transparent).
    t = np.clip((distance - radius) / feather, 0.0, 1.0)
    mask = 1.0 - _ease_out_sine(t)

    alpha = np.asarray(image.getchannel("A"), dtype=np.float32) / 255.0
    combined_alpha = (alpha * mask * 255.0).astype(np.uint8)

    result = image.copy()
    result.putalpha(Image.fromarray(combined_alpha, mode="L"))
    return result


def composite_over_background(
    image: Image.Image,
    background: tuple[int, int, int, int],
) -> Image.Image:
    """Colle `image` (avec transparence) sur un fond uni de la même taille.

    Utilisé pour que les zones rendues transparentes par le masque circulaire
    affichent la couleur de fond du canvas plutôt que de rester transparentes.
    """
    image = image.convert("RGBA")
    canvas = Image.new("RGBA", image.size, background)
    return Image.alpha_composite(canvas, image)
