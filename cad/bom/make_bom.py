from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak, KeepTogether)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os, datetime

D = os.path.dirname(os.path.abspath(__file__))
IMG = os.path.join(D, "img")
pdfmetrics.registerFont(TTFont("DV", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DVB", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))
from reportlab.lib.fonts import addMapping
addMapping("DV", 0, 0, "DV"); addMapping("DV", 1, 0, "DVB")

ss = getSampleStyleSheet()
N = ParagraphStyle("n", parent=ss["Normal"], fontName="DV", fontSize=8.5, leading=11)
S = ParagraphStyle("s", parent=N, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#444444"))
H1 = ParagraphStyle("h1", parent=N, fontName="DVB", fontSize=18, leading=22, spaceAfter=4)
H2 = ParagraphStyle("h2", parent=N, fontName="DVB", fontSize=12.5, leading=16, spaceBefore=8, spaceAfter=5)
B = ParagraphStyle("b", parent=N, fontName="DVB")

PETG = 1.27      # g/cm3
FILL = 0.6       # rough share of solid volume actually printed (4-5 perimeters, 30-40 % gyroid)

# name, image, qty, (x,y,z), volume cm3, notes
SUPPORT = [
    ("TEST_Poutre_bout", 1, (30, 22, 48), 25.3, "Coupon de test : bout de poutre avec rainure. <b>À imprimer en premier.</b> Inchangé depuis le 1er test : inutile de le refaire."),
    ("TEST_Coulisseau", 1, (44, 17, 40), 22.5, "Coupon de test : coulisseau. Jeu queue d'aronde 0,5 mm/flanc. Doit glisser à la main sans basculer."),
    ("Poutre", 1, (248, 61, 48), 375.6, "Rainure queue d'aronde + crans 1,5 mm, fentes de blocage, plateau central. <b>4 écrous M6 captifs</b> (fentes latérales du plateau)."),
    ("Berceau_S", 1, (77, 47, 69), 82.8, "Berceau en V tribord. 2 tunnels de collier + rainures de guidage. <b>1 écrou M6 captif</b> (fente juste derrière le fond du V, 6,5 mm de matière pleine sous le pivot). Caoutchouc dans le V. Le pivot doit tourner librement dans le coulisseau avant serrage."),
    ("Berceau_P", 1, (77, 47, 69), 82.8, "Berceau en V bâbord, idem tribord (pièce miroir)."),
    ("Coulisseau_S", 1, (44, 17, 40), 22.5, "Tenon queue d'aronde + crans, tribord."),
    ("Coulisseau_P", 1, (44, 17, 40), 22.5, "Tenon queue d'aronde + crans, bâbord."),
    ("Column", 1, (90, 80, 81), 204.2, "Colonne : pied à fentes (réglage avant/arrière 0 à +30 mm), crantage de lacet, anneau de butée. <b>1 écrou M8 captif</b> (fenêtre latérale)."),
    ("Tower", 1, (56, 77, 168), 189.9, "Tour (lacet). <b>5 périmètres, 40 % de remplissage, +5 à 10 °C</b> pour l'adhérence des couches (pied de tige sollicité par le vent)."),
    ("VESA_Head", 1, (120, 79, 120), 120.8, "Tête VESA 100 (inclinaison). <b>1 écrou M8 captif</b> (inclinaison)."),
    ("Bouton_lacet", 1, (30, 30, 22), 12.9, "Bouton étoile Ø30 pour <b>vis hexagonale M8 × 50</b> (lacet). Tête de vis enfoncée dans l'hexagone (étau ou un peu de chaleur). Ø30 maxi : à 2 mm du fût de la tour. Imprimer dessus sur le plateau."),
    ("Bouton_inclinaison", 1, (40, 40, 16), 17.5, "Bouton étoile Ø40 pour <b>vis hexagonale M8 × 45</b> (inclinaison). Même montage. Imprimer dessus sur le plateau."),
]
BOITE = [
    ("BOX_Boite", 1, (253, 14, 192), 202.7, "Boîte (logement tablette). <b>8 écrous M3 captifs</b>, fentes ouvertes côté logement. Min. 3 périmètres (peau de 0,7 mm devant les écrous)."),
    ("BOX_Cadre", 1, (253, 3, 192), 50.7, "Cadre avant (fenêtre écran, encoche bouton home). Drains en rainure au dos, peau de 1 mm côté écran : une seule pièce. Imprimer face avant sur le plateau."),
    ("BOX_Poussoir", 1, (8, 8, 8), 0.2, "Poussoir du bouton marche/arrêt, mis en place par l'intérieur avant la tablette."),
    ("BOX_Module_powerbank", 1, (120, 21, 192), 209.8, "Module powerbank + interface VESA. <b>8 écrous M4 + 2 écrous M3 captifs</b>, fentes ouvertes vers le logement powerbank."),
    ("BOX_Bouchon", 1, (120, 21, 47), 15.2, "Bouchon inférieur (tient la powerbank, sorties câbles vers le bas)."),
]

QUINC = [
    ("Support", "Collier de serrage inox A4 (316), 60–80 mm, bande 12 mm", 4, "2 par berceau, dans les tunnels, vis côté extérieur (jamais vers les rayons)"),
    ("Support", "Vis M6 × 45 + rondelle large (M6 × 18)", 2, "Pivots : poutre → coulisseau → berceau. <b>Pas plus longue que 45</b> (le bout arrive au fond du V)"),
    ("Support", "Vis M6 × 20 + rondelle", 4, "Pied de colonne → poutre"),
    ("Support", "Écrou M6 (DIN 934, 10 mm s/plats)", 6, "4 dans la poutre, 1 par berceau"),
    ("Support", "Vis hexagonale M8 × 50 (DIN 933, 13 mm s/plats)", 1, "Lacet (vertical), tête dans le bouton étoile imprimé"),
    ("Support", "Vis hexagonale M8 × 45 (DIN 933, 13 mm s/plats)", 1, "Inclinaison (horizontal), tête dans le bouton étoile imprimé"),
    ("Support", "Écrou M8 (13 mm s/plats) + rondelle", 2, "1 dans la colonne, 1 dans la tête VESA"),
    ("Support", "Caoutchouc (chambre à air) ≈ 60 × 50 mm", 2, "Dans le V des berceaux, contre le tube"),
    ("Boîte", "Vis M3 × 10 tête fraisée", 8, "Cadre → boîte"),
    ("Boîte", "Vis M3 × 12 tête fraisée", 2, "Bouchon → module powerbank"),
    ("Boîte", "Écrou M3 (5,5 mm s/plats)", 10, "8 dans la boîte, 2 dans le module"),
    ("Boîte", "Vis M4 × 12 tête fraisée", 4, "Boîte → module powerbank"),
    ("Boîte", "Vis M4 × 16 + rondelle", 4, "Tête VESA → module powerbank (VESA 100)"),
    ("Boîte", "Écrou M4 (7 mm s/plats)", 8, "Dans le module powerbank"),
    ("Boîte", "Mousse EPDM 1,5 mm ≈ 230 × 150 mm", 1, "Derrière la tablette"),
    ("Boîte", "Sac congélation (option)", 1, "Tablette dedans si pluie forte"),
]

def thumb(name, w=46 * mm):
    p = os.path.join(IMG, name + ".png")
    from reportlab.lib.utils import ImageReader
    iw, ih = ImageReader(p).getSize()
    return Image(p, width=w, height=w * ih / iw)

def part_table(rows):
    data = [[Paragraph("<b>Croquis</b>", N), Paragraph("<b>Pièce</b>", N), Paragraph("<b>Nb</b>", N),
             Paragraph("<b>Taille (mm)</b>", N), Paragraph("<b>PETG ≈</b>", N), Paragraph("<b>Remarques</b>", N)]]
    tot = 0
    for name, q, (x, y, z), vol, note in rows:
        g = vol * PETG * FILL * q
        tot += g
        data.append([thumb(name), Paragraph("<b>%s</b><br/><font size=7 color='#666666'>%s.stl</font>" % (name.replace("BOX_", ""), name.replace("BOX_", "")), N),
                     Paragraph(str(q), N), Paragraph("%d × %d × %d" % (x, y, z), N),
                     Paragraph(("%d g" % round(g)) if g >= 1 else "&lt; 1 g", N), Paragraph(note, S)])
    t = Table(data, colWidths=[46 * mm, 32 * mm, 9 * mm, 26 * mm, 15 * mm, 58 * mm], repeatRows=1)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF6")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B0B8C4")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t, tot

def footer(c, doc):
    c.saveState()
    c.setFont("DV", 7.5)
    c.setFillColor(colors.HexColor("#777777"))
    c.drawString(15 * mm, 9 * mm, "Jabuka – support tablette X35 + boîte – nomenclature")
    c.drawRightString(195 * mm, 9 * mm, "page %d" % doc.page)
    c.restoreState()

doc = SimpleDocTemplate(os.path.join(D, "X35_support_tablette_BOM.pdf"), pagesize=A4,
                        leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=15 * mm,
                        title="Support tablette X35 – nomenclature", author="Jabuka")
st = []
st.append(Paragraph("Support tablette X35 + boîte – nomenclature", H1))
st.append(Paragraph("Piédestal Jefa, tablette Feonal K116 10,1\", powerbank Goodmans 10 000 mAh. "
                    "Impression PETG sur Bambu Lab A1. Fichiers : <b>stl/support/</b> et <b>stl/boite/</b> du dépôt jabuka. "
                    "Édition du %s." % datetime.date.today().strftime("%d/%m/%Y"), N))
st.append(Spacer(1, 3 * mm))
st.append(Paragraph("Liste de courses – magasin de bricolage", H2))
st.append(Paragraph("Tout en <b>inox</b> (A4/316 si dispo, sinon A2/304 ; jamais de zingué en mer). "
                    "Les quantités incluent déjà quelques écrous de rechange.", N))
st.append(Spacer(1, 2 * mm))
SHOP = [
    ("Visserie", "Vis tête hexagonale ou CHC M6 × 45 (pas plus long)", "2", "pivots des berceaux"),
    ("Visserie", "Vis tête hexagonale ou CHC M6 × 20", "4", "pied de colonne"),
    ("Visserie", "Écrous M6 (hauteur normale)", "8", "6 utilisés + 2 rechange"),
    ("Visserie", "Rondelles M6 (dont 2 larges M6 × 18)", "6", "2 larges sous les têtes des pivots, côté poutre"),
    ("Visserie", "Écrous M8 + rondelles M8", "2 + 2", "lacet et inclinaison"),
    ("Visserie", "Vis M4 × 16 (tête cylindrique) + rondelles M4", "4 + 4", "fixation VESA"),
    ("Visserie", "Vis M4 × 12 tête fraisée", "4", "boîte → module"),
    ("Visserie", "Écrous M4", "10", "8 utilisés + 2 rechange"),
    ("Visserie", "Vis M3 × 10 tête fraisée", "8", "cadre → boîte"),
    ("Visserie", "Vis M3 × 12 tête fraisée", "2", "bouchon → module"),
    ("Visserie", "Écrous M3", "14", "10 utilisés + 4 rechange (ça se perd)"),
    ("Serrage", "Vis hexagonale M8 × 50 inox A2 (DIN 933). kamm.si : « RF šestrobi vijak M8X50 A2 », réf. 00677", "1", "lacet ; le bouton étoile est imprimé (Bouton_lacet)"),
    ("Serrage", "Vis hexagonale M8 × 45 inox A2 (DIN 933). kamm.si : « RF šestrobi vijak M8X45 A2 », réf. 00676", "1", "inclinaison ; bouton imprimé (Bouton_inclinaison)"),
    ("Plomberie", "Colliers de serrage inox A4, plage 60–80 mm, bande 12 mm. En slovène : <i>inox cevna objemka</i> ; kamm.si : « RF OBJEMKA CEV. 60-80/12 3017 A4 »", "4 (+1)", "pas de zingué ; 70–90 ne serre pas assez (il faut ≈ Ø66) ; 50–70 passe en dépannage, en fin de course"),
    ("Cycle / divers", "Chambre à air vélo usagée (ou plaque caoutchouc 2 mm)", "1", "garniture du V des berceaux"),
    ("Isolation", "Joint mousse EPDM adhésif, ~1,5–2 mm d'épaisseur", "1 rouleau", "dos de la tablette"),
]
sd = [[Paragraph("<b>%s</b>" % h, N) for h in ("✓", "Rayon", "Article", "Qté", "Pour")]]
for r, a, q, u in SHOP:
    sd.append([Paragraph("☐", N), Paragraph(r, S), Paragraph(a, N), Paragraph(q, N), Paragraph(u, S)])
stbl = Table(sd, colWidths=[7 * mm, 22 * mm, 78 * mm, 17 * mm, 62 * mm], repeatRows=1)
stbl.setStyle(TableStyle([
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF6")),
    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B0B8C4")),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
]))
st.append(stbl)
st.append(Spacer(1, 2 * mm))
st.append(Paragraph("Outils utiles : clés plates 10 et 13, clés Allen correspondantes, tournevis plat pour les colliers, "
                    "pince à bec (pour glisser les écrous M3 dans leurs fentes).", S))
st.append(PageBreak())
st.append(Paragraph("Vue d'ensemble", H2))
st.append(thumb("assemblage_zoom", 150 * mm))
st.append(Paragraph("Orange : pièces imprimées mobiles · bleu : poutre et colonne · gris foncé / vert : boîte et module powerbank · "
                    "noir : boutons M8 · gris clair : piédestal et colliers (non imprimés).", S))
st.append(Spacer(1, 3 * mm))
st.append(Paragraph("Réglages clés", H2))
for txt in [
    "Centre de la tablette à <b>730 mm</b> du plancher. Lacet ±45° et inclinaison ±18° par crans de 15° (crantage Hirth) ; desserrer le bouton d'environ 3 tours pour changer de cran.",
    "Queue d'aronde : jeu <b>0,5 mm par flanc</b>. Imprimer <b>TEST_Coulisseau</b> et l'essayer dans TEST_Poutre_bout avant la grande poutre ; ébavurer la première couche si ça coince.",
    "Écrous captifs partout (pas d'inserts à chaud) : glisser les écrous dans leurs fentes avant le montage ; les plafonds de fente s'impriment en pont, sans support.",
    "Pièces du support : 4 périmètres minimum, 30–40 % gyroïde (Tower : 5 périmètres, 40 %, +5 à 10 °C).",
    "Masses PETG estimées à ~60 % du volume plein : ordre de grandeur pour prévoir la bobine, pas une valeur du slicer.",
]:
    st.append(Paragraph("• " + txt, N))
st.append(PageBreak())

st.append(Paragraph("1. Pièces imprimées – support", H2))
t1, g1 = part_table(SUPPORT)
st.append(t1)
st.append(PageBreak())
st.append(Paragraph("2. Pièces imprimées – boîte tablette", H2))
t2, g2 = part_table(BOITE)
st.append(t2)
st.append(Spacer(1, 3 * mm))
st.append(Paragraph("<b>Total PETG estimé :</b> support ≈ %d g, boîte ≈ %d g, soit ≈ %d g : prévoir 2 bobines de 1 kg (les coupons de test et les éventuelles réimpressions comptent aussi)." % (round(g1), round(g2), round(g1 + g2)), N))

st.append(Paragraph("3. Quincaillerie (de préférence inox A4)", H2))
qd = [[Paragraph("<b>%s</b>" % h, N) for h in ("Groupe", "Article", "Qté", "Usage")]]
for grp, art, q, use in QUINC:
    qd.append([Paragraph(grp, N), Paragraph(art, N), Paragraph(str(q), N), Paragraph(use, S)])
qt = Table(qd, colWidths=[20 * mm, 78 * mm, 11 * mm, 77 * mm], repeatRows=1)
qt.setStyle(TableStyle([
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF6")),
    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B0B8C4")),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
]))
st.append(qt)
st.append(Spacer(1, 3 * mm))
st.append(Paragraph("<b>Récapitulatif écrous :</b> 6 × M6, 2 × M8, 8 × M4, 10 × M3. "
                    "<b>Vis :</b> 2 × M6×45, 4 × M6×20, 4 × M4×16, 4 × M4×12 TF, 8 × M3×10 TF, 2 × M3×12 TF.", N))
doc.build(st, onFirstPage=footer, onLaterPages=footer)
print("ok")
