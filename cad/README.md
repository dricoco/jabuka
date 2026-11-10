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
correspondre à l'encombrement de la boîte (250 × 200 × 37,5 mm, bouchon compris ; élargie de 3 mm côté boutons, `TAB_X0, TAB_X1`).

## Nomenclature (BOM)

`bom/X35_support_tablette_BOM.pdf` : liste de courses quincaillerie, pièces imprimées
avec croquis, quantités et remarques. Régénérer avec `python3 bom/make_bom.py`
(reportlab ; croquis dans `bom/img/`, rendus depuis FreeCAD).

## Points de montage à respecter

- Écrous captifs partout (pas d'inserts à chaud) : glisser les écrous dans leurs fentes avant
  d'assembler ; les plafonds de fente s'impriment en pont, sans support.
- Pivots des berceaux : vis **M6 × 45, pas plus longue** (le bout arrive à ~0,5 mm du fond du V),
  rondelle large côté poutre. Le pivot Ø14 ne fait que centrer : c'est le serrage de la vis qui
  plaque le berceau sur le coulisseau. Il doit tourner librement avant serrage.
- L'écrou M6 du berceau tire sur 6,5 mm de PETG plein (`CR_EXTRA = 4` dans le script) ; tout
  ce qui est derrière le berceau (coulisseaux, poutre, colonne, tablette) est décalé d'autant
  vers l'arrière, sans changer de forme.
- Queue d'aronde : jeu 0,5 mm par flanc ; imprimer `TEST_Coulisseau` d'abord.
