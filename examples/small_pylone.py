import openseespy.opensees as ops
import math
from dataclasses import dataclass

# ─── Parameters ───────────────────────────────────────────────────────────────
# Unit system: kN, m, s  →  mass in t (tonnes = kN·s²/m)

@dataclass
class Params:
    # Geometry
    radius:    float = 1.0      # m — circumradius of cross-section
    height:    float = 12.0     # m — total height
    n_panels:  int   = 6        # number of panels along height
    n_sides:   int   = 3        # polygon sides (3 = triangular, 4 = square, …)
    jacket_ratio: float = 1.5   # ratio of outer jacket radius to inner radius
    # Sections (CHS-DxT format, diameter x thickness in mm)
    sec_chord: str   = 'CHS-76.1x8'
    sec_diag:  str   = 'CHS-42.4x2.6'
    sec_trans: str   = 'CHS-42.4x2.6'
    sec_jacket: str  = 'CHS-60.3x3.2'  # jacket section
    # Loading
    wind_load: float = 10.0     # kN — total horizontal wind at top nodes (+X)
    # Material
    E:         float = 2.1e8    # kN/m²
    G:         float = 8.077e7  # kN/m²
    rho:       float = 7.85     # t/m³
    g_acc:     float = 9.81     # m/s²

# Viewer colors per role
ROLE_COLORS: dict[str, str] = {
    'M': '#cc4455',   # main chords — red
    'D': '#33aa88',   # diagonals — teal
    'T': '#9955bb',   # transversals — purple
    'J': '#ffaa00',   # jacket — orange
}


# ─── Section properties ──────────────────────────────────────────────────────

def chs_props(section: str) -> tuple[float, float, float, float]:
    """CHS-D.dxT → (A, Iy, Iz, J) in m², m⁴."""
    dim = section.split('-')[1]
    d_mm, t_mm = map(float, dim.split('x'))
    r_o = d_mm / 2e3
    r_i = max(0.0, r_o - t_mm / 1e3)
    pi = math.pi
    A = pi * (r_o**2 - r_i**2)
    I = pi / 4 * (r_o**4 - r_i**4)
    return A, I, I, 2 * I


# ─── Helpers ──────────────────────────────────────────────────────────────────

def vecxz(dx: float, dy: float, dz: float, L: float) -> tuple[float, float, float]:
    if abs(dz / L) < 0.9:
        return 0.0, 0.0, 1.0
    return 1.0, 0.0, 0.0


def local_axes(dx: float, dy: float, dz: float, L: float) -> tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float]]:
    ex = (dx / L, dy / L, dz / L)
    vxz = vecxz(dx, dy, dz, L)
    cx = vxz[1]*ex[2] - vxz[2]*ex[1]
    cy = vxz[2]*ex[0] - vxz[0]*ex[2]
    cz = vxz[0]*ex[1] - vxz[1]*ex[0]
    n  = math.sqrt(cx**2 + cy**2 + cz**2)
    ey = (cx / n, cy / n, cz / n)
    ez = (ex[1]*ey[2] - ex[2]*ey[1],
          ex[2]*ey[0] - ex[0]*ey[2],
          ex[0]*ey[1] - ex[1]*ey[0])
    return ex, ey, ez


# ─── Main ─────────────────────────────────────────────────────────────────────

def main(p: Params = Params()) -> None:
    dz = p.height / p.n_panels
    n_levels = p.n_panels + 1
    angles = [2 * math.pi * i / p.n_sides for i in range(p.n_sides)]

    def ntag(level: int, corner: int) -> int:
        return level * p.n_sides + corner + 1

    def jacket_ntag(level: int, corner: int) -> int:
        """Node tag for jacket (outer layer)."""
        return 1000 + level * p.n_sides + corner + 1

    # ── OpenSees model ───────────────────────────────────────────────────────
    ops.wipe()
    ops.model('basic', '-ndm', 3, '-ndf', 6)

    # ── Nodes ────────────────────────────────────────────────────────────────
    nodes: dict[int, tuple[float, float, float]] = {}

    # Inner nodes
    for lv in range(n_levels):
        z = lv * dz
        for c, angle in enumerate(angles):
            x = p.radius * math.cos(angle)
            y = p.radius * math.sin(angle)
            tag = ntag(lv, c)
            nodes[tag] = (x, y, z)
            ops.node(tag, x, y, z)

    # Jacket (outer) nodes
    jacket_radius = p.radius * p.jacket_ratio
    for lv in range(n_levels):
        z = lv * dz
        for c, angle in enumerate(angles):
            x = jacket_radius * math.cos(angle)
            y = jacket_radius * math.sin(angle)
            tag = jacket_ntag(lv, c)
            nodes[tag] = (x, y, z)  # Store in same dict!
            ops.node(tag, x, y, z)

    # ── Supports ─────────────────────────────────────────────────────────────
    for c in range(p.n_sides):
        ops.fix(ntag(0, c), 1, 1, 1, 1, 1, 1)
        ops.fix(jacket_ntag(0, c), 1, 1, 1, 1, 1, 1)

    # ── Sections ─────────────────────────────────────────────────────────────
    sec_data: dict[str, tuple[int, float]] = {}
    for idx, sec_name in enumerate([p.sec_chord, p.sec_diag, p.sec_trans, p.sec_jacket]):
        if sec_name in sec_data:
            continue
        sec_id = idx + 1
        A, Iy, Iz, J = chs_props(sec_name)
        sec_data[sec_name] = (sec_id, A)
        ops.section('Elastic', sec_id, p.E, A, Iz, Iy, p.G, J)

    # ── Element builder ──────────────────────────────────────────────────────
    ops.timeSeries('Linear', 1)
    ops.pattern('Plain', 1, 1)

    el_tag = 0
    transf_tag = 0
    nodal_mass: dict[int, float] = {}
    sec_labels: list[dict[str, object]] = []
    label_set: set[str] = set()

    def add_elem(ni: int, nj: int, sec_name: str, role: str) -> None:
        nonlocal el_tag, transf_tag
        el_tag += 1
        transf_tag += 1

        xi, yi, zi = nodes[ni]
        xj, yj, zj = nodes[nj]
        dx, dy, ddz = xj - xi, yj - yi, zj - zi
        L = math.sqrt(dx**2 + dy**2 + ddz**2)

        sec_id, A = sec_data[sec_name]
        mass_dens = p.rho * A

        ops.geomTransf('Linear', transf_tag, *vecxz(dx, dy, ddz, L))
        ops.element('elasticBeamColumn', el_tag, ni, nj, sec_id, transf_tag,
                    '-mass', mass_dens)

        w = mass_dens * p.g_acc
        ex, ey, ez = local_axes(dx, dy, ddz, L)
        gvec = (0.0, 0.0, -w)
        Wx = gvec[0]*ex[0] + gvec[1]*ex[1] + gvec[2]*ex[2]
        Wy = gvec[0]*ey[0] + gvec[1]*ey[1] + gvec[2]*ey[2]
        Wz = gvec[0]*ez[0] + gvec[1]*ez[1] + gvec[2]*ez[2]
        ops.eleLoad('-ele', el_tag, '-type', '-beamUniform', Wy, Wz, Wx)

        half_m = mass_dens * L / 2
        nodal_mass[ni] = nodal_mass.get(ni, 0.0) + half_m
        nodal_mass[nj] = nodal_mass.get(nj, 0.0) + half_m

        label = f'{sec_name}-{role}'
        if label not in label_set:
            label_set.add(label)
            sec_labels.append({'tag': sec_id, 'color': ROLE_COLORS.get(role, '#5a7fba'), 'label': label})

    # ── Chords — vertical members along each corner ─────────────────────────
    for lv in range(p.n_panels):
        for c in range(p.n_sides):
            add_elem(ntag(lv, c), ntag(lv + 1, c), p.sec_chord, 'M')

    # ── Transversals — horizontal bracing at each level ─────────────────────
    for lv in range(n_levels):
        for c in range(p.n_sides):
            add_elem(ntag(lv, c), ntag(lv, (c + 1) % p.n_sides), p.sec_trans, 'T')

    # ── Diagonals — X-bracing between levels ────────────────────────────────
    for lv in range(p.n_panels):
        for c in range(p.n_sides):
            add_elem(ntag(lv, c), ntag(lv + 1, (c + 1) % p.n_sides), p.sec_diag, 'D')
            add_elem(ntag(lv, (c + 1) % p.n_sides), ntag(lv + 1, c), p.sec_diag, 'D')

    # ── Jacket (outer layer) ─────────────────────────────────────────────────
    # Jacket chords — vertical members of outer layer
    for lv in range(p.n_panels):
        for c in range(p.n_sides):
            add_elem(jacket_ntag(lv, c), jacket_ntag(lv + 1, c), p.sec_jacket, 'J')

    # Jacket transversals — horizontal bracing of outer layer
    for lv in range(n_levels):
        for c in range(p.n_sides):
            add_elem(jacket_ntag(lv, c), jacket_ntag(lv, (c + 1) % p.n_sides), p.sec_jacket, 'J')

    # Radial ties — connect inner tower to outer jacket
    for lv in range(n_levels):
        for c in range(p.n_sides):
            add_elem(ntag(lv, c), jacket_ntag(lv, c), p.sec_jacket, 'J')

    # ── Nodal masses ────────────────────────────────────────────────────────
    for tag, m in nodal_mass.items():
        ops.mass(tag, m, m, m, 0.0, 0.0, 0.0)

    # ── Wind load at top nodes ──────────────────────────────────────────────
    ops.timeSeries('Linear', 2)
    ops.pattern('Plain', 2, 2)
    for c in range(p.n_sides):
        tag = ntag(p.n_panels, c)
        ops.load(tag, p.wind_load / p.n_sides, 0.0, 0.0, 0.0, 0.0, 0.0)

    # ── Viewer metadata ─────────────────────────────────────────────────────
    global __viewer__
    __viewer__ = {
        'sections': sec_labels,
        'precision': 3,
    }

    # ── Static analysis ─────────────────────────────────────────────────────
    ops.system('BandGeneral')
    ops.numberer('RCM')
    ops.constraints('Plain')
    ops.integrator('LoadControl', 1.0)
    ops.algorithm('Linear')
    ops.analysis('Static')
    ops.analyze(1)


if __name__ == '__main__':
    main(Params(height=30.0, n_panels=5, jacket_ratio=2.0))

# ── Parametric usage examples ─────────────────────────────────────────────────
# main(Params(height=24.0, n_panels=10, radius=1.5))
# main(Params(n_sides=4, sec_chord='CHS-114.3x8'))
