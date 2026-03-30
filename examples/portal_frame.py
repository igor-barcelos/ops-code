# 2D portal frame — fixed base, horizontal wind load
# Units: kN, m
import openseespy.opensees as ops

ops.wipe()
ops.model('basic', '-ndm', 2, '-ndf', 3)

E = 2.1e8   # kN/m²
A = 1.2e-2  # m²
I = 6.0e-5  # m⁴
H = 4.0     # m — column height
L = 6.0     # m — bay width

#   2 ——— 3
#   |     |
#   1     4
ops.node(1, 0.0, 0.0)
ops.node(2, 0.0,   H)
ops.node(3,   L,   H)
ops.node(4,   L, 0.0)

ops.fix(1, 1, 1, 1)
ops.fix(4, 1, 1, 1)

ops.geomTransf('Linear', 1)

ops.element('elasticBeamColumn', 1, 1, 2, A, E, I, 1)  # left column
ops.element('elasticBeamColumn', 2, 2, 3, A, E, I, 1)  # beam
ops.element('elasticBeamColumn', 3, 3, 4, A, E, I, 1)  # right column

# Horizontal wind at top-left node
ops.timeSeries('Linear', 1)
ops.pattern('Plain', 1, 1)
ops.load(2, 10.0, 0.0, 0.0)  # 10 kN →

__viewer__ = {
    'nodalLoads': {'scale': 1.5, 'color': '#ff8800'},
    'supports':   {'scale': 1.2, 'color': '#44aaff'},
    'precision': 3,
    'label': {'size': 10},
}

ops.system('BandGeneral')
ops.numberer('Plain')
ops.constraints('Plain')
ops.integrator('LoadControl', 1.0)
ops.algorithm('Linear')
ops.analysis('Static')
ops.analyze(1)
