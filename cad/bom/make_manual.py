# Assembly manual (IKEA style) for the X35 tablet mount + box.
# Images: cad/bom/img/m_*.png, rendered in the FreeCAD GUI by manual_scenes.py.
# Regenerate:  python3 cad/bom/make_manual.py
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak,
                                KeepTogether, Flowable)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.fonts import addMapping
import math, os, datetime

D = os.path.dirname(os.path.abspath(__file__))
IMG = os.path.join(D, "img")
pdfmetrics.registerFont(TTFont("DV", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DVB", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))
addMapping("DV", 0, 0, "DV"); addMapping("DV", 1, 0, "DVB")

ss = getSampleStyleSheet()
N = ParagraphStyle("n", parent=ss["Normal"], fontName="DV", fontSize=9, leading=12)
S = ParagraphStyle("s", parent=N, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#444444"))
H1 = ParagraphStyle("h1", parent=N, fontName="DVB", fontSize=20, leading=24, spaceAfter=4)
H2 = ParagraphStyle("h2", parent=N, fontName="DVB", fontSize=13, leading=16, spaceBefore=4, spaceAfter=4)
WARN = ParagraphStyle("w", parent=N, backColor=colors.HexColor("#FFF1D6"), borderPadding=4, leftIndent=4, rightIndent=4,
                      spaceBefore=4, spaceAfter=2)
ORANGE = colors.HexColor("#F08C22")
STEEL = colors.HexColor("#8A95A8")
INK = colors.HexColor("#222222")

AFS = {3: 5.5, 4: 7.0, 6: 10.0, 8: 13.0}


class HW(Flowable):
    """Hardware drawn at 1:1 (when printed at 100 %), with quantity.
    kind: hex (hex head bolt, side), cyl (socket/cheese head, side), csk (countersunk, side),
    nut (front), washer (front), knob (star knob M8, side)"""

    def __init__(self, kind, M, L=0, qty=1, label=None, od=None, scale=1.0):
        Flowable.__init__(self)
        self.kind, self.M, self.L, self.qty, self.od, self.k = kind, M, L, qty, od, scale * mm
        self.label = label or {"hex": "Vis M%d × %d", "cyl": "Vis M%d × %d", "csk": "Vis M%d × %d tête fraisée",
                               "knob": "Bouton étoile M%d, tige %d"}.get(kind, "")
        if kind in ("hex", "cyl", "csk", "knob"):
            self.label = self.label % (M, L)
        elif kind == "nut":
            self.label = "Écrou M%d" % M
        elif kind == "washer":
            self.label = "Rondelle M%d" % M + (" large Ø%d" % od if od else "")
        hd = {"hex": 0.7 * M, "cyl": M, "csk": 0, "knob": 14}.get(kind, 0)
        if kind in ("nut",):
            self.wmm, self.hmm = AFS[M] * 2 / math.sqrt(3), AFS[M]
        elif kind == "washer":
            self.wmm = self.hmm = od or 2 * M
        elif kind == "knob":
            self.wmm, self.hmm = hd + L, 38
        else:
            self.wmm, self.hmm = hd + L, max(AFS[M] * 2 / math.sqrt(3) if kind == "hex" else (2 * M if kind == "csk" else 1.6 * M), M)
        self.wide = self.wmm > 45
        self.width = max(self.wmm * self.k, 26 * mm) + (2 * mm if self.wide else 16 * mm)
        self.height = self.hmm * self.k + 9 * mm

    def draw(self):
        c, k, M = self.canv, self.k, self.M
        cy = 7 * mm + self.hmm * k / 2
        x0 = 1 * mm
        c.setStrokeColor(INK); c.setLineWidth(0.6); c.setFillColor(colors.HexColor("#C9CFD8"))
        if self.kind in ("hex", "cyl", "csk", "knob"):
            if self.kind == "hex":
                hh, hw = 0.7 * M, AFS[M] * 2 / math.sqrt(3)
                c.rect(x0, cy - hw / 2 * k, hh * k, hw * k, fill=1)
                c.line(x0, cy - hw / 4 * k, x0 + hh * k, cy - hw / 4 * k)
                c.line(x0, cy + hw / 4 * k, x0 + hh * k, cy + hw / 4 * k)
            elif self.kind == "cyl":
                hh, hw = M, 1.6 * M
                c.roundRect(x0, cy - hw / 2 * k, hh * k, hw * k, 0.6 * k, fill=1)
            elif self.kind == "csk":
                hh = M / 2
                p = c.beginPath(); p.moveTo(x0, cy - M * k); p.lineTo(x0, cy + M * k)
                p.lineTo(x0 + hh * k, cy + M / 2 * k); p.lineTo(x0 + hh * k, cy - M / 2 * k); p.close()
                c.drawPath(p, fill=1)
            else:
                hh = 14
                c.setFillColor(colors.HexColor("#333333"))
                c.roundRect(x0, cy - 19 * k, hh * k, 38 * k, 3 * k, fill=1)
                c.setFillColor(colors.HexColor("#C9CFD8"))
            xs = x0 + hh * k
            c.rect(xs, cy - M / 2 * k, self.L * k, M * k, fill=1)
            pitch = {3: 0.5, 4: 0.7, 6: 1.0, 8: 1.25}[M] * 2
            c.setLineWidth(0.25)
            x = xs + pitch * k
            while x < xs + self.L * k - 0.3 * k:
                c.line(x, cy - M / 2 * k, x - pitch * 0.5 * k, cy + M / 2 * k)
                x += pitch * k
            c.setLineWidth(0.6)
        elif self.kind == "nut":
            r = AFS[M] / math.sqrt(3)
            cx = x0 + r * k
            p = c.beginPath()
            for i in range(6):
                a = math.radians(60 * i)
                (p.moveTo if i == 0 else p.lineTo)(cx + r * math.cos(a) * k, cy + r * math.sin(a) * k)
            p.close(); c.drawPath(p, fill=1)
            c.setFillColor(colors.white); c.circle(cx, cy, M / 2 * k, fill=1)
        elif self.kind == "washer":
            r = (self.od or 2 * M) / 2
            cx = x0 + r * k
            c.circle(cx, cy, r * k, fill=1)
            c.setFillColor(colors.white); c.circle(cx, cy, (M / 2 + 0.3) * k, fill=1)
        c.setFillColor(INK); c.setFont("DV", 7)
        c.drawString(x0, 1.5 * mm, self.label)
        c.setFont("DVB", 13)
        if self.wide:
            c.drawRightString(x0 + self.wmm * k, cy + self.M / 2 * k + 2 * mm, "×%d" % self.qty)
        else:
            c.drawString(x0 + max(self.wmm * k, 26 * mm) + 2 * mm, cy - 4.5, "×%d" % self.qty)


def img(name, w, max_h=None):
    from reportlab.lib.utils import ImageReader
    p = os.path.join(IMG, name + ".png")
    iw, ih = ImageReader(p).getSize()
    if max_h and w * ih / iw > max_h:
        w = max_h * iw / ih
    return Image(p, width=w, height=w * ih / iw)


def crop_all():
    """trim the white margins of the rendered step images (in place)"""
    from PIL import Image as PI, ImageChops
    for f in os.listdir(IMG):
        if not f.startswith("m_"):
            continue
        p = os.path.join(IMG, f)
        im = PI.open(p).convert("RGB")
        bb = ImageChops.difference(im, PI.new("RGB", im.size, "white")).getbbox()
        if bb:
            pad = 20
            bb = (max(bb[0] - pad, 0), max(bb[1] - pad, 0), min(bb[2] + pad, im.width), min(bb[3] + pad, im.height))
            if bb != (0, 0, im.width, im.height):
                im.crop(bb).save(p)


def hw_box(items, title="Il te faut"):
    rows = [[Paragraph("<b>%s</b>" % title, N)]] + [[h] for h in items] if items else \
           [[Paragraph("<b>%s</b>" % title, N)], [Paragraph("Rien : seulement les pièces imprimées.", S)]]
    t = Table(rows, colWidths=[64 * mm])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.8, INK), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF6")),
                           ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                           ("LEFTPADDING", (0, 0), (-1, -1), 4)]))
    return t


def step(num, title, images, hw, text, warn=None, img_w=118 * mm):
    BADGE = ParagraphStyle("badge", parent=N, fontName="DVB", fontSize=20, leading=24, textColor=colors.white, alignment=1)
    head = Table([[Paragraph(num, BADGE), Paragraph(title, H2)]],
                 colWidths=[16 * mm, 170 * mm])
    head.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), ORANGE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                              ("TOPPADDING", (0, 0), (0, 0), 2), ("BOTTOMPADDING", (0, 0), (0, 0), 4)]))
    if len(images) == 1:
        pics = img(images[0], img_w, 92 * mm)
    else:
        w = img_w / 2 - 2 * mm
        cells = [img(n, w, 55 * mm) for n in images]
        pics = Table([cells[i:i + 2] for i in range(0, len(cells), 2)], colWidths=[img_w / 2] * 2)
        pics.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    body = Table([[pics, hw_box(hw)]], colWidths=[img_w + 4 * mm, 68 * mm])
    body.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    out = [head, Spacer(1, 2 * mm), body, Spacer(1, 1 * mm)]
    out += [Paragraph("%d. %s" % (i + 1, t), N) for i, t in enumerate(text)]
    if warn:
        out.append(Paragraph("⚠ " + warn, WARN))
    out.append(Spacer(1, 5 * mm))
    return KeepTogether(out)


def footer(c, doc):
    c.saveState()
    c.setFont("DV", 7.5)
    c.setFillColor(colors.HexColor("#777777"))
    c.drawString(12 * mm, 9 * mm, "Jabuka – support tablette X35 + boîte – notice de montage")
    c.drawRightString(198 * mm, 9 * mm, "page %d" % doc.page)
    c.restoreState()


crop_all()
doc = SimpleDocTemplate(os.path.join(D, "X35_support_tablette_montage.pdf"), pagesize=A4,
                        leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=15 * mm,
                        title="Support tablette X35 – notice de montage", author="Jabuka")
st = []

# ---------------- cover ----------------
st.append(Paragraph("Support tablette X35 + boîte – notice de montage", H1))
st.append(Paragraph("Piédestal Jefa de l'X35, tablette Feonal K116 10,1\" dans sa boîte étanche, powerbank. "
                    "Pièces : <b>stl/support/</b> et <b>stl/boite/</b> ; liste de courses : <b>X35_support_tablette_BOM.pdf</b>. "
                    "Édition du %s." % datetime.date.today().strftime("%d/%m/%Y"), N))
st.append(Spacer(1, 3 * mm))
cov = Table([[img("m_13_fini", 100 * mm), [
    Paragraph("<b>Code couleur des dessins</b>", N),
    Paragraph("<font color='#F08C22'>■</font> orange : les pièces de l'étape", N),
    Paragraph("<font color='#AAAAAA'>■</font> gris : déjà monté", N),
    Paragraph("<font color='#8A95A8'>■</font> acier : vis, écrous, rondelles, colliers", N),
    Paragraph("<font color='#D81414'>➜</font> rouge : sens de montage / axe de la vis", N),
    Spacer(1, 4 * mm),
    Paragraph("<b>Outils</b>", N),
    Paragraph("• clé plate ou à pipe de <b>10</b> (M6), de <b>13</b> si boulons M8 au lieu des boutons<br/>"
              "• tournevis plat ou douille de <b>7</b> (vis des colliers)<br/>"
              "• tournevis / clé Allen adaptés aux têtes fraisées M3 et M4<br/>"
              "• pince fine (pousser les écrous), cutter, ciseaux<br/>"
              "• option : un peu de ruban adhésif pour retenir les écrous, frein-filet faible", N),
    Spacer(1, 4 * mm),
    Paragraph("<b>Avant tout</b> : imprimer <b>TEST_Poutre_bout</b> + <b>TEST_Coulisseau</b>. Le coulisseau doit glisser "
              "à la main sans basculer. Sinon, corriger <i>DT_C</i> avant d'imprimer la poutre.", N),
]]], colWidths=[104 * mm, 82 * mm])
cov.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
st.append(cov)
st.append(Spacer(1, 4 * mm))
st.append(Paragraph("Les vis et écrous sont dessinés <b>à l'échelle 1:1</b> (imprimer à 100 %, sans « ajuster à la page ») : "
                    "pose la vis sur le dessin pour vérifier la longueur. Récapitulatif en dernière page.", WARN))
st.append(Spacer(1, 3 * mm))
st.append(Paragraph("<b>Écrous captifs</b> : chaque écrou se glisse dans une fente latérale jusqu'à ce que son trou soit en face "
                    "du perçage. Pour vérifier, présente la vis : elle doit entrer dans l'écrou sans forcer. Si un écrou "
                    "force, ébavure la fente au cutter, ne tape pas dessus. S'il ressort tout seul, un bout de scotch "
                    "le tient jusqu'à ce que la vis le prenne.", N))
st.append(PageBreak())

# ---------------- support ----------------
st.append(Paragraph("Partie 1 – le support sur le piédestal", H1))
st.append(step("1", "Écrous captifs du support",
               ["m_1a_poutre_ecrous", "m_1b_berceau_ecrou", "m_1c_colonne_ecrou", "m_1d_tete_ecrou"],
               [HW("nut", 6, qty=6), HW("nut", 8, qty=2)],
               ["<b>Poutre</b> : 4 écrous M6 par les fentes sur les côtés du plateau central, à plat.",
                "<b>Berceaux</b> : 1 écrou M6 dans chaque berceau, par la fente juste derrière le fond du V, "
                "jusqu'au trou du pivot.",
                "<b>Colonne</b> : 1 écrou M8 par la fenêtre sur le côté.",
                "<b>Tête VESA</b> : 1 écrou M8 dans le logement hexagonal, sur le côté opposé au bouton."]))
st.append(step("2", "Coulisseaux dans la poutre",
               ["m_2_coulisseaux"], [],
               ["Glisse chaque coulisseau par un bout de la poutre, dans la queue d'aronde de la face avant, "
                "les crans contre les crans de la poutre.",
                "Coulisseau_S d'un côté, Coulisseau_P de l'autre (ils sont symétriques). Ils doivent glisser à la main."]))
st.append(step("3", "Berceaux et vis de pivot",
               ["m_3_berceaux_pivots"],
               [HW("hex", 6, 45, 2), HW("washer", 6, qty=2, od=18)],
               ["Engage le pivot Ø14 du berceau dans le trou du coulisseau, le V vers l'avant.",
                "Passe la vis M6 × 45 avec sa rondelle large par l'arrière de la poutre, à travers la lumière, "
                "le coulisseau et le berceau, jusque dans l'écrou du berceau.",
                "Visse seulement au contact : le berceau doit encore tourner sur son pivot et le coulisseau "
                "glisser dans la poutre."],
               warn="Vis de pivot : <b>45 mm, pas plus</b>. Plus longue, elle sort au fond du V et appuie sur le tube du pied."))
st.append(step("4", "Pose sur les pieds arrière du piédestal",
               ["m_4_pietement", "m_4_pietement_arriere"],
               [Paragraph("<b>Collier de serrage inox A4</b> 60–80 mm, bande 12 mm (<i>inox cevna objemka</i>) &nbsp;&nbsp;<font size=13><b>×4</b></font>", N),
                Paragraph("<b>Chambre à air</b> ≈ 60 × 50 mm &nbsp;&nbsp;<font size=13><b>×2</b></font>", N)],
               ["Coupe 2 morceaux de chambre à air et pose-les dans le V des berceaux.",
                "Présente l'ensemble derrière les deux pieds arrière, à ≈ 51 cm du plancher du cockpit, la poutre de niveau.",
                "Écarte ou rapproche les coulisseaux pour que chaque V se pose bien sur son pied. "
                "Les berceaux pivotent pour suivre l'angle des pieds.",
                "Par berceau, 2 colliers : autour du pied, dans les rainures des flancs, à travers les tunnels derrière le V. "
                "<b>Vis du collier côté extérieur</b>, jamais du côté de la roue.",
                "Serre les colliers petit à petit, en alternant, en gardant la poutre de niveau.",
                "Serre ensuite les 2 vis de pivot à fond avec la clé de 10 : les crans bloquent les coulisseaux."]))
st.append(step("5", "Colonne sur la poutre",
               ["m_5_colonne"],
               [HW("hex", 6, 20, 4), HW("washer", 6, qty=4)],
               ["Pose la colonne sur le plateau central de la poutre.",
                "4 vis M6 × 20 avec rondelle, à travers les lumières du pied, dans les écrous de la poutre.",
                "Réglage avant/arrière : la colonne peut reculer jusqu'à 30 mm vers le barreur. Plus en arrière, "
                "la tablette passe plus loin de la barre. Serre."]))
st.append(step("6", "Tour et bouton de rotation (lacet)",
               ["m_6_tour"],
               [HW("knob", 8, 50, 1)],
               ["Pose la tour sur la denture de la colonne. L'ergot de butée va dans le secteur ouvert, côté arrière.",
                "Visse le bouton étoile M8 (tige 50) par le dessus, à travers la tour, dans l'écrou de la colonne. "
                "Serre à la main.",
                "Pour orienter : desserre d'un ou deux tours, soulève la tour de 3 mm, tourne par crans de 15° et resserre. "
                "Butée vers ±45°."],
               warn="Pas de bouton ? Une vis M8 × 50 avec rondelle fait l'affaire (clé de 13)."))
st.append(step("7", "Tête VESA et bouton d'inclinaison",
               ["m_7_tete_vesa"],
               [HW("knob", 8, 45, 1)],
               ["Présente la tête VESA contre la denture du côté de la tour. Sa queue de butée se place entre les deux blocs de la tour.",
                "Visse le bouton étoile M8 (tige 45) par l'autre côté de la tour, dans l'écrou de la tête. Serre à la main.",
                "Inclinaison par crans de 15°, butée vers ±15°."]))

# ---------------- box ----------------
st.append(Paragraph("Partie 2 – la boîte de la tablette", H1))
st.append(step("8", "Écrous captifs de la boîte et du module",
               ["m_8a_boite_ecrous", "m_8b_module_ecrous"],
               [HW("nut", 3, qty=10), HW("nut", 4, qty=8)],
               ["<b>Boîte</b> : 8 écrous M3 par les fentes qui s'ouvrent dans le logement de la tablette (4 en haut, 4 en bas).",
                "<b>Module powerbank</b> : 8 écrous M4 et 2 écrous M3, par les fentes qui s'ouvrent dans le logement de la powerbank."]))
st.append(step("9", "Boîte sur le module, poussoir marche/arrêt",
               ["m_9_boite_module"],
               [HW("csk", 4, 12, 4)],
               ["Pose la boîte sur le module powerbank, dos contre dos.",
                "4 vis M4 × 12 tête fraisée par l'intérieur du logement de la tablette, dans les écrous du module.",
                "Mets le poussoir du bouton marche dans son trou, par l'intérieur, collerette côté intérieur."]))
st.append(step("10", "Mousse, tablette et cadre",
               ["m_10_tablette_cadre"],
               [HW("csk", 3, 10, 8),
                Paragraph("<b>Mousse EPDM</b> 1,5 mm ≈ 230 × 150 &nbsp;&nbsp;<font size=13><b>×1</b></font>", N)],
               ["Colle la mousse au fond du logement.",
                "Branche le câble USB-C plat dans la tablette et fais-le sortir par la fente du bas.",
                "Pose la tablette, éventuellement dans un sac congélation s'il pleut fort.",
                "Pose le cadre et serre les 8 vis M3 × 10 modérément (c'est du PETG)."]))
st.append(step("11", "Powerbank et bouchon",
               ["m_11_powerbank_bouchon"],
               [HW("csk", 3, 12, 2)],
               ["Branche les câbles sur la powerbank : USB-A vers la tablette, USB-C pour la recharger.",
                "Glisse la powerbank par le bas dans le module, prises vers le bas.",
                "Pose le bouchon, câbles dans ses fentes, et visse les 2 vis M3 × 12 par-dessous."]))
st.append(step("12", "Boîte sur la tête VESA",
               ["m_12_boite_sur_tete"],
               [HW("cyl", 4, 16, 4), HW("washer", 4, qty=4)],
               ["Présente la boîte contre la plaque VESA de la tête, écran vers le barreur.",
                "4 vis M4 × 16 avec rondelle par l'avant de la plaque, dans les 4 trous les plus écartés (VESA 100), "
                "jusque dans les écrous du module."]))
st.append(step("13", "Contrôles avant de naviguer",
               ["m_13_fini"], [],
               ["Tourne la tablette jusqu'aux butées (±45°) dans les deux sens : elle ne doit jamais toucher la roue.",
                "Teste l'inclinaison dans les deux sens, puis resserre les deux boutons à la main.",
                "Tire fermement la colonne vers l'arrière : rien ne doit bouger sur les pieds.",
                "Après la première sortie, resserre les colliers et les vis de pivot."], img_w=100 * mm))

# ---------------- 1:1 recap ----------------
st.append(PageBreak())
st.append(Paragraph("Visserie à l'échelle 1:1", H1))
st.append(Paragraph("Imprimer à 100 %. Pose chaque vis sur son dessin pour vérifier le diamètre et la longueur "
                    "(longueur mesurée sous la tête, tête comprise pour les fraisées).", N))
st.append(Spacer(1, 3 * mm))
# 50 mm check bar
class Ruler(Flowable):
    width, height = 60 * mm, 10 * mm

    def draw(self):
        c = self.canv
        c.setLineWidth(0.6)
        c.line(0, 3 * mm, 50 * mm, 3 * mm)
        for i in range(0, 51, 5):
            c.line(i * mm, 3 * mm, i * mm, (5 if i % 10 else 6.5) * mm)
        c.setFont("DV", 7)
        c.drawString(0, 7.5 * mm, "contrôle d'échelle : ce trait doit mesurer 50 mm")
rec = [
    ("Support", [HW("hex", 6, 45, 2), HW("hex", 6, 20, 4), HW("washer", 6, qty=2, od=18), HW("washer", 6, qty=4),
                 HW("nut", 6, qty=6), HW("nut", 8, qty=2), HW("knob", 8, 50, 1), HW("knob", 8, 45, 1)]),
    ("Boîte", [HW("csk", 4, 12, 4), HW("cyl", 4, 16, 4), HW("washer", 4, qty=4), HW("nut", 4, qty=8),
               HW("csk", 3, 10, 8), HW("csk", 3, 12, 2), HW("nut", 3, qty=10), Ruler()]),
]
for title, items in rec:
    st.append(Paragraph(title, H2))
    rows = [items[i:i + 2] for i in range(0, len(items), 2)]
    rows[-1] += [""] * (2 - len(rows[-1]))
    t = Table(rows, colWidths=[93 * mm] * 2)
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CCCCCC")),
                           ("TOPPADDING", (0, 0), (-1, -1), 4)]))
    st.append(t)

doc.build(st, onFirstPage=footer, onLaterPages=footer)
print("ok", doc.filename)
