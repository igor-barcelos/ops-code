import math
import openseespy.opensees as ops
from tools import buckling_en1993

# ─── Constants ────────────────────────────────────────────────────────────────
E: float = 2.1e8   # kN/m²
G: float = 8.077e7 # kN/m²

ROLE_COLORS: dict[str, str] = {
    'M': '#cc4455',
    'D': '#33aa88',
    'T': '#9955bb',
}

# ─── Geometry ─────────────────────────────────────────────────────────────────
# (x, y, z, fixed) — 0-based index, ops tag = index + 1
NODES: list[tuple[float, float, float, bool]] = [
    ( 1.21,  0.00,  0, True ),  # n0
    ( 1.21,  0.00,  2, False),  # n1
    (-0.61,  1.05,  0, True ),  # n2
    (-0.61,  1.05,  2, False),  # n3
    (-0.61, -1.05,  0, True ),  # n4
    (-0.61, -1.05,  2, False),  # n5
    ( 1.21,  0.00,  4, False),  # n6
    (-0.61,  1.05,  4, False),  # n7
    (-0.61, -1.05,  4, False),  # n8
    ( 1.21,  0.00,  6, False),  # n9
    (-0.61,  1.05,  6, False),  # n10
    (-0.61, -1.05,  6, False),  # n11
    ( 1.21,  0.00,  8, False),  # n12
    (-0.61,  1.05,  8, False),  # n13
    (-0.61, -1.05,  8, False),  # n14
    ( 1.21,  0.00, 10, False),  # n15
    (-0.61,  1.05, 10, False),  # n16
    (-0.61, -1.05, 10, False),  # n17
    ( 1.21,  0.00, 12, False),  # n18
    (-0.61,  1.05, 12, False),  # n19
    (-0.61, -1.05, 12, False),  # n20
    ( 1.21,  0.00, 14, False),  # n21
    (-0.61,  1.05, 14, False),  # n22
    (-0.61, -1.05, 14, False),  # n23
    ( 1.21,  0.00, 16, False),  # n24
    (-0.61,  1.05, 16, False),  # n25
    (-0.61, -1.05, 16, False),  # n26
    ( 1.21,  0.00, 18, False),  # n27
    (-0.61,  1.05, 18, False),  # n28
    (-0.61, -1.05, 18, False),  # n29
    ( 1.21,  0.00, 20, False),  # n30
    (-0.61,  1.05, 20, False),  # n31
    (-0.61, -1.05, 20, False),  # n32
    ( 1.21,  0.00, 22, False),  # n33
    (-0.61,  1.05, 22, False),  # n34
    (-0.61, -1.05, 22, False),  # n35
    ( 1.21,  0.00, 24, False),  # n36
    (-0.61,  1.05, 24, False),  # n37
    (-0.61, -1.05, 24, False),  # n38
    ( 1.21,  0.00, 26, False),  # n39
    (-0.61,  1.05, 26, False),  # n40
    (-0.61, -1.05, 26, False),  # n41
    ( 1.21,  0.00, 28, False),  # n42
    (-0.61,  1.05, 28, False),  # n43
    (-0.61, -1.05, 28, False),  # n44
    ( 1.21,  0.00, 30, False),  # n45
    (-0.61,  1.05, 30, False),  # n46
    (-0.61, -1.05, 30, False),  # n47
    ( 1.21,  0.00, 32, False),  # n48
    (-0.61,  1.05, 32, False),  # n49
    (-0.61, -1.05, 32, False),  # n50
    ( 1.21,  0.00, 35, False),  # n51
    (-0.61,  1.05, 35, False),  # n52
    (-0.61, -1.05, 35, False),  # n53
]

# (ni, nj, section) — 0-based node indices
M = 'CHS-168.3x12.5-M'; m = 'CHS-139.7x10-M'; n = 'CHS-139.7x8-M'
p = 'CHS-101.6x8.8-M';  q = 'CHS-101.6x4-M'
D = 'CHS-88.9x4-D';     d = 'CHS-76.1x4.5-D'; e = 'CHS-76.1x3.6-D'; f = 'CHS-76.1x5.6-D'
T = 'LS-60x60x6-T'

ELEMENTS: list[tuple[int, int, str]] = [
    # panel 0→1 (z=0→2)
    (0,1,M),(2,3,M),(4,5,M),   (0,3,D),(2,5,D),(4,1,D),   (1,3,T),(3,5,T),(5,1,T),
    # panel 1→2 (z=2→4)
    (1,6,M),(3,7,M),(5,8,M),   (3,6,D),(5,7,D),(1,8,D),   (6,7,T),(7,8,T),(8,6,T),
    # panel 2→3 (z=4→6)
    (6,9,M),(7,10,M),(8,11,M), (6,10,D),(7,11,D),(8,9,D), (9,10,T),(10,11,T),(11,9,T),
    # panel 3→4 (z=6→8)
    (9,12,M),(10,13,M),(11,14,M), (10,12,D),(11,13,D),(9,14,D), (12,13,T),(13,14,T),(14,12,T),
    # panel 4→5 (z=8→10)
    (12,15,M),(13,16,M),(14,17,M), (12,16,D),(13,17,D),(14,15,D), (15,16,T),(16,17,T),(17,15,T),
    # panel 5→6 (z=10→12)
    (15,18,M),(16,19,M),(17,20,M), (16,18,D),(17,19,D),(15,20,D), (18,19,T),(19,20,T),(20,18,T),
    # panel 6→7 (z=12→14)
    (18,21,m),(19,22,m),(20,23,m), (18,22,d),(19,23,d),(20,21,d), (21,22,T),(22,23,T),(23,21,T),
    # panel 7→8 (z=14→16)
    (21,24,m),(22,25,m),(23,26,m), (22,24,d),(23,25,d),(21,26,d), (24,25,T),(25,26,T),(26,24,T),
    # panel 8→9 (z=16→18)
    (24,27,m),(25,28,m),(26,29,m), (24,28,d),(25,29,d),(26,27,d), (27,28,T),(28,29,T),(29,27,T),
    # panel 9→10 (z=18→20)
    (27,30,n),(28,31,n),(29,32,n), (28,30,d),(29,31,d),(27,32,d), (30,31,T),(31,32,T),(32,30,T),
    # panel 10→11 (z=20→22)
    (30,33,n),(31,34,n),(32,35,n), (30,34,d),(31,35,d),(32,33,d), (33,34,T),(34,35,T),(35,33,T),
    # panel 11→12 (z=22→24)
    (33,36,n),(34,37,n),(35,38,n), (34,36,e),(35,37,e),(33,38,e), (36,37,T),(37,38,T),(38,36,T),
    # panel 12→13 (z=24→26)
    (36,39,p),(37,40,p),(38,41,p), (36,40,e),(37,41,e),(38,39,e), (39,40,T),(40,41,T),(41,39,T),
    # panel 13→14 (z=26→28)
    (39,42,p),(40,43,p),(41,44,p), (40,42,e),(41,43,e),(39,44,e), (42,43,T),(43,44,T),(44,42,T),
    # panel 14→15 (z=28→30)
    (42,45,p),(43,46,p),(44,47,p), (42,46,e),(43,47,e),(44,45,e), (45,46,T),(46,47,T),(47,45,T),
    # panel 15→16 (z=30→32)
    (45,48,q),(46,49,q),(47,50,q), (46,48,f),(47,49,f),(45,50,f), (48,49,T),(49,50,T),(50,48,T),
    # panel 16→17 (z=32→35)
    (48,51,q),(49,52,q),(50,53,q), (48,52,f),(49,53,f),(50,51,f), (51,52,T),(52,53,T),(53,51,T),
]


# ─── Section properties ───────────────────────────────────────────────────────

def chs_props(dims: str) -> tuple[float, float, float, float]:
    """CHS 'DxT' → (A, Iy, Iz, J) in m², m⁴."""
    d_mm, t_mm = map(float, dims.split('x'))
    r_o = d_mm / 2e3
    r_i = max(0.0, r_o - t_mm / 1e3)
    pi = math.pi
    A = pi * (r_o**2 - r_i**2)
    I = pi / 4 * (r_o**4 - r_i**4)
    return A, I, I, 2 * I


def ls_props(dims: str) -> tuple[float, float, float, float]:
    """LS 'axbxt' equal leg angle → (A, Iy, Iz, J) in m², m⁴."""
    parts = dims.split('x')
    a = float(parts[0]) / 1e3
    t = float(parts[2]) / 1e3
    A = t * (2*a - t)
    A1, y1 = a * t, t / 2
    A2, y2 = t * (a - t), t + (a - t) / 2
    e = (A1 * y1 + A2 * y2) / A
    Ix_back = (a * t**3 / 12 + A1 * y1**2) + (t * (a - t)**3 / 12 + A2 * y2**2)
    I = Ix_back - A * e**2
    J = (2*a - t) * t**3 / 3
    return A, I, I, J


def section_props(sec_name: str) -> tuple[float, float, float, float]:
    parts = sec_name.split('-')
    stype, dims = parts[0], parts[1]
    if stype == 'CHS':
        return chs_props(dims)
    if stype == 'LS':
        return ls_props(dims)
    raise ValueError(f"Unknown section type: {stype}")


# ─── Geometry helper ──────────────────────────────────────────────────────────

def vecxz(dx: float, dy: float, dz: float, L: float) -> tuple[float, float, float]:
    if abs(dz / L) < 0.9:
        return 0.0, 0.0, 1.0
    return 1.0, 0.0, 0.0


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    ops.wipe()
    ops.model('basic', '-ndm', 3, '-ndf', 6)

    coords: dict[int, tuple[float, float, float]] = {}
    for i, (x, y, z, fixed) in enumerate(NODES):
        tag = i + 1
        coords[tag] = (x, y, z)
        ops.node(tag, x, y, z)
        if fixed:
            ops.fix(tag, 1, 1, 1, 1, 1, 1)

    sec_tags: dict[str, int] = {}
    sec_labels: list[dict[str, object]] = []

    for ni_idx, nj_idx, sec_name in ELEMENTS:
        if sec_name not in sec_tags:
            sec_id = len(sec_tags) + 1
            sec_tags[sec_name] = sec_id
            A, Iy, Iz, J = section_props(sec_name)
            ops.section('Elastic', sec_id, E, A, Iz, Iy, G, J)
            role = sec_name.split('-')[-1]
            sec_labels.append({
                'tag': sec_id,
                'color': ROLE_COLORS.get(role, '#5a7fba'),
                'label': sec_name,
            })

    transf_tag = 0
    for el_tag, (ni_idx, nj_idx, sec_name) in enumerate(ELEMENTS, start=1):
        ni, nj = ni_idx + 1, nj_idx + 1
        xi, yi, zi = coords[ni]
        xj, yj, zj = coords[nj]
        dx, dy, dz = xj - xi, yj - yi, zj - zi
        L = math.sqrt(dx**2 + dy**2 + dz**2)
        transf_tag += 1
        ops.geomTransf('Linear', transf_tag, *vecxz(dx, dy, dz, L))
        ops.element('elasticBeamColumn', el_tag, ni, nj, sec_tags[sec_name], transf_tag)

    # Wind load at top nodes (z = 35 m)
    top_z = max(z for _, _, z, _ in NODES)
    top_tags = [i + 1 for i, (_, _, z, _) in enumerate(NODES) if z == top_z]
    wind_load = 40.04  # kN total
    ops.timeSeries('Linear', 1)
    ops.pattern('Plain', 1, 1)
    for tag in top_tags:
        ops.load(tag, wind_load / len(top_tags), 0.0, 0.0, 0.0, 0.0, 0.0)

    global __viewer__
    __viewer__ = {'sections': sec_labels, 'precision': 3}

    ops.system('BandGeneral')
    ops.numberer('RCM')
    ops.constraints('Plain')
    ops.integrator('LoadControl', 1.0)
    ops.algorithm('Linear')
    ops.analysis('Static')
    ops.analyze(1)


if __name__ == '__main__':
    main()
