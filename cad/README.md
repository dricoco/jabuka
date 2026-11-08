# CAD – support et boîte tablette X35

Modèles FreeCAD paramétriques (FreeCAD 1.1, Part workbench) du support de tablette
pour le piédestal Jefa de l'X35 et de la boîte de la tablette 10.1" (Feonal K116)
avec son module powerbank. Impression : PETG sur Bambu Lab A1.

| Dossier | Script | Contenu |
|---|---|---|
| `support/` | `x35_tablet_mount_v5.py` | socle réglable (poutre à queue d'aronde, coulisseaux, berceaux en V + colliers inox, colonne réglable avant/arrière), tour orientable, tête VESA |
| `boite/` | `x35_tablet_box.py` | boîte, cadre, poussoir marche, module powerbank, bouchon |

Les paramètres (dimensions supposées du piédestal, de la tablette, de la powerbank)
sont en tête de chaque script.

## Régénérer

```sh
cd cad/boite   && freecadcmd -c "exec(open('build_boite.py').read())"
cd cad/support && freecadcmd -c "exec(open('build_support.py').read())"
```

Chaque build affiche un rapport de vérification (collisions, distance tablette–barre
aux butées, taille A1), écrit les STL dans `../../stl/<boite|support>/`, le STEP dans
`build/` (ignoré par git) et le `.FCStd` dans le dossier du script.

Construire la boîte avant le support : `TAB_W/TAB_H/TAB_D` du support doivent
correspondre à l'encombrement de la boîte (247 × 200 × 37,5 mm, bouchon compris).

## Nomenclature (BOM)

`bom/X35_support_tablette_BOM.pdf` : liste de courses quincaillerie, pièces imprimées
avec croquis, quantités et remarques. Régénérer avec `python3 bom/make_bom.py`
(reportlab ; croquis dans `bom/img/`, rendus depuis FreeCAD).
