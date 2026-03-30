"""Runs real openseespy analysis and captures results.

Input:  script path (sys.argv[1])
Output: JSON to stdout — Phase 1 model data + analysis results block
"""

import io
import json
import math
import os
import sys
from typing import Any

import openseespy.opensees as ops


def run(script_path: str) -> dict[str, Any]:
    """Execute user script with real openseespy, query results after analysis."""
    recorded_nodes: list[int] = []
    recorded_elements: list[int] = []

    ndm: int = 2
    ndf: int = 3
    nodes: list[dict[str, Any]] = []
    elements: list[dict[str, Any]] = []
    supports: list[dict[str, Any]] = []
    nodal_loads: list[dict[str, Any]] = []
    # --- Wrap real ops functions to record tags ---

    real_model = ops.model
    def patched_model(*args: Any) -> None:
        nonlocal ndm, ndf
        str_args = [str(a) for a in args]
        if '-ndm' in str_args:
            ndm = int(str_args[str_args.index('-ndm') + 1])
        if '-ndf' in str_args:
            ndf = int(str_args[str_args.index('-ndf') + 1])
        real_model(*args)
    ops.model = patched_model  # type: ignore[method-assign]

    real_node = ops.node
    def patched_node(tag: int, *coords: float) -> None:
        recorded_nodes.append(int(tag))
        nodes.append({"tag": int(tag), "coords": [float(c) for c in coords]})
        real_node(tag, *coords)
    ops.node = patched_node  # type: ignore[method-assign]

    real_element = ops.element
    def patched_element(etype: str, tag: int, *args: Any) -> None:
        recorded_elements.append(int(tag))
        node_tags: list[int] = []
        for arg in args:
            if isinstance(arg, int):
                node_tags.append(arg)
            else:
                break
        elements.append({"tag": int(tag), "type": str(etype), "nodes": node_tags})
        real_element(etype, tag, *args)
    ops.element = patched_element  # type: ignore[method-assign]

    real_fix = ops.fix
    def patched_fix(tag: int, *dofs: int) -> None:
        supports.append({"tag": int(tag), "dofs": [int(d) for d in dofs]})
        real_fix(tag, *dofs)
    ops.fix = patched_fix  # type: ignore[method-assign]

    real_load = ops.load
    def patched_load(tag: int, *values: float) -> None:
        nodal_loads.append({"tag": int(tag), "values": [float(v) for v in values]})
        real_load(tag, *values)
    ops.load = patched_load  # type: ignore[method-assign]

    # --- Execute user script ---

    error: str | None = None
    converged: bool = False
    ops_elem_results: list[dict[str, Any]] = []

    def ops_elem_result(name: str, values: dict[int, float | list[float]]) -> None:
        """Register a custom element result for visualization."""
        wrapped_values: dict[int, list[float]] = {}
        for tag, val in values.items():
            if isinstance(val, (int, float)):
                wrapped_values[int(tag)] = [float(val)]
            elif isinstance(val, list):
                wrapped_values[int(tag)] = [float(v) for v in val]

        ops_elem_results.append({
            "id": f"custom_{len(ops_elem_results)}",
            "name": name,
            "values": wrapped_values,
        })

    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        filepath = os.path.abspath(script_path)
        with open(filepath, 'r', encoding='utf-8') as f:
            code = f.read()
        namespace = {
            '__name__': '__main__',
            '__file__': filepath,
            'ops_elem_result': ops_elem_result,
        }
        exec(compile(code, filepath, 'exec'), namespace)
        converged = True
    except Exception as exc:
        error = str(exc)
    finally:
        sys.stdout = old_stdout
        _restore_ops(real_model, real_node, real_element, real_fix, real_load)

    # --- Query results ---

    node_results: list[dict[str, Any]] = []
    element_results: list[dict[str, Any]] = []

    if converged:
        for tag in recorded_nodes:
            try:
                node_results.append({
                    "tag": tag,
                    "disp": ops.nodeDisp(tag),
                    "reaction": ops.nodeReaction(tag),
                })
            except Exception:
                pass

        # Build node coord lookup for element length computation
        node_coords: dict[int, list[float]] = {}
        for n in nodes:
            node_coords[n["tag"]] = n["coords"]

        for el in elements:
            tag = el["tag"]
            try:
                lf = list(ops.eleResponse(tag, 'localForces'))
            except Exception:
                continue

            # Compute element length from node coordinates
            el_nodes = el["nodes"]
            if len(el_nodes) >= 2 and el_nodes[0] in node_coords and el_nodes[1] in node_coords:
                c0 = node_coords[el_nodes[0]]
                c1 = node_coords[el_nodes[1]]
                L = math.sqrt(sum((a - b) ** 2 for a, b in zip(c0, c1)))
            else:
                L = 0.0

            sf = _section_forces(lf, L, ndf, ndm, el["type"])
            element_results.append({
                "tag": tag,
                "local_forces": lf,
                "section_forces": sf,
            })

    return {
        "schema_version": 2,
        "ndm": ndm,
        "ndf": ndf,
        "nodes": nodes,
        "elements": elements,
        "supports": supports,
        "nodal_loads": nodal_loads,
        "error": error,
        "analysis": {
            "converged": converged,
            "node_results": node_results,
            "element_results": element_results,
            "ops_elem_results": ops_elem_results if ops_elem_results else None,
        },
    }


_TRUSS_TYPES = {'truss', 'corottruss', 'trusssection'}

def _section_forces(
    lf: list[float], L: float, ndf: int, ndm: int, etype: str = '', nep: int = 11
) -> dict[str, list[float]]:
    """Compute section forces at nep evaluation points along the element.

    Uses opsvis sign convention for Euler-Bernoulli beams:
      N(x) = -N1,  V(x) = V1,  M(x) = -M1 + V1*x

    Args:
        lf:    local end forces from eleResponse('localForces')
        L:     element length
        ndf:   degrees of freedom per node (model-level)
        ndm:   number of spatial dimensions (2 or 3)
        etype: element type string (e.g. 'Truss', 'elasticBeamColumn')
        nep:   number of evaluation points (default 11)

    Returns:
        Dict with 'x' (normalized positions) and force component arrays.
        Keys depend on element type:
          truss        → N only
          2D frame     → N, V, M
          3D frame     → N, V, Vz, T, My, Mz
    """
    nlf = len(lf)
    x = [i / (nep - 1) for i in range(nep)]
    is_truss = etype.lower() in _TRUSS_TYPES

    if nlf >= 12 and ndf >= 6:
        # 3D frame element (e.g. elasticBeamColumn, forceBeamColumn in 3D)
        # lf = [N1, Vy1, Vz1, T1, My1, Mz1,  N2, Vy2, Vz2, T2, My2, Mz2]
        # Forces at node 1 only are needed; node 2 forces are equilibrium-consistent.
        # Sign convention (opsvis): axial and torsion are negated so that
        #   positive N = tension, positive T = right-hand-rule about local x.
        # Moments vary linearly via beam equilibrium: M(x) = -M1 + V*x*L
        N1, Vy1, Vz1, T1, My1, Mz1 = lf[0], lf[1], lf[2], lf[3], lf[4], lf[5]
        return {
            "x": x,
            "N":  [-N1] * nep,
            "V":  [Vy1] * nep,
            "Vz": [Vz1] * nep,
            "T":  [-T1] * nep,
            "My": [-My1 + Vz1 * (t * L) for t in x],
            "Mz": [-Mz1 + Vy1 * (t * L) for t in x],
        }

    if nlf >= 6 and ndf >= 3:
        if is_truss and ndm == 3:
            # BUG TRAP: 3D Truss with ndf=3 also produces nlf=6 because
            # eleResponse('localForces') returns global-frame forces for all 3
            # translational DOFs at each node: [Fx1, Fy1, Fz1, Fx2, Fy2, Fz2].
            # The axial force magnitude = norm of the node-1 force vector.
            # Sign: node-1 force points away from element for tension → negative
            # local-x component → we negate to match positive = tension convention.
            N = math.sqrt(lf[0]**2 + lf[1]**2 + lf[2]**2)
            # Determine sign: if the dominant component at node 1 is negative,
            # it opposes the node1→node2 direction → element is in tension.
            dominant = max((lf[0], lf[1], lf[2]), key=abs)
            sign = 1.0 if dominant < 0 else -1.0
            return {"x": x, "N": [sign * N] * nep}

        # 2D frame element (e.g. elasticBeamColumn in 2D, ndf=3 = u,v,θ per node)
        # lf = [N1, V1, M1,  N2, V2, M2]
        # Moment varies linearly: M(x) = -M1 + V1*x*L  (beam equilibrium)
        N1, V1, M1 = lf[0], lf[1], lf[2]
        return {
            "x": x,
            "N": [-N1] * nep,
            "V": [V1] * nep,
            "M": [-M1 + V1 * (t * L) for t in x],
        }

    if nlf >= 2:
        # Truss element returning only axial forces: lf = [N1, N2]
        # Positive N = tension (opsvis convention: negate N1)
        return {
            "x": x,
            "N": [-lf[0]] * nep,
        }

    # Fallback for unrecognised element types
    return {"x": x, "N": [lf[0]] * nep} if nlf > 0 else {"x": x}


def _restore_ops(
    real_model: Any,
    real_node: Any,
    real_element: Any,
    real_fix: Any,
    real_load: Any,
) -> None:
    ops.model = real_model      # type: ignore[method-assign]
    ops.node = real_node        # type: ignore[method-assign]
    ops.element = real_element  # type: ignore[method-assign]
    ops.fix = real_fix          # type: ignore[method-assign]
    ops.load = real_load        # type: ignore[method-assign]


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: analysis_runner.py <script_path>"}))
        sys.exit(1)
    print(json.dumps(run(sys.argv[1])))
