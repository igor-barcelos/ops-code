import openseespy.opensees as ops
import csv
import math
import os

# ─── Material / loading constants ────────────────────────────────────────────
# Unit system: kN, m, s  →  mass in t (tonnes = kN·s²/m)
E     = 2.1e8    # kN/m²
G     = 8.077e7  # kN/m²
RHO   = 7.85     # t/m³  (steel mass density, 7850 kg/m³)
G_ACC = 9.81     # m/s²

FIXED_NODES = {'n0', 'n2', 'n4', 'n387', 'n389', 'n391'}


# ─── Section properties ───────────────────────────────────────────────────────

def _chs_props(section: str) -> tuple[float, float, float, float]:
    """CHS-D.dxT[-suffix] → (A, Iy, Iz, J) in m², m⁴."""
    dim = section.split('-')[1]          # e.g. '114.3x8'
    d_mm, t_mm = map(float, dim.split('x'))
    r_o = d_mm / 2e3                     # m
    r_i = max(0.0, d_mm / 2e3 - t_mm / 1e3)
    pi = math.pi
    A = pi * (r_o**2 - r_i**2)
    I = pi / 4 * (r_o**4 - r_i**4)
    return A, I, I, 2 * I


def _ls_props(section: str) -> tuple[float, float, float, float]:
    """LS-bxt → (A, Iy, Iz, J) in m², m⁴.  Equal-leg angle."""
    dim = section.split('-')[1]          # e.g. '50x5'
    b_mm, t_mm = map(float, dim.split('x'))
    b, t = b_mm / 1e3, t_mm / 1e3       # m
    A = t * (2 * b - t)
    # centroid distance from outer face of each leg
    c = (b**2 + b * t - t**2) / (2 * (2 * b - t))
    # parallel-axis theorem — horizontal + vertical leg contributions
    I_h = b * t**3 / 12 + b * t * (c - t / 2)**2
    I_v = t * (b - t)**3 / 12 + t * (b - t) * ((b + t) / 2 - c)**2
    I   = I_h + I_v
    J   = t**3 * (2 * b - t) / 3        # thin-walled open section torsion
    return A, I, I, J


def section_props(section: str) -> tuple[float, float, float, float]:
    if section.startswith('CHS'):
        return _chs_props(section)
    return _ls_props(section)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def ntag(name: str) -> int:
    """Node name 'nN' → OpenSees tag N+1  (tags must be ≥ 1)."""
    return int(name[1:]) + 1


def vecxz(dx: float, dy: float, dz: float, L: float) -> tuple[float, float, float]:
    """Local-xz-plane reference vector that is not parallel to the element axis."""
    if abs(dz / L) < 0.9:
        return 0.0, 0.0, 1.0
    return 1.0, 0.0, 0.0


def local_axes(dx: float, dy: float, dz: float, L: float) -> tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float]]:
    """Return (ex, ey, ez) unit vectors for the element local coordinate system."""
    ex = (dx / L, dy / L, dz / L)
    vxz = vecxz(dx, dy, dz, L)
    # ey = normalize(vxz × ex)
    cx = vxz[1]*ex[2] - vxz[2]*ex[1]
    cy = vxz[2]*ex[0] - vxz[0]*ex[2]
    cz = vxz[0]*ex[1] - vxz[1]*ex[0]
    n  = math.sqrt(cx**2 + cy**2 + cz**2)
    ey = (cx / n, cy / n, cz / n)
    # ez = ex × ey
    ez = (ex[1]*ey[2] - ex[2]*ey[1],
          ex[2]*ey[0] - ex[0]*ey[2],
          ex[0]*ey[1] - ex[1]*ey[0])
    return ex, ey, ez


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    base = os.path.dirname(os.path.abspath(__file__))

    # ── Read nodes ────────────────────────────────────────────────────────────
    node_coords: dict[str, tuple[float, float, float]] = {}
    with open(os.path.join(base, 'noeuds.csv'), newline='') as f:
        for row in csv.DictReader(f):
            node_coords[row['name']] = (float(row['X']), float(row['Y']), float(row['Z']))

    # ── Read elements ─────────────────────────────────────────────────────────
    bar_rows: list[dict[str, str]] = []
    with open(os.path.join(base, 'barres.csv'), newline='') as f:
        bar_rows = list(csv.DictReader(f))

    # ── Build OpenSees model ──────────────────────────────────────────────────
    ops.wipe()
    ops.model('basic', '-ndm', 3, '-ndf', 6)

    for name, (x, y, z) in node_coords.items():
        ops.node(ntag(name), x, y, z)

    for name in FIXED_NODES:
        ops.fix(ntag(name), 1, 1, 1, 1, 1, 1)

    # ── Sections ─────────────────────────────────────────────────────────────
    unique_sections: list[str] = list(dict.fromkeys(row['section'] for row in bar_rows))
    sec_tag_map: dict[str, int] = {}
    sec_area: dict[str, float] = {}
    for i, sec_name in enumerate(unique_sections):
        sec_id = i + 1
        sec_tag_map[sec_name] = sec_id
        A, Iy, Iz, J = section_props(sec_name)
        sec_area[sec_name] = A
        ops.section('Elastic', sec_id, E, A, Iz, Iy, G, J)

    # ── Gravity load pattern (distributed self-weight via eleLoad) ───────────
    ops.timeSeries('Linear', 1)
    ops.pattern('Plain', 1, 1)

    # ── Wind load pattern (horizontal load in +x direction) ──────────────────
    ops.timeSeries('Linear', 2)
    ops.pattern('Plain', 2, 2)

    # Accumulated lumped nodal mass (t) from element -mass
    nodal_mass: dict[int, float] = {}

    for idx, row in enumerate(bar_rows):
        ni_name = row['node_i']
        nj_name = row['node_j']
        ni, nj   = ntag(ni_name), ntag(nj_name)

        xi, yi, zi = node_coords[ni_name]
        xj, yj, zj = node_coords[nj_name]
        dx, dy, dz  = xj - xi, yj - yi, zj - zi
        L = math.sqrt(dx**2 + dy**2 + dz**2)

        sec_name = row['section']
        sec_id = sec_tag_map[sec_name]
        A = sec_area[sec_name]

        # mass per unit length (t/m)
        mass_dens = RHO * A  # t/m

        transf_tag = idx + 1
        ops.geomTransf('Linear', transf_tag, *vecxz(dx, dy, dz, L))

        el_tag = int(row['name'][1:]) + 1
        ops.element('elasticBeamColumn', el_tag, ni, nj, sec_id, transf_tag,
                    '-mass', mass_dens)

        # Self-weight as distributed eleLoad — project global (0,0,-w) onto local axes
        w = mass_dens * G_ACC  # kN/m
        ex, ey, ez = local_axes(dx, dy, dz, L)
        g = (0.0, 0.0, -w)
        Wx = g[0]*ex[0] + g[1]*ex[1] + g[2]*ex[2]
        Wy = g[0]*ey[0] + g[1]*ey[1] + g[2]*ey[2]
        Wz = g[0]*ez[0] + g[1]*ez[1] + g[2]*ez[2]
        ops.eleLoad('-ele', el_tag, '-type', '-beamUniform', Wy, Wz, Wx)

        # Lumped half-mass to each end node
        half_m = mass_dens * L / 2  # t
        nodal_mass[ni] = nodal_mass.get(ni, 0.0) + half_m
        nodal_mass[nj] = nodal_mass.get(nj, 0.0) + half_m

    # Set nodal masses (enables modal analysis later if needed)
    for tag, m in nodal_mass.items():
        ops.mass(tag, m, m, m, 0.0, 0.0, 0.0)

    # Apply wind load at top 3 nodes in +x direction
    top_nodes = sorted(node_coords.items(), key=lambda item: item[1][2], reverse=True)[:3]
    WIND_LOAD = 50.2  # kN (total, distributed across top nodes)
    load_per_node = WIND_LOAD / len(top_nodes)
    for name, coords in top_nodes:
        tag = ntag(name)
        ops.load(tag, load_per_node, 0.0, 0.0, 0.0, 0.0, 0.0)

    # ── Viewer ────────────────────────────────────────────────────────────────
    ROLE_COLORS: dict[str, str] = {
        'M':  '#cc4455',   # main chords — red
        'MR': '#cc8833',   # main reinforced — orange
        'D':  '#33aa88',   # diagonals — teal
        'DR': '#3399aa',   # diagonals reinforced — cyan
        'T':  '#9955bb',   # transversals — purple
        'TR': '#aa5544',   # transversals reinforced — brown
        'LS': '#bbaa44',   # angles — yellow
    }

    def _role(name: str) -> str:
        return 'LS' if name.startswith('LS') else name.rsplit('-', 1)[-1]

    global __viewer__
    __viewer__ = {
        'sections': [
            {'tag': sec_id, 'color': ROLE_COLORS.get(_role(name), '#5a7fba'), 'label': name}
            for name, sec_id in sec_tag_map.items()
        ],
        'precision': 3,
    }

    # ── Static linear analysis ────────────────────────────────────────────────
    ops.system('BandGeneral')
    ops.numberer('RCM')
    ops.constraints('Plain')
    ops.integrator('LoadControl', 1.0)
    ops.algorithm('Linear')
    ops.analysis('Static')
    ops.analyze(1)


if __name__ == '__main__':
    main()
