"""Runs real openseespy analysis and captures results.

Input:  script path (sys.argv[1])
Output: JSON to stdout — Phase 1 model data + analysis results block
"""

import ast
import io
import json
import os
import sys
from typing import Any

import openseespy.opensees as ops


# Node counts for common element types (keep in sync with interceptor._NODE_COUNT)
_NODE_COUNT: dict[str, int] = {
    'elasticBeamColumn': 2,
    'forceBeamColumn': 2,
    'dispBeamColumn': 2,
    'Truss': 2,
    'TrussSection': 2,
    'CorotTruss': 2,
    'zeroLength': 2,
}


def _extract_tools(filepath: str) -> list[str]:
    try:
        with open(filepath, encoding='utf-8') as f:
            tree = ast.parse(f.read())
        tools: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == 'tools':
                tools.extend(alias.name for alias in node.names)
        return tools
    except Exception:
        return []


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
    materials: dict[int, dict[str, Any]] = {}       # matTag -> {"type": "Elastic", "E": float}
    sections_by_tag: dict[int, dict[str, Any]] = {} # secTag -> {"type": "Elastic", "E", "A", ...}
    element_args: dict[int, list[Any]] = {}         # eleTag -> trailing args after node tags
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
        ncount = _NODE_COUNT.get(etype, 2)
        node_tags = [int(a) for a in args[:ncount]]
        trailing = list(args[ncount:])
        elements.append({"tag": int(tag), "type": str(etype), "nodes": node_tags})
        element_args[int(tag)] = trailing
        real_element(etype, tag, *args)
    ops.element = patched_element  # type: ignore[method-assign]

    real_uniaxialMaterial = ops.uniaxialMaterial
    def patched_uniaxialMaterial(matType: str, matTag: int, *args: Any) -> None:
        if matType == 'Elastic' and len(args) >= 1:
            materials[int(matTag)] = {"type": "Elastic", "E": float(args[0])}
        real_uniaxialMaterial(matType, matTag, *args)
    ops.uniaxialMaterial = patched_uniaxialMaterial  # type: ignore[method-assign]

    real_section = ops.section
    def patched_section(secType: str, secTag: int, *args: Any) -> None:
        if secType == 'Elastic' and len(args) >= 3:
            entry: dict[str, Any] = {
                "type": "Elastic",
                "E": float(args[0]),
                "A": float(args[1]),
                "Iz": float(args[2]),
            }
            if len(args) >= 6:
                entry["Iy"] = float(args[3])
                entry["G"] = float(args[4])
                entry["J"] = float(args[5])
            sections_by_tag[int(secTag)] = entry
        real_section(secType, secTag, *args)
    ops.section = patched_section  # type: ignore[method-assign]

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

    filepath = os.path.abspath(script_path)
    script_dir = os.path.dirname(filepath)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            code = f.read()
        namespace = {
            '__name__': '__main__',
            '__file__': filepath,
        }
        exec(compile(code, filepath, 'exec'), namespace)
        converged = True
    except Exception as exc:
        error = str(exc)
    finally:
        sys.stdout = old_stdout
        _restore_ops(
            real_model, real_node, real_element, real_fix, real_load,
            real_uniaxialMaterial, real_section,
        )

    # --- Query results ---

    outputs_nodes: list[dict[str, Any]] = []
    outputs_elements: list[dict[str, Any]] = []
    outputs_sections: list[dict[str, Any]] = []

    coords_by_tag: dict[int, list[float]] = {n["tag"]: n["coords"] for n in nodes}

    if converged:
        for tag in recorded_nodes:
            try:
                disp = ops.nodeDisp(tag)
                reaction = ops.nodeReaction(tag)
            except Exception:
                continue
            outputs_nodes.append({
                "tag": tag,
                "coords": coords_by_tag.get(tag, []),
                "displacement": disp,
                "reaction": reaction,
            })

        for el in elements:
            tag = el["tag"]
            try:
                lf = list(ops.eleResponse(tag, 'localForces'))
            except Exception:
                continue

            outputs_elements.append({
                "eleTag": tag,
                "type": el["type"],
                "nodes": el["nodes"],
                "responses": {"localForce": lf},
            })

            sec = _section_for_element(el["type"], element_args.get(tag, []), materials, sections_by_tag)
            if sec is not None:
                outputs_sections.append({"eleTag": tag, **sec})

    return {
        "schema_version": 3,
        "ndm": ndm,
        "ndf": ndf,
        "nodes": nodes,
        "elements": elements,
        "supports": supports,
        "nodal_loads": nodal_loads,
        "error": error,
        "tools": _extract_tools(os.path.abspath(script_path)),
        "outputs": {
            "nodes": outputs_nodes,
            "elements": outputs_elements,
            "sections": outputs_sections,
        },
    }


def _section_for_element(
    etype: str,
    trailing: list[Any],
    materials: dict[int, dict[str, Any]],
    sections_by_tag: dict[int, dict[str, Any]],
) -> dict[str, Any] | None:
    """Synthesize an ElasticSection-shaped dict for an element, or None if not resolvable."""
    if etype in ("Truss", "CorotTruss") and len(trailing) >= 2:
        A = float(trailing[0])
        mat = materials.get(int(trailing[1]))
        if mat and mat["type"] == "Elastic":
            return {"type": "Elastic", "E": mat["E"], "A": A}

    if etype == "TrussSection" and len(trailing) >= 1:
        sec = sections_by_tag.get(int(trailing[0]))
        if sec is not None:
            return dict(sec)

    if etype == "elasticBeamColumn" and len(trailing) >= 2:
        # Section form: (secTag, transfTag, ...)
        if isinstance(trailing[0], int) and isinstance(trailing[1], int):
            sec = sections_by_tag.get(int(trailing[0]))
            if sec is not None:
                return dict(sec)
        # Inline 3D form: (A, E, G, Jxx, Iy, Iz, transfTag, ...)
        if len(trailing) >= 7 and isinstance(trailing[6], int):
            return {
                "type": "Elastic",
                "E":  float(trailing[1]),
                "A":  float(trailing[0]),
                "G":  float(trailing[2]),
                "J":  float(trailing[3]),
                "Iy": float(trailing[4]),
                "Iz": float(trailing[5]),
            }
        # Inline 2D form: (A, E, Iz, transfTag, ...)
        if len(trailing) >= 4 and isinstance(trailing[3], int):
            return {
                "type": "Elastic",
                "E":  float(trailing[1]),
                "A":  float(trailing[0]),
                "Iz": float(trailing[2]),
            }
    return None


def _restore_ops(
    real_model: Any,
    real_node: Any,
    real_element: Any,
    real_fix: Any,
    real_load: Any,
    real_uniaxialMaterial: Any,
    real_section: Any,
) -> None:
    ops.model = real_model                          # type: ignore[method-assign]
    ops.node = real_node                            # type: ignore[method-assign]
    ops.element = real_element                      # type: ignore[method-assign]
    ops.fix = real_fix                              # type: ignore[method-assign]
    ops.load = real_load                            # type: ignore[method-assign]
    ops.uniaxialMaterial = real_uniaxialMaterial    # type: ignore[method-assign]
    ops.section = real_section                      # type: ignore[method-assign]


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: analysis_runner.py <script_path>"}))
        sys.exit(1)
    print(json.dumps(run(sys.argv[1])))
