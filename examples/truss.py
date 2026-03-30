# 2D Pratt truss — pin + roller supports, gravity loads on top chord
# Units: kN, m
import openseespy.opensees as ops

ops.wipe()
ops.model('basic', '-ndm', 2, '-ndf', 3)

E       = 2.1e8   # kN/m²
A_chord = 4.0e-4  # m² — chord sections
A_diag  = 2.5e-4  # m² — diagonal / vertical sections

ops.uniaxialMaterial('Elastic', 1, E)

# Bottom chord: 1(0,0)  2(3,0)  3(6,0)  4(9,0)
# Top chord:    5(0,3)  6(3,3)  7(6,3)  8(9,3)
ops.node(1, 0.0, 0.0)
ops.node(2, 3.0, 0.0)
ops.node(3, 6.0, 0.0)
ops.node(4, 9.0, 0.0)
ops.node(5, 0.0, 3.0)
ops.node(6, 3.0, 3.0)
ops.node(7, 6.0, 3.0)
ops.node(8, 9.0, 3.0)

ops.fix(1, 1, 1, 0)   # pin
ops.fix(4, 0, 1, 0)   # roller

# Bottom chord
ops.element('Truss', 1, 1, 2, A_chord, 1)
ops.element('Truss', 2, 2, 3, A_chord, 1)
ops.element('Truss', 3, 3, 4, A_chord, 1)
# Top chord
ops.element('Truss', 4, 5, 6, A_chord, 1)
ops.element('Truss', 5, 6, 7, A_chord, 1)
ops.element('Truss', 6, 7, 8, A_chord, 1)
# Verticals
ops.element('Truss', 7,  1, 5, A_diag, 1)
ops.element('Truss', 8,  2, 6, A_diag, 1)
ops.element('Truss', 9,  3, 7, A_diag, 1)
ops.element('Truss', 10, 4, 8, A_diag, 1)
# Diagonals — Pratt pattern (tension under gravity)
ops.element('Truss', 11, 5, 2, A_diag, 1)
ops.element('Truss', 12, 6, 3, A_diag, 1)
ops.element('Truss', 13, 7, 4, A_diag, 1)

# Gravity loads at interior top-chord nodes
ops.timeSeries('Linear', 1)
ops.pattern('Plain', 1, 1)
ops.load(6, 0.0, -5.0, 0.0)
ops.load(7, 0.0, -5.0, 0.0)

__viewer__ = {
    'nodalLoads': {'scale': 2.0, 'color': '#ff4444'},
    'supports':   {'scale': 1.0, 'color': '#55cc88'},
    'precision': 4,
    'label': {'size': 10},
}

ops.system('BandGeneral')
ops.numberer('Plain')
ops.constraints('Plain')
ops.integrator('LoadControl', 1.0)
ops.algorithm('Linear')
ops.analysis('Static')
ops.analyze(1)
