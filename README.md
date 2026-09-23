# Éditeur d'image — canvas & masque circulaire

Petite application de bureau (PySide6 + Pillow) pour :
- charger une image par glisser-déposer ou via un sélecteur de fichier ;
- redimensionner le canvas de l'image en la gardant centrée (agrandissement
  avec une couleur de fond au choix, ou recadrage si on réduit) ;
- appliquer un masque circulaire dont le bord intérieur disparaît en fondu
  (rayon, largeur du fondu et centre réglables) ;
- enregistrer le résultat (PNG conseillé pour conserver la transparence).

## Installation

```bash
pip install -r requirements.txt
```

## Lancement

```bash
python main.py
```

## Structure

- `image_ops.py` — logique de traitement d'image pure (Pillow + numpy), sans
  dépendance à Qt.
- `main.py` — interface graphique PySide6 (fenêtre, panneau de contrôle,
  drag-and-drop).

## Utilisation rapide

1. Glissez une image dans la zone grise (ou « Charger une image… »).
2. Pour l'agrandissement : réglez largeur/hauteur en % de la taille de
   l'image chargée (l'aperçu affiche la taille en pixels correspondante),
   choisissez une couleur de fond (avec canal alpha si besoin), puis
   « Appliquer le redimensionnement ».
3. Pour le masque : réglez le rayon et le fondu (en pixels), ajustez le
   centre si besoin, puis « Appliquer le masque ».
4. « Enregistrer l'image sous… » pour exporter le résultat.

Les opérations s'appliquent sur l'image de travail de façon cumulative ;
« Réinitialiser » revient à l'image d'origine.
