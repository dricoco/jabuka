# Jabuka Pi box: holds the Raspberry Pi 3B in its printed "slip case" (Waveshare 3.5" LCD,
# Thingiverse 3473751 by srwilson58, CC BY-NC, printed unmodified: Body + End Cap) together with
# a Silicon Power QX55 30000 mAh power bank and the cables. GPS and DTECH stay outside, plugged
# into the Pi's USB ports at the top.
# ONE printed piece. Printer: Bambu Lab A1. Print it STANDING on its bottom wall (z- on the bed): every
# wall is vertical, no support. A small bar (printed flat) screwed over the bank's top locks it in.
# Frame (same as the slip case STL): x = width, y = depth (screen at y-, back cover at y+),
# z = up along the Pi's long side. z = 0 is the SD-card end of the slip case, x = 0 its centre,
# y = 0 its back face (feet reach y = +2). Units mm.
import os
import FreeCAD as App
import Part
from FreeCAD import Vector as V

OUT = os.getcwd()   # run from cad/pi (see build_pi.py)
BED = 256.0

# ---- slip case (measured on the STLs) ----
SL_W, SL_Y0, SL_Y1 = 61.8, -30.8, 2.0     # width, screen face, feet
SL_LEN = 87.4                             # body end face 85.8 + end cap plate 1.6 (both read on the STLs; the cap's 3.3 lip drops into the body's front recess)
SL_WIN = (-26.0, 25.0, 7.0, 85.0)         # its screen window (x0, x1, z0, z1)
SL_CLR = 0.4
# power micro-USB and HDMI are on the +x side: z 5..41, y -12..-3

# ---- power bank Silicon Power QX55 (owner's caliper: 112.12 x 72.12 x 40.64), ports on a 72 x 40.6 end ----
PB_L, PB_W, PB_T = 112.12, 72.12, 40.64
PB_CLR = 0.5

# ---- box (ONE printed piece; the bank and the slip case both slide in from the top) ----
W, WF, WB = 2.0, 2.0, 2.0   # side/bottom walls, front wall, back wall
CHAMBER = 38.0              # cable chamber height under the slip case and the bank's ports
COLUMN = 16.0               # cable column beside the bank
GAP = 2.5                   # slip-case feet to bank (3 mm foam strip, lightly squeezed)
LEDGE = 7.0                 # bank end rests on two ledges this wide (ports stay clear)
R_M3, N3_W, N3_T = 1.7, 5.9, 2.6   # M3 clearance, nut slot width and thickness (M3 x 12 countersunk + nuts, as on the tablet box)
BAR_W, BAR_T, BOSS = 12.0, 4.0, 9.0  # bar over the bank's top, held by 2 screws; boss size

# ---- derived ----
PX0, PX1 = -SL_W / 2 - SL_CLR, SL_W / 2 + SL_CLR          # pocket for the slip case
PY0, PY1 = SL_Y0 - SL_CLR, SL_Y1 + SL_CLR
GW = 2.0                                                   # guide strip between slip case and cable bay
BX0 = PX0                                                  # bank against the -x wall
BX1 = BX0 + PB_W + PB_CLR
DIV = 2.0                                                  # divider bank / cable column
XI0, XI1 = PX0, BX1 + DIV + COLUMN                         # inner x
BY0 = SL_Y1 + GAP
BY1 = BY0 + PB_T + PB_CLR
Y_BACK = BY1                                               # back wall inner face
Y_OUT = Y_BACK + WB
YF = PY0 - WF                                              # front face
Z_FLOOR = -CHAMBER
Z_BOT = Z_FLOOR - W
Z_FRONT_TOP = SL_LEN - 1.0                                 # front block top, 1 mm below the end cap: the Pi bar clamps the case
Z_TOP = PB_L - 2.0                                         # bank block top: the bank stands 2 mm proud, the bar presses on it
XO0, XO1 = XI0 - W, XI1 + W


def box(x0, x1, y0, y1, z0, z1):
    return Part.makeBox(x1 - x0, y1 - y0, z1 - z0, V(x0, y0, z0))


def prism_x(x0, x1, yz):
    """prism between x0..x1 of the (y, z) polygon"""
    pts = [V(x0, y, z) for y, z in yz]
    f = Part.Face(Part.makePolygon(pts + [pts[0]]))
    return f.extrude(V(x1 - x0, 0, 0))


def build():
    doc = App.newDocument("X35_PiBox")
    parts = {}

    b = box(XO0, XO1, YF, PY0, Z_BOT, Z_FRONT_TOP)                               # front wall
    b = b.cut(box(SL_WIN[0] - 1.5, SL_WIN[1] + 2.5, YF - 1, PY0 + 1, SL_WIN[2] - 2.0, SL_WIN[3] + 1.5))   # screen window
    b = b.fuse(box(XO0, XO1, YF, Y_OUT, Z_BOT, Z_FLOOR))                         # bottom wall
    b = b.fuse(box(XO0, XO1, Y_BACK, Y_OUT, Z_BOT, Z_TOP))                       # back wall
    for x0, x1 in ((XO0, XI0), (XI1, XO1)):                                      # side walls: full depth up to the
        b = b.fuse(box(x0, x1, YF, Y_OUT, Z_BOT, Z_FRONT_TOP))                   # front block top, then only the
        b = b.fuse(box(x0, x1, PY1, Y_OUT, Z_FRONT_TOP, Z_TOP))                  # bank block
    # slip-case pocket: rests on two columns; on +x a front strip guides it and leaves the power/HDMI
    # plugs (y > -16) free to come down with the case, already plugged in
    b = b.fuse(box(XI0, XI0 + 4.0, PY0, PY1, Z_FLOOR, 0))                        # column a (-x)
    b = b.fuse(box(PX1 - 4.0, PX1 + GW, PY0, -20.0, Z_FLOOR, 0))                 # column b (+x, front only: the chamber stays open behind)
    b = b.fuse(box(PX1, PX1 + GW, PY0, -16.0, 0, Z_FRONT_TOP))                   # guide strip
    # bank: front rails (it must not push on the Pi case), two end ledges, divider
    b = b.fuse(box(XI0, XI0 + 3.0, PY1, BY0, Z_FLOOR, Z_TOP))                    # rail -x
    b = b.fuse(box(BX1 - LEDGE, BX1 + DIV, PY1, BY0, Z_FLOOR, Z_TOP))            # rail +x (foot of the divider)
    b = b.fuse(box(BX1, BX1 + DIV, BY0, Y_BACK, Z_FLOOR, Z_TOP))                 # divider bank / cable column
    b = b.fuse(box(BX0 + LEDGE - 1.6, BX0 + LEDGE, BY0, BY1, Z_FLOOR, 0))        # ledge -x: a rib, the bank end sits on its top edge
    b = b.fuse(box(BX1 - LEDGE, BX1 - LEDGE + 1.6, BY0, BY1, Z_FLOOR, 0))        # ledge +x
    # slip-case lock: a bar across the front band of the end cap (8.5 mm without connectors), 2 x M3 x 12 into captive nuts
    yp, zp = -27.0, Z_FRONT_TOP
    xpa, xpb = XO0 - BOSS / 2, PX1 + GW + 6.0
    boss = Part.Face(Part.makePolygon([V(XO0, yp - 5, zp), V(XO0 - BOSS, yp - 5, zp), V(XO0 - BOSS, yp - 5, zp - 8.0),
                                       V(XO0, yp - 5, zp - 8.0 - BOSS), V(XO0, yp - 5, zp)]))
    b = b.fuse(boss.extrude(V(0, 10, 0)))                                        # boss outside the -x wall, 45 deg underneath
    b = b.fuse(box(PX1 + GW, XI1, PY0, yp + 5, zp - 8.0, zp))                    # boss bridging the cable bay, behind the front wall
    for x in (xpa, xpb):
        b = b.cut(Part.makeCylinder(R_M3, 12.0, V(x, yp, zp - 12.0), V(0, 0, 1)))
    b = b.cut(box(XO0 - BOSS - 1, xpa + N3_W / 2, yp - N3_W / 2, yp + N3_W / 2, zp - 3.0 - N3_T, zp - 3.0))   # nut slot, open to the outside
    b = b.cut(box(xpb - N3_W / 2, xpb + N3_W / 2, yp - N3_W / 2, yp + 6, zp - 3.0 - N3_T, zp - 3.0))          # nut slot, open to the back of the bay
    # openings: vents (vertical slots), hand holes into the cable chamber, back windows
    for y in (-27.0, -22.0):
        b = b.cut(box(XO0 - 1, XI0 + 0.1, y, y + 3.0, 15.0, 60.0))               # slip-case side vents (-x)
    b = b.cut(box(XO0 - 1, XI0 + 0.1, BY0 + 6.0, BY1 - 6.0, 12.0, 86.0))         # bank window (-x), below the bar boss
    b = b.cut(box(XI1 - 0.1, XO1 + 1, BY0 + 6.0, BY1 - 6.0, 12.0, 100.0))        # cable column window (+x)
    b = b.cut(box(XI1 - 0.1, XO1 + 1, -27.0, -3.0, 5.0, 74.0))                   # cable bay window (+x)
    b = b.cut(box(PX1 + GW + 2.0, XI1 - 2.0, YF - 1, PY0 + 1, 5.0, 74.0))        # cable bay window (front)
    for y0, y1 in ((-26.0, 4.0), (10.0, 40.0)):
        b = b.cut(box(XI1 - 0.1, XO1 + 1, y0, y1, -33.0, -6.0))                  # hand holes (+x): reach the bank's ports, charging cable exit
    for x0, x1 in ((XI0 + 6.0, 10.0), (16.0, XI1 - 6.0)):
        b = b.cut(box(x0, x1, YF - 1, PY0 + 1, -33.0, -8.0))                     # chamber windows (front)
    for z0, z1 in ((8.0, 50.0), (56.0, 102.0)):
        b = b.cut(box(BX0 + 8.0, BX1 - 8.0, Y_BACK - 0.1, Y_OUT + 1, z0, z1))    # back windows (less plastic, bank cooling)
        b = b.cut(box(BX1 + DIV + 2.0, XI1 - 2.0, Y_BACK - 0.1, Y_OUT + 1, z0, z1))   # same behind the cable column
    # bank lock: a bar across the bank's top, 2 x M3 x 12 into captive nuts (bosses 0.5 mm below the bank's top: the bar clamps it)
    ym, zt = (BY0 + BY1) / 2, PB_L - 0.5
    xa, xb = XO0 - BOSS / 2, (BX1 + DIV + XI1) / 2
    boss = Part.Face(Part.makePolygon([V(XO0, ym - 5, zt), V(XO0 - BOSS, ym - 5, zt), V(XO0 - BOSS, ym - 5, zt - 8.0),
                                       V(XO0, ym - 5, zt - 8.0 - BOSS), V(XO0, ym - 5, zt)]))
    b = b.fuse(boss.extrude(V(0, 10, 0)))                                        # boss outside the -x wall, 45 deg underneath
    b = b.fuse(box(BX1 + DIV, XI1, ym - 5, ym + 5, zt - 8.0, zt))                # boss bridging the cable column
    b = b.fuse(box(XO0, XI0, ym - 5, ym + 5, Z_TOP - 0.1, zt))                   # wall tops raised under the bar
    for x in (xa, xb):
        b = b.cut(Part.makeCylinder(R_M3, 12.0, V(x, ym, zt - 12.0), V(0, 0, 1)))
    b = b.cut(box(XO0 - BOSS - 1, xa + N3_W / 2, ym - N3_W / 2, ym + N3_W / 2, zt - 3.0 - N3_T, zt - 3.0))   # nut slot, open to the outside
    b = b.cut(box(xb - N3_W / 2, xb + N3_W / 2, ym - 6, ym + N3_W / 2, zt - 3.0 - N3_T, zt - 3.0))           # nut slot, open to the front of the column
    parts["Boitier"] = b.removeSplitter()

    bar = box(XO0 - BOSS, XI1, ym - BAR_W / 2, ym + BAR_W / 2, PB_L, PB_L + BAR_T)
    for x in (xa, xb):
        bar = bar.cut(Part.makeCylinder(R_M3, BAR_T + 2, V(x, ym, PB_L - 1), V(0, 0, 1)))
        bar = bar.cut(Part.makeCone(R_M3, 3.1, 1.4, V(x, ym, PB_L + BAR_T - 1.4), V(0, 0, 1)))   # countersink
    parts["Barre_powerbank"] = bar

    bp = box(XO0 - BOSS, xpb + 6.0, PY0 + 0.3, yp + 4.0, SL_LEN + 0.2, SL_LEN + 0.2 + BAR_T)
    for x in (xpa, xpb):
        bp = bp.cut(Part.makeCylinder(R_M3, BAR_T + 2, V(x, yp, SL_LEN - 1), V(0, 0, 1)))
        bp = bp.cut(Part.makeCone(R_M3, 3.1, 1.4, V(x, yp, SL_LEN + 0.2 + BAR_T - 1.4), V(0, 0, 1)))   # countersink
    parts["Barre_pi"] = bp

    # ---------------- dummies ----------------
    dummies = {
        "Slip_case": box(-SL_W / 2, SL_W / 2, SL_Y0, SL_Y1, 0, SL_LEN),
        "Ecran": box(SL_WIN[0], SL_WIN[1], SL_Y0 - 0.3, SL_Y0, SL_WIN[2], SL_WIN[3]),      # what shows through the slip case window
        "Powerbank": box(BX0 + PB_CLR / 2, BX0 + PB_CLR / 2 + PB_W, BY0 + PB_CLR / 2, BY0 + PB_CLR / 2 + PB_T, 0, PB_L),
        "Fiche_micro_USB": box(SL_W / 2, SL_W / 2 + 22.0, -11.0, -4.0, 5.0, 16.0),
        "Fiches_USB_powerbank": box(BX0 + LEDGE + 1, BX1 - LEDGE - 1, BY0 + 6, BY1 - 6, -30.0, 0),
    }

    printed = doc.addObject("App::DocumentObjectGroup", "Pieces_imprimees")
    for n, sh in parts.items():
        o = doc.addObject("Part::Feature", n)
        o.Shape = sh
        printed.addObject(o)
    dg = doc.addObject("App::DocumentObjectGroup", "Gabarits")
    for n, sh in dummies.items():
        o = doc.addObject("Part::Feature", n)
        o.Shape = sh
        dg.addObject(o)
    doc.recompute()

    rep = {}
    hits = []
    allp = list(parts.items()) + list(dummies.items())
    for i in range(len(allp)):
        for j in range(i + 1, len(allp)):
            v = allp[i][1].common(allp[j][1]).Volume
            if v > 0.5 and "Ecran" not in (allp[i][0], allp[j][0]):
                hits.append((allp[i][0], allp[j][0], round(v, 1)))
    rep["hits"] = hits
    rep["solids"] = {n: (len(sh.Solids), sh.isValid()) for n, sh in parts.items()}
    rep["bbox"] = {n: [round(d, 1) for d in (sh.BoundBox.XLength, sh.BoundBox.YLength, sh.BoundBox.ZLength)]
                   for n, sh in parts.items()}
    rep["fits_A1"] = all(max(sh.BoundBox.XLength, sh.BoundBox.YLength, sh.BoundBox.ZLength) <= BED - 6 for sh in parts.values())
    rep["outer_WxDxH"] = (round(XO1 - XO0, 1), round(Y_OUT - YF, 1), round(Z_TOP - Z_BOT, 1))
    rep["cable_bay_beside_pi"] = (round(XI1 - PX1 - GW, 1), round(PY1 - PY0, 1), round(Z_FRONT_TOP, 1))
    rep["cable_column_beside_bank"] = (COLUMN, round(Y_BACK - BY0, 1), round(Z_TOP - Z_FLOOR, 1))
    rep["bank_proud_of_walls"] = round(PB_L - Z_TOP, 1)
    rep["chamber_height"] = CHAMBER
    rep["volume_cm3"] = {n: round(sh.Volume / 1000, 1) for n, sh in parts.items()}
    return doc, parts, rep


doc, parts, rep = build()
for k, v in rep.items():
    print(k, "=", v)
