# X35 Jefa A-frame pedestal - COMPACT 3D-printable swivelling tablet mount (v2)
# Printer: Bambu Lab A1 (256 x 256 x 256). Material: PETG / PETG-CF (ASA if UV matters).
# Frame: origin = cockpit floor under wheel centre, x = starboard, y = aft
# (towards helmsman), z = up. Wheel plane y = 0. Units mm.
# Pedestal numbers scaled from Jefa drawing x35-web-8.gif -> [MEASURE] on boat.
import math
import FreeCAD as App
import Part
from FreeCAD import Vector as V, Placement, Rotation

import os
OUT = os.getcwd()   # run from cad/support (see build_support.py)
BED = 256.0

# ---------------- pedestal (reference) ----------------
H_SHAFT = 600.0
R_WHEEL = 750.0
WHEEL_HALF = 40.0    # half thickness wheel+hub envelope [MEASURE]
LEG_Y = 70.0         # A-frame leg centre plane from wheel plane [MEASURE]
LEG_R = 20.0         # leg Ø40 [MEASURE]
LEG_X0 = 262.0       # leg centre x at floor [MEASURE]
LEG_SLOPE = 0.357    # dx/dz [MEASURE]
HUB_R = 45.0         # hub housing radius [MEASURE]
# ---------------- mount ----------------
SIDE = +1
CLEAR = 25.0         # min clearance tablet <-> wheel envelope
# ---- adjustable base (v5): no on-board measurement needed before printing ----
P_SER = 1.5          # serration pitch slider/beam (crans)
SER_H = 0.6          # serration depth
XS = round((LEG_X0 - LEG_SLOPE * 510.0) / P_SER) * P_SER   # nominal slider x (on the serration grid)
Z_CLAMP = (LEG_X0 - XS) / LEG_SLOPE                        # ~511: clamp height on the aft legs
CR_W, CR_L, CR_DEPTH = 32.0, 25.0, 26.0   # V cradle half width, half length (along leg), V depth
S_T = 10.0           # slider body thickness (y)
DT_D_G, DT_W0, DT_W1, DT_C = 6.0, 10.0, 14.0, 0.5   # dovetail groove depth, half widths face/bottom, clearance
GAP_S = 0.5          # slider body to beam face
XBEAM, HB, BEAM_T = 124.0, 24.0, 22.0
SLOT_X = (52.0, 108.0)   # lock slot -> leg spacing c-c 104..216
NUT_AF, NUT_T, NUT_W = 10.0, 5.5, 10.4   # M6 nut (DIN 934): across flats, pocket height, pocket width
TBW = 45.0           # centre table half width (column foot)
COL_ADJ = 30.0       # column aft adjustment range (option 4)
RUB = 1.5            # TPU liner
WALL = 8.0
FRONT_T = 4.0        # front shell thickness (the only part between leg and wheel) [CHECK GAP]
EAR = 22.0
CL_L = 44.0
BRIDGE_T = 20.0
H_T = 730.0          # tablet centre = tilt axis height
TAB_W, TAB_H, TAB_D = 247.0, 200.0, 37.5   # tablet box outer, cap included, symmetric
LIFT_MAX = 6.0       # max free play with knob fully loose (nyloc above knob)
STOP_PLAY = 3.0      # design margin: hard stop is at most this past the last notch
VESA_T = 6.0
TILT_ARM = 35.0      # tilt axis -> back of VESA plate
TILT_MAX = 15.0
YAW_MAX = 45.0       # physical stop
STEM_SWEEP = 76.0    # half angle of the fwd stop-ring cut-out (yaw 45 + stem half width 24 + margin)
N_TEETH = 24         # Hirth, 15 deg steps
Z_Y = H_T - 130.0    # yaw mating plane

TH = math.atan(LEG_SLOPE)
THD = math.degrees(TH)
RB = LEG_R + RUB
XO = RB + WALL
Y_EAR = LEG_Y + RB + EAR          # bridge front face
Y_BR = Y_EAR + BRIDGE_T           # bridge rear face


def tablet_min_y(yaw, tilt):
    m = 1e9
    t, a = math.radians(tilt), math.radians(yaw)
    for x in (-TAB_W / 2, TAB_W / 2):
        for y in (TILT_ARM + VESA_T, TILT_ARM + VESA_T + TAB_D):
            for z in (-TAB_H / 2, TAB_H / 2):
                yt = y * math.cos(t) - z * math.sin(t)
                m = min(m, x * math.sin(a) + yt * math.cos(a))
    return m


_ys, _ts = YAW_MAX + STOP_PLAY, TILT_MAX + STOP_PLAY
MINY = min(tablet_min_y(a, t) for a in (-_ys, 0, _ys) for t in (-_ts, 0, _ts))
YA = math.ceil((WHEEL_HALF + CLEAR - MINY) / 5.0) * 5.0


def box(x0, x1, y0, y1, z0, z1):
    return Part.makeBox(x1 - x0, y1 - y0, z1 - z0, V(x0, y0, z0))


def cyl(r, h, base, d=V(0, 0, 1)):
    return Part.makeCylinder(r, h, base, d)


def tube(ro, ri, h, base, d=V(0, 0, 1)):
    return cyl(ro, h, base, d).cut(cyl(ri, h, base, d))


def baked(shape, pl):
    s = shape.copy()
    s.transformShape(pl.toMatrix())
    return s


def legx(z):
    return LEG_X0 - LEG_SLOPE * z


def clamp_pl(sx, zc):
    return Placement(V(sx * legx(zc), LEG_Y, zc), Rotation(V(0, 1, 0), -sx * THD))


def hexprism(af, h, base, d):
    r = af / math.sqrt(3) + 0.15
    pts = [V(r * math.cos(math.radians(60 * i + 30)), r * math.sin(math.radians(60 * i + 30)), 0) for i in range(7)]
    s = Part.Face(Part.makePolygon(pts)).extrude(V(0, 0, h))
    return baked(s, Placement(base, Rotation(V(0, 0, 1), d)))


def hull2d(pts):
    pts = sorted(set(pts))
    cr = lambda o, a, b: (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])
    lo, up = [], []
    for p in pts:
        while len(lo) >= 2 and cr(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(up) >= 2 and cr(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    return lo[:-1] + up[:-1]


def hirth(ro, H, T, center, d, twist=0.0, N=N_TEETH):
    """Hirth face coupling. Mating plane through `center`, teeth point along d,
    body extends T behind the plane. Flanks are planes through the axis point."""
    body = cyl(ro, T + H, V(0, 0, -T))
    body = body.cut(Part.makeCone(0, 3 * ro, 1.5 * H, V(0, 0, 0)))
    Rb = 1.3 * ro
    sb = (H / 2) * Rb / ro
    O = V(0, 0, 0)
    g = []
    for k in range(N):
        phi, dd = (k + 0.5) * 2 * math.pi / N, math.pi / N
        T1 = V(Rb * math.cos(phi - dd), Rb * math.sin(phi - dd), sb)
        T2 = V(Rb * math.cos(phi + dd), Rb * math.sin(phi + dd), sb)
        B = V(Rb * math.cos(phi), Rb * math.sin(phi), -sb)
        fs = [Part.Face(Part.makePolygon([a, b, c, a])) for a, b, c in ((O, T1, B), (O, B, T2), (O, T2, T1), (T1, T2, B))]
        s = Part.Solid(Part.Shell(fs))
        if s.Volume < 0:
            s.reverse()
        g.append(s)
    body = body.cut(Part.makeCompound(g))
    body = baked(body, Placement(V(), Rotation(V(0, 0, 1), twist)))
    return baked(body, Placement(center, Rotation(V(0, 0, 1), d)))


def build():
    if "X35_TabletMount_v2" in App.listDocuments():
        App.closeDocument("X35_TabletMount_v2")
    doc = App.newDocument("X35_TabletMount_v2")
    ref = doc.addObject("App::DocumentObjectGroup", "Reference_Pedestal")
    prt = doc.addObject("App::DocumentObjectGroup", "Printed_Parts")
    hw = doc.addObject("App::DocumentObjectGroup", "Hardware")
    tabg = doc.addObject("App::DocumentObjectGroup", "Tablet")

    def add(name, shape, grp, color, transp=0):
        o = doc.addObject("Part::Feature", name)
        o.Shape = shape
        grp.addObject(o)
        if App.GuiUp:
            o.ViewObject.ShapeColor = color
            o.ViewObject.Transparency = transp
        return o

    PLA, ORA, DARK, RUBC, SS = (0.25, 0.25, 0.28), (0.95, 0.55, 0.1), (0.1, 0.1, 0.1), (0.15, 0.15, 0.15), (0.7, 0.7, 0.75)
    GREY = (0.85, 0.85, 0.85)

    # ---- reference pedestal ----
    Lg = (H_SHAFT - HUB_R) / math.cos(TH)
    for fy in (LEG_Y, -LEG_Y):
        tag = 'aft' if fy > 0 else 'fwd'
        for sx in (1, -1):
            pl = Placement(V(sx * LEG_X0, fy, 0), Rotation(V(0, 1, 0), -sx * THD))
            add(f"Leg_{tag}_{'S' if sx>0 else 'P'}", baked(cyl(LEG_R, Lg, V()), pl), ref, GREY, 40)
            add(f"Foot_{tag}_{'S' if sx>0 else 'P'}", box(sx*LEG_X0-57, sx*LEG_X0+57, fy-30, fy+30, 0, 8), ref, GREY, 40)
        add(f"Hub_{tag}", cyl(HUB_R, 40, V(0, fy - 20, H_SHAFT), V(0, 1, 0)), ref, GREY, 40)
    add("Shaft", cyl(12.5, 220, V(0, -110, H_SHAFT), V(0, 1, 0)), ref, SS, 40)
    wheel = cyl(R_WHEEL, 2 * WHEEL_HALF, V(0, -WHEEL_HALF, H_SHAFT), V(0, 1, 0))
    wo = add("Wheel_Envelope_KEEPOUT", wheel, ref, (1.0, 0.2, 0.2), 85)

    ms = Placement() if SIDE > 0 else Placement(V(), Rotation(V(0, 0, 1), 180))
    parts = {}

    print('STAGE', '# ================= 1. ADJUSTABLE BASE', flush=True)
    # ---- V cradle (local frame: origin on the leg axis at Z_CLAMP, z along the leg, y aft) ----
    # rubber (inner tube) 1.5 mm on the V faces; a stainless hose clamp goes round the leg front,
    # along the cradle sides and through the two tunnels behind the V apex.
    y_ap = RB * math.sqrt(2)
    yf, yb = y_ap - CR_DEPTH, y_ap + 9.0
    cr = box(-CR_W, CR_W, yf, yb, -CR_L, CR_L)
    vprof = Part.Face(Part.makePolygon([V(0, y_ap, -CR_L - 1), V(80, y_ap - 80, -CR_L - 1),
                                        V(-80, y_ap - 80, -CR_L - 1), V(0, y_ap, -CR_L - 1)]))
    cr = cr.cut(vprof.extrude(V(0, 0, 2 * CR_L + 2)))
    for zt in (-14.0, 14.0):
        cr = cr.cut(box(-CR_W - 1, CR_W + 1, y_ap + 1.5, y_ap + 4.5, zt - 6.5, zt + 6.5))   # band tunnels
    try:
        eds = [e for e in cr.Edges if abs((e.Vertexes[1].Point - e.Vertexes[0].Point).normalize().z) > 0.99
               and abs(abs(e.Vertexes[0].Point.x) - CR_W) < 1e-6 and abs(e.Vertexes[0].Point.y - yf) < 1e-6]
        cr = cr.makeFillet(4.0, eds)
    except Exception as ex:
        print("fillet skipped", ex)
    for zt in (-14.0, 14.0):              # 1 mm guide grooves for the band on both side walls (no sideways creep)
        for xs_ in (-1, 1):
            cr = cr.cut(box(xs_ * CR_W - 1.0, xs_ * CR_W + 1.0, yf - 1, y_ap + 4.5, zt - 6.5, zt + 6.5))
    cr = cr.fuse(cyl(7.0, 8.0, V(0, yb, 0), V(0, 1, 0)))                     # pivot pin
    cr = cr.cut(cyl(3.3, yb + 8.01 - (y_ap + 1.0), V(0, y_ap + 1.0, 0), V(0, 1, 0)))  # M6 clearance bore (pin + body)
    cr = cr.cut(box(-NUT_AF / 2 - 1.0, CR_W + 1, yb - NUT_T, yb, -NUT_W / 2, NUT_W / 2))  # captive M6 nut, side slot (+x)
    # ---- slider (global orientation, origin at (x_slider, LEG_Y, Z_CLAMP)) ----
    ys1 = yb + S_T
    yfb = ys1 + GAP_S                     # beam front face (local)
    ygb = yfb + DT_D_G                    # groove bottom
    k = (DT_W1 - DT_W0) / DT_D_G
    sl = box(-22, 22, yb, ys1, -20, 20)
    tprof = [V(-22, ys1, -(DT_W0 - DT_C - k * GAP_S)), V(-22, ygb, -(DT_W1 - DT_C)),
             V(-22, ygb, DT_W1 - DT_C), V(-22, ys1, DT_W0 - DT_C - k * GAP_S)]
    sl = sl.fuse(Part.Face(Part.makePolygon(tprof + [tprof[0]])).extrude(V(44, 0, 0)))
    zr = DT_W1 - DT_C - 1.0

    def teeth(x0, x1, y0, sgn, zh):
        g = []
        n0, n1 = math.ceil(x0 / P_SER - 0.5), math.floor(x1 / P_SER - 0.5)
        for j in range(n0, n1 + 1):
            xa = (j + 0.5) * P_SER - P_SER / 2
            f = Part.Face(Part.makePolygon([V(xa, y0, -zh), V(xa + P_SER, y0, -zh), V(xa + P_SER / 2, y0 + sgn * SER_H, -zh), V(xa, y0, -zh)]))
            g.append(f.extrude(V(0, 0, 2 * zh)))
        return g
    liners = []
    sl_hole = cyl(3.3, 40, V(0, yb - 1, 0), V(0, 1, 0))
    sl_pin = cyl(7.25, S_T + 0.5, V(0, yb - 0.5, 0), V(0, 1, 0))
    # ---- beam (global) with dovetail groove + serrations + lock slots + centre table ----
    Y0 = LEG_Y + yfb
    YG = LEG_Y + ygb
    beam = box(-XBEAM, XBEAM, Y0, Y0 + BEAM_T, Z_CLAMP - HB, Z_CLAMP + HB)
    Y_TB1 = YA + 26.0
    beam = beam.fuse(box(-TBW, TBW, Y0, Y_TB1, Z_CLAMP - HB, Z_CLAMP + HB))
    gprof = [V(-XBEAM - 1, Y0 - 1, Z_CLAMP - (DT_W0 - k)), V(-XBEAM - 1, YG, Z_CLAMP - DT_W1),
             V(-XBEAM - 1, YG, Z_CLAMP + DT_W1), V(-XBEAM - 1, Y0 - 1, Z_CLAMP + DT_W0 - k)]
    beam = beam.cut(Part.Face(Part.makePolygon(gprof + [gprof[0]])).extrude(V(2 * XBEAM + 2, 0, 0)))
    notch = Part.makeCompound([baked(t, Placement(V(0, 0, Z_CLAMP), Rotation())) for t in teeth(-XBEAM, XBEAM, YG, +1, zr)])
    beam = beam.cut(notch)
    for sx in (1, -1):
        xa, xb_ = sorted((sx * SLOT_X[0], sx * SLOT_X[1]))
        beam = beam.cut(box(xa - 3.3, xb_ + 3.3, YG - 1, Y0 + BEAM_T + 1, Z_CLAMP - 3.3, Z_CLAMP + 3.3))
    YB_BOLTS = (YA - 6.0, YA + 18.0)
    for x in (-36.0, 36.0):
        for yb_ in YB_BOLTS:
            beam = beam.cut(cyl(3.3, 14.0, V(x, yb_, Z_CLAMP + HB - 14.0)))                  # M6 bolt bore (column foot)
            xs0, xs1 = sorted((x - math.copysign(NUT_AF / 2 + 1.0, x), math.copysign(TBW + 1.0, x)))
            beam = beam.cut(box(xs0, xs1, yb_ - NUT_W / 2, yb_ + NUT_W / 2,
                                Z_CLAMP + HB - 3.5 - NUT_T, Z_CLAMP + HB - 3.5))       # captive M6 nut, side slot
    parts["Poutre"] = (beam.removeSplitter(), ORA)
    bands = {}
    for sx in (1, -1):
        tag = 'S' if sx > 0 else 'P'
        xs = sx * XS
        parts[f"Berceau_{tag}"] = (baked(cr, clamp_pl(sx, Z_CLAMP)), ORA)
        sll = sl.fuse(Part.makeCompound(teeth(-22 + P_SER, 22 - P_SER, ygb, +1, zr))).cut(sl_hole).cut(sl_pin)
        parts[f"Coulisseau_{tag}"] = (baked(sll, Placement(V(xs, LEG_Y, Z_CLAMP), Rotation())).removeSplitter(), ORA)
        for i, zt in enumerate((-14.0, 14.0)):
            bnd = tube(LEG_R + 0.8, LEG_R, 12.0, V(0, 0, zt - 6.0)).common(box(-30, 30, -30, 0, -60, 60))
            bands[f"Collier_inox_{tag}{i+1}"] = (baked(bnd, clamp_pl(sx, Z_CLAMP)), SS)

    print('STAGE', '# ================= 2. COLUMN', flush=True)
    # ================= 2. COLUMN (riser + lower yaw Hirth + stop ring) =================
    ZF0 = Z_CLAMP + HB
    col = box(-TBW, TBW, YA - 42, YA + 24, ZF0, ZF0 + 10)                               # foot on the beam table
    col = col.fuse(box(-28, 28, YA - 22, YA + 22, ZF0, Z_Y - 10))
    col = col.fuse(cyl(38, 8.5, V(0, YA, Z_Y - 10)))                                  # flange to z_y-1.5
    col = col.fuse(hirth(28, 3.0, 10, V(0, YA, Z_Y), V(0, 0, 1)))
    ring = tube(37, 31, 17.5, V(0, YA, Z_Y - 1.5))                                  # wall to z_y+16 (> LIFT_MAX + overlap)
    lug_half = 11.0
    a0, a1 = 90 - YAW_MAX - lug_half, 90 + YAW_MAX + lug_half                         # free sector (aft)
    wedge = Part.Face(Part.makePolygon([V(0, YA, 0)] + [V(60 * math.cos(math.radians(a)), YA + 60 * math.sin(math.radians(a)), 0)
                                        for a in (a0, (a0 + a1) / 2 - 20, (a0 + a1) / 2, (a0 + a1) / 2 + 20, a1)] + [V(0, YA, 0)]))
    wedge = wedge.extrude(V(0, 0, 1)).copy()
    wedge = baked(Part.Face(Part.makePolygon([V(0, YA, Z_Y - 3)] + [V(60 * math.cos(math.radians(a)), YA + 60 * math.sin(math.radians(a)), Z_Y - 3)
                  for a in (a0, (a0 + a1) / 2 - 20, (a0 + a1) / 2, (a0 + a1) / 2 + 20, a1)] + [V(0, YA, Z_Y - 3)])).extrude(V(0, 0, 20)), Placement())
    f0, f1 = 270 - STEM_SWEEP, 270 + STEM_SWEEP                                     # fwd sector swept by the tower stem
    wedge_f = Part.Face(Part.makePolygon([V(0, YA, Z_Y - 3)] + [V(60 * math.cos(math.radians(a)), YA + 60 * math.sin(math.radians(a)), Z_Y - 3)
                        for a in (f0, (f0 + f1) / 2 - 40, (f0 + f1) / 2, (f0 + f1) / 2 + 40, f1)] + [V(0, YA, Z_Y - 3)])).extrude(V(0, 0, 20))
    col = col.fuse(ring.cut(wedge).cut(wedge_f))                                       # ring kept only at the two stop sectors
    col = col.cut(cyl(4.25, 60, V(0, YA, Z_Y - 50)))                                   # M8 yaw bolt
    col = col.cut(hexprism(13, 7, V(0, YA, Z_Y - 32), V(0, 0, 1)))                    # nut pocket
    col = col.cut(box(-7.7, 40, YA - 6.8, YA + 6.8, Z_Y - 32, Z_Y - 25))              # nut insert slot (+x)
    for x in (-36.0, 36.0):                                                          # fore-aft slots 0..+30
        col = col.cut(box(x - 3.3, x + 3.3, YB_BOLTS[0] - COL_ADJ - 3.3, YB_BOLTS[1] + 3.3, ZF0 - 1, ZF0 + 11))
    parts["Column"] = (col.removeSplitter(), ORA)

    print('STAGE', '# ================= 3. TOWER', flush=True)
    # ================= 3. TOWER (rotates in yaw) =================
    tw = hirth(28, 3.0, 14, V(0, YA, Z_Y), V(0, 0, -1), twist=180.0 / N_TEETH)
    tw = tw.fuse(box(-6, 6, YA + 27.5, YA + 36, Z_Y + 1.8, Z_Y + 15))                   # yaw stop lug (aft)
    tw = tw.fuse(box(-14, 14, YA - 41, YA - 17, Z_Y + 17, H_T + 36))                  # stem (fwd of axis, above stop ring)
    tw = tw.fuse(box(-14, 14, YA - 41, YA - 17, Z_Y + 2, Z_Y + 18))                   # stem root: full stem section down onto the disc
    for zs in (1, -1):                                                                # tilt stop blocks
        z0, z1 = sorted((H_T + zs * 17, H_T + zs * 35))
        tw = tw.fuse(box(13, 28, YA - 41, YA - 24, z0, z1))
    tw = tw.fuse(cyl(22, 28, V(-14, YA, H_T), V(1, 0, 0)))                            # tilt boss
    tw = tw.fuse(box(-14, 14, YA - 41, YA, H_T - 22, H_T))
    tw = tw.cut(cyl(23, 4, V(12.5, YA, H_T), V(1, 0, 0)))                            # make room, re-add teeth
    tw = tw.fuse(hirth(22, 3.0, 6, V(14, YA, H_T), V(1, 0, 0)))
    tw = tw.cut(cyl(4.25, 30, V(0, YA, Z_Y - 1)))                                     # yaw bolt
    tw = tw.cut(cyl(4.25, 60, V(-30, YA, H_T), V(1, 0, 0)))                           # tilt bolt
    parts["Tower"] = (tw.removeSplitter(), ORA)

    print('STAGE', '# ================= 4. VESA HEAD', flush=True)
    # ================= 4. VESA HEAD (tilts) =================
    vh = hirth(22, 3.0, 14, V(14, YA, H_T), V(-1, 0, 0), twist=180.0 / N_TEETH)
    yv = YA + TILT_ARM
    vh = vh.fuse(box(15.6, 28, YA, yv, H_T - 20, H_T + 20))
    vh = vh.fuse(box(15.6, 28, YA - 38, YA - 15, H_T - 6, H_T + 6))                   # tilt stop tail
    vesa = box(-60, 60, yv, yv + VESA_T, H_T - 60, H_T + 60)
    for s_ in (75, 100):
        for dx in (-1, 1):
            for dz in (-1, 1):
                vesa = vesa.cut(cyl(2.25, 10, V(dx * s_ / 2, yv - 1, H_T + dz * s_ / 2), V(0, 1, 0)))
    vesa = vesa.cut(cyl(9, 10, V(-30, yv - 1, H_T - 25), V(0, 1, 0)))               # cable
    vh = vh.fuse(vesa)
    for zz in (-1, 1):                                                                 # gussets arm->plate
        g = Part.Face(Part.makePolygon([V(14, yv - 20, H_T + zz * 20), V(14, yv, H_T + zz * 20),
                                        V(14, yv, H_T + zz * 45), V(14, yv - 20, H_T + zz * 20)])).extrude(V(14, 0, 0))
        g = g.common(box(15.6, 28, -1e4, 1e4, -1e4, 1e4))
        vh = vh.fuse(g)
    vh = vh.cut(cyl(4.25, 60, V(-30, YA, H_T), V(1, 0, 0)))
    vh = vh.cut(hexprism(13, 7, V(28 - 6.9, YA, H_T), V(1, 0, 0)))                    # M8 nut trap
    parts["VESA_Head"] = (vh.removeSplitter(), ORA)

    print('STAGE', '# ---- hardware ----', flush=True)
    # ---- hardware ----
    hwp = dict(bands)
    hwp.update({
        "Knob_yaw_M8": (cyl(4, 45, V(0, YA, Z_Y - 30)).fuse(cyl(16, 14, V(0, YA, Z_Y + 14.2))), DARK),
        "Knob_tilt_M8": (cyl(4, 50, V(-36, YA, H_T), V(1, 0, 0)).fuse(cyl(16, 14, V(-28.2, YA, H_T), V(-1, 0, 0))), DARK),
    })
    tablet = box(-TAB_W / 2, TAB_W / 2, yv + VESA_T, yv + VESA_T + TAB_D, H_T - TAB_H / 2, H_T + TAB_H / 2)

    # ---- assemble with yaw / tilt ----
    yaw_set = {"Tower", "Knob_yaw_M8"}
    tilt_set = {"VESA_Head", "Knob_tilt_M8", "Tablet"}
    allp = dict(parts)
    allp.update(hwp)
    allp["Tablet"] = (tablet, (0.1, 0.3, 0.6))

    def posed(name, yaw=0.0, tilt=0.0, ly=0.0, lt=0.0):
        """ly = yaw joint lift (z), lt = tilt joint lift (+x) - i.e. knob loosened"""
        s = allp[name][0]
        if name in tilt_set:
            s = baked(s, Placement(V(lt, 0, 0), Rotation()))
            s = baked(s, Placement(V(), Rotation(V(1, 0, 0), tilt), V(0, YA, H_T)))
        if name in yaw_set or name in tilt_set:
            s = baked(s, Placement(V(0, 0, ly), Rotation()))
            s = baked(s, Placement(V(), Rotation(V(0, 0, 1), yaw), V(0, YA, 0)))
        return baked(s, ms)

    def stop_angle(kind, lift):
        """first angle (0.5 deg steps) where the hard stop contacts, joint lifted by `lift`"""
        a = (YAW_MAX if kind == "yaw" else TILT_MAX) - 1.0
        while a < 90:
            a += 0.5
            if kind == "yaw":
                v = posed("Tower", a, 0, ly=lift).common(posed("Column")).Volume
            else:
                v = posed("VESA_Head", 0, a, lt=lift).common(posed("Tower")).Volume
            if v > 0.5:
                return a
        return None

    for n, (s, c) in allp.items():
        grp = prt if n in parts else (tabg if n == "Tablet" else hw)
        add(n, posed(n), grp, c, 50 if n == "Tablet" else 0)
    for n, s in liners:
        add(n, baked(s, ms), hw, RUBC)
    gh = doc.addObject("App::DocumentObjectGroup", "Ghost_yaw_45")
    for a in (YAW_MAX, -YAW_MAX):
        add(f"Ghost_Tablet_{int(a)}", posed("Tablet", a), gh, (0.1, 0.3, 0.6), 80)

    print('STAGE', '# ---- checks ----', flush=True)
    # ---- checks ----
    rep = dict(YA=YA, tablet_front_y=round(YA + TILT_ARM + VESA_T + TAB_D, 1))
    keep = wheel
    for o in ref.Group:
        if o.Name.startswith(("Leg", "Hub", "Shaft")):
            keep = keep.fuse(o.Shape)
    moving = ["Tower", "VESA_Head", "Tablet", "Knob_yaw_M8", "Knob_tilt_M8"]
    hits, mind = [], 1e9
    for a in range(-int(YAW_MAX), int(YAW_MAX) + 1, 15):
        for t in (-TILT_MAX, 0, TILT_MAX):
            P = {n: posed(n, a, t) for n in moving}
            for n, s in P.items():
                if s.common(keep).Volume > 1e-3:
                    hits.append((n, "pedestal/wheel", a, t))
            mind = min(mind, P["Tablet"].distToShape(wheel)[0])
            for n in ("Tablet", "VESA_Head"):
                for f in ("Column", "Poutre"):
                    if P[n].common(posed(f)).Volume > 1e-3:
                        hits.append((n, f, a, t))
            for n in ("Tablet",):
                if P[n].common(P["Tower"]).Volume > 1e-3:
                    hits.append((n, "Tower", a, t))
            if t == 0 and a in (-YAW_MAX, 0, YAW_MAX):
                v = P["Tower"].common(posed("Column")).Volume
                if v > 5:
                    hits.append(("Tower", "Column", a, round(v, 1)))
    print('STAGE', 'rep["min_tablet_to_wheel_notches"]', flush=True)
    rep["min_tablet_to_wheel_notches"] = round(mind, 1)
    # hard-stop angles with joint lifted just enough to clear teeth, and fully loose
    ys = {l: stop_angle("yaw", l) for l in (3.6, LIFT_MAX)}
    tsp = {}
    for l in (3.6, LIFT_MAX):
        a = TILT_MAX - 1.0
        while a < 90:
            a += 0.5
            if posed("VESA_Head", 0, -a, lt=l).common(posed("Tower")).Volume > 0.5:
                break
        tsp[l] = (stop_angle("tilt", l), -a)
    print('STAGE', 'rep["yaw_stop_deg(lift)"]', flush=True)
    rep["yaw_stop_deg(lift)"] = ys
    rep["tilt_stop_deg(lift)"] = tsp
    # worst case: at the real stops, fully loose, all combinations
    yw = max(v for v in ys.values() if v) - 0.5
    tw_ = max(max(abs(x) for x in v) for v in tsp.values()) - 0.5
    worst = 1e9
    env = []
    for a in (-yw, -yw / 2, 0, yw / 2, yw):
        for t in (-tw_, 0, tw_):
            for l in (0, LIFT_MAX):
                s = posed("Tablet", a, t, ly=l, lt=l)
                worst = min(worst, s.distToShape(wheel)[0])
                if s.common(keep).Volume > 1e-3:
                    hits.append(("Tablet@stop", "pedestal/wheel", a, t, l))
    for a in [x * 5.0 for x in range(-int(yw // 5), int(yw // 5) + 1)] + [-yw, yw]:
        for t in (-tw_, 0, tw_):
            env.append(posed("Tablet", a, t, ly=LIFT_MAX, lt=LIFT_MAX))
    print('STAGE', 'rep["min_tablet_to_wheel_at_hard_stops_k', flush=True)
    rep["min_tablet_to_wheel_at_hard_stops_knobs_loose"] = round(worst, 1)
    print('STAGE', 'sweep = env[0]', flush=True)
    sweep = Part.makeCompound(env)   # display only (boolean union OOMs)
    add("Tablet_Sweep_Envelope", sweep, doc.getObject("Tablet"), (0.2, 0.4, 1.0), 85)
    FIX = ["Poutre", "Column", "Coulisseau_S", "Coulisseau_P", "Berceau_S", "Berceau_P"]
    rep["fixed_vs_pedestal"] = round(sum(posed(n).common(keep).Volume for n in FIX), 2)
    ov = []
    for i in range(len(FIX)):
        for j in range(i + 1, len(FIX)):
            v = posed(FIX[i]).common(posed(FIX[j])).Volume
            if v > 0.5:
                ov.append((FIX[i], FIX[j], round(v, 1)))
    rep["fixed_parts_overlaps"] = ov
    rep["Z_CLAMP"] = round(Z_CLAMP, 1)
    rep["band_gap_to_keepout"] = round(min(posed(n).distToShape(wheel)[0] for n in bands), 1)
    rep["cradle_gap_to_keepout"] = round(min(posed(n).distToShape(wheel)[0] for n in ("Berceau_S", "Berceau_P")), 1)
    rep["leg_spacing_range_cc"] = (2 * SLOT_X[0], 2 * SLOT_X[1])
    rep["hirth_yaw_overlap_mm3"] = round(posed("Tower").common(posed("Column")).Volume, 2)
    rep["hirth_tilt_overlap_mm3"] = round(posed("VESA_Head").common(posed("Tower")).Volume, 2)
    bb = {}
    for n, (s, c) in parts.items():
        b = s.BoundBox
        dims = sorted([b.XLength, b.YLength, b.ZLength])
        bb[n] = [round(d) for d in dims]
    rep["part_bbox_sorted"] = bb
    rep["fits_A1"] = all(max(v) <= BED - 6 for v in bb.values())
    rep["hits"] = hits
    doc.recompute()
    return doc, rep, parts


doc, report, PARTS = build()
for k, v in report.items():
    print(k, v)
