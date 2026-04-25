"""Flexural buckling check per EN 1993-1-1:2005 clause 6.3.1.

Supports Truss and elasticBeamColumn elements. Governing axis is the one with
the smaller radius of gyration → smaller chi → smaller N_b_Rd.

Self-contained: inlines the EN 1993-1-1 helpers used by this tool
(lambda_bar per 6.50, chi per 6.49, N_b_Rd per 6.47, unity check per 6.46,
imperfection factors per Table 6.1).

UNITS: kN, m, s — forces in kN, moments in kN.m, lengths in m, stresses in kN/m².
       Your OpenSees model must use consistent kN/m for the results to be meaningful.

Assumptions:
- Truss (no section shape): solid circular → i = sqrt(A / (4*pi))
- elasticBeamColumn: i_y = sqrt(Iy/A), i_z = sqrt(Iz/A); governing = min
- Steel grade S355: fy = 355 MPa
- Buckling curve 'c' (alpha = 0.49) — conservative default
- gamma_M1 = 1.0
- Pin-pin supports: L_cr = L
"""
import math
from enum import Enum
from typing import Any


# --- Table 6.1: imperfection factors ------------------------------------

class BucklingCurve(str, Enum):
    A0 = "a0"
    A = "a"
    B = "b"
    C = "c"
    D = "d"


_IMPERFECTION_FACTORS: dict[BucklingCurve, float] = {
    BucklingCurve.A0: 0.13,
    BucklingCurve.A:  0.21,
    BucklingCurve.B:  0.34,
    BucklingCurve.C:  0.49,
    BucklingCurve.D:  0.76,
}


def get_imperfection_factor(curve: BucklingCurve) -> float:
    return _IMPERFECTION_FACTORS[curve]


# --- Formula 6.50: non-dimensional slenderness --------------------------

def calculate_lambda_bar_direct(L_cr: float, i: float, f_y: float, E: float) -> float:
    """lambda_bar = (L_cr / i) / (pi * sqrt(E / f_y))."""
    if i <= 0:
        raise ValueError("Radius of gyration must be positive")
    lambda_1 = math.pi * math.sqrt(E / f_y)
    return (L_cr / i) / lambda_1


# --- Formula 6.49: reduction factor chi ---------------------------------

def calculate_chi_from_alpha(alpha: float, lambda_bar: float) -> float:
    """chi = 1 / (phi + sqrt(phi^2 - lambda_bar^2)), capped at 1.0; =1 if lambda_bar <= 0.2."""
    if lambda_bar <= 0.2:
        return 1.0
    phi = 0.5 * (1 + alpha * (lambda_bar - 0.2) + lambda_bar ** 2)
    discriminant = max(phi ** 2 - lambda_bar ** 2, 0.0)
    chi = 1.0 / (phi + math.sqrt(discriminant))
    return min(chi, 1.0)


# --- Formula 6.47: design buckling resistance ---------------------------

def calculate_N_b_Rd(chi: float, A: float, f_y: float, gamma_M1: float = 1.0) -> float:
    """N_b,Rd = chi * A * f_y / gamma_M1."""
    return (chi * A * f_y) / gamma_M1


# --- Formula 6.46: unity check ------------------------------------------

def check_buckling_resistance(N_Ed: float, N_b_Rd: float) -> float:
    """Returns utilization ratio N_Ed / N_b,Rd."""
    if N_b_Rd <= 0:
        raise ValueError("Buckling resistance must be positive")
    return abs(N_Ed) / N_b_Rd


# --- Tool entry point ---------------------------------------------------

_FY = 355_000.0  # S355 yield strength in kN/m² (= 355 MPa)
_GAMMA_M1 = 1.0
_CURVE = BucklingCurve.C


def run(outputs: dict[str, Any]) -> dict[str, Any]:
    coords = {n["tag"]: n["coords"] for n in outputs["nodes"]}
    sections = {s["eleTag"]: s for s in outputs["sections"]}
    alpha = get_imperfection_factor(_CURVE)

    results = []
    for el in outputs["elements"]:
        sec = sections.get(el["eleTag"])
        if sec is None or sec["type"] != "Elastic":
            continue

        tag = el["eleTag"]
        n1, n2 = el["nodes"][0], el["nodes"][1]
        c1, c2 = coords[n1], coords[n2]
        L = math.sqrt(sum((a - b) ** 2 for a, b in zip(c1, c2)))

        N = el["responses"]["localForce"][0]
        # Truss returns axial positive = tension; beam-column node-1 axial is
        # positive-outward = compression. Normalize to positive = tension.
        N_tension = N if el["type"].lower() in ("truss", "corottruss") else -N
        N_Ed = abs(N_tension) if N_tension < 0 else 0.0

        E, A = sec["E"], sec["A"]
        if "Iy" in sec and "Iz" in sec:
            i_y = math.sqrt(sec["Iy"] / A)
            i_z = math.sqrt(sec["Iz"] / A)
            i = min(i_y, i_z)
            axis = "y" if i_y <= i_z else "z"
            i_desc = f"governing radius of gyration — min(i_y={i_y:.5f}, i_z={i_z:.5f}) about axis {axis} (m)"
        else:
            i = math.sqrt(A / (4 * math.pi))
            i_desc = "radius of gyration — solid circular: sqrt(A/(4*pi)) (m)"

        lambda_bar = calculate_lambda_bar_direct(L, i, _FY, E)
        chi = calculate_chi_from_alpha(alpha, lambda_bar)
        N_b_Rd = calculate_N_b_Rd(chi, A, _FY, _GAMMA_M1)
        ratio = check_buckling_resistance(N_Ed, N_b_Rd) if N_Ed > 0 else 0.0
        status = "compression" if N_tension < 0 else "tension (skipped)"

        results.extend([
            {"tag": tag, "name": "N_Ed",       "value": round(N_Ed, 4),        "description": f"design compression — kN ({status})"},
            {"tag": tag, "name": "L",          "value": round(L, 6),           "description": "member length (m)"},
            {"tag": tag, "name": "E",          "value": E,                     "description": "Young's modulus (kN/m^2)"},
            {"tag": tag, "name": "A",          "value": A,                     "description": "cross-section area (m^2)"},
            {"tag": tag, "name": "i",          "value": round(i, 8),           "description": i_desc},
            {"tag": tag, "name": "fy",         "value": _FY,                   "description": "yield strength — S355 assumed (kN/m^2)"},
            {"tag": tag, "name": "curve",      "value": _CURVE.value,          "description": "buckling curve (Table 6.2)"},
            {"tag": tag, "name": "alpha",      "value": alpha,                 "description": "imperfection factor (Table 6.1)"},
            {"tag": tag, "name": "lambda_bar", "value": round(lambda_bar, 4),  "description": "non-dimensional slenderness (formula 6.50)"},
            {"tag": tag, "name": "chi",        "value": round(chi, 4),         "description": "reduction factor (formula 6.49)"},
            {"tag": tag, "name": "N_b_Rd",     "value": round(N_b_Rd, 2),      "description": "design buckling resistance — kN (formula 6.47)"},
            {"tag": tag, "name": "ratio",      "value": round(ratio, 4),       "description": "N_Ed/N_b_Rd — pass if <= 1.0 (formula 6.46)"},
        ])
    return {"elements": results}
