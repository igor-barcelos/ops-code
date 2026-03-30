# 3D single-bay space frame — fixed base, vertical loads at top
# Units: kN, m
import openseespy.opensees as ops

ops.wipe()
ops.model('basic', '-ndm', 3, '-ndf', 6)

E  = 2.1e8   # kN/m²
G  = 8.1e7   # kN/m²
A  = 1.5e-2  # m²
Iy = 8.0e-5  # m⁴
Iz = 8.0e-5  # m⁴
J  = 1.6e-4  # m⁴
H  = 5.0     # m — column height
B  = 4.0     # m — bay size

# Base (1–4) and top (5–8)
#   4 ─── 3
#   |     |    ← plan view
#   1 ─── 2
ops.node(1, 0.0, 0.0, 0.0)
ops.node(2,   B, 0.0, 0.0)
ops.node(3,   B,   B, 0.0)
ops.node(4, 0.0,   B, 0.0)
ops.node(5, 0.0, 0.0,   H)
ops.node(6,   B, 0.0,   H)
ops.node(7,   B,   B,   H)
ops.node(8, 0.0,   B,   H)

for n in [1, 2, 3, 4]:
    ops.fix(n, 1, 1, 1, 1, 1, 1)

ops.geomTransf('Linear', 1, 1, 0, 0)  # columns  (axis = Z, vecxz = X)
ops.geomTransf('Linear', 2, 0, 0, 1)  # beams    (axis = X or Y, vecxz = Z)

# Columns
for el, (ni, nj) in enumerate([(1,5),(2,6),(3,7),(4,8)], start=1):
    ops.element('elasticBeamColumn', el, ni, nj, A, E, G, J, Iy, Iz, 1)

# Beams at top
ops.element('elasticBeamColumn', 5, 5, 6, A, E, G, J, Iy, Iz, 2)
ops.element('elasticBeamColumn', 6, 6, 7, A, E, G, J, Iy, Iz, 2)
ops.element('elasticBeamColumn', 7, 7, 8, A, E, G, J, Iy, Iz, 2)
ops.element('elasticBeamColumn', 8, 8, 5, A, E, G, J, Iy, Iz, 2)

# Vertical loads at each top node
ops.timeSeries('Linear', 1)
ops.pattern('Plain', 1, 1)
for n in [5, 6, 7, 8]:
    ops.load(n, 0.0, 0.0, -25.0, 0.0, 0.0, 0.0)  # 25 kN ↓

__viewer__ = {
    'nodalLoads': {'scale': 1.2, 'color': '#ff6600'},
    'supports':   {'scale': 1.5, 'color': '#3399ff'},
    'precision': 3,
}

ops.system('BandGeneral')
ops.numberer('Plain')
ops.constraints('Plain')
ops.integrator('LoadControl', 1.0)
ops.algorithm('Linear')
ops.analysis('Static')
ops.analyze(1)
