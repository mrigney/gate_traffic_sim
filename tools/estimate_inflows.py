"""Reconcile origin-zone inflows from two rough, conflicting sources:

  1. Per-gate daily totals (trusted, from reports):  gate_total = split^T @ inflow
  2. Your prior guess of each zone's size (rough but keeps the problem well-posed)

Back-solving from gate totals ALONE is ill-posed: West/North/East all feed the
same north gates with similar proportions, so the gate totals can't separate
them and the naive solution swings wildly (and negative). We instead solve a
*regularized* least squares that stays near the priors while bending toward the
gate totals:

    minimize  || split^T x - gate_totals ||^2  +  lambda * || x - prior ||^2

lambda is the trust dial:
    lambda -> 0    trust the gate totals (unstable here)
    lambda -> inf  trust your priors (ignore gate totals)

The sweep below shows the whole spectrum so you can pick a sane operating point.
"""

from __future__ import annotations

import numpy as np

ZONES = ["West/Madison", "North/Research", "East/Central", "South Huntsville", "Far South"]
GATES = ["G1", "G9", "G10", "G7", "G3"]

# Habit split matrix: MATRIX[zone][gate]. Each row should sum to ~1.0.
MATRIX = {
    "West/Madison":     {"G1": 0.45, "G9": 0.45, "G10": 0.10},
    "North/Research":   {"G1": 0.08, "G9": 0.62, "G10": 0.30},
    "East/Central":     {"G9": 0.50, "G10": 0.32, "G7": 0.18},
    "South Huntsville": {"G7": 0.72, "G3": 0.28},
    "Far South":        {"G7": 0.08, "G3": 0.92},
}

# Trusted per-gate daily totals.
GATE_TOTALS = {"G1": 7500, "G9": 25000, "G10": 7500, "G7": 7500, "G3": 3000}

# Prior guess of zone inflows (your intuition: four zones roughly equal, South &
# West slightly higher, Far South much lower). Only the relative sizes matter.
PRIOR = {
    "West/Madison": 12000,
    "North/Research": 10000,
    "East/Central": 10000,
    "South Huntsville": 12000,
    "Far South": 6500,
}

LAMBDAS = [0.0, 0.02, 0.1, 0.5, 5.0]


def build():
    A = np.zeros((len(GATES), len(ZONES)))  # gates x zones = split^T
    for zi, z in enumerate(ZONES):
        for gi, g in enumerate(GATES):
            A[gi, zi] = MATRIX[z].get(g, 0.0)
    b = np.array([GATE_TOTALS[g] for g in GATES], dtype=float)
    p = np.array([PRIOR[z] for z in ZONES], dtype=float)
    return A, b, p


def solve(A, b, p, lam):
    n = A.shape[1]
    A_aug = np.vstack([A, np.sqrt(lam) * np.eye(n)])
    b_aug = np.concatenate([b, np.sqrt(lam) * p])
    try:
        from scipy.optimize import nnls
        x, _ = nnls(A_aug, b_aug)
    except ImportError:
        x, *_ = np.linalg.lstsq(A_aug, b_aug, rcond=None)
    resid = A @ x - b
    rms = float(np.sqrt(np.mean(resid ** 2)))
    return x, rms


def main():
    A, b, p = build()
    results = [(lam, *solve(A, b, p, lam)) for lam in LAMBDAS]

    head = f"{'Zone':<18}" + "".join(f"{('lam=' + str(lam)):>11}" for lam in LAMBDAS)
    print(head)
    print("-" * len(head))
    for zi, z in enumerate(ZONES):
        row = f"{z:<18}" + "".join(f"{res[1][zi]:>11.0f}" for res in results)
        print(row)
    print("-" * len(head))
    print(f"{'TOTAL':<18}" + "".join(f"{res[1].sum():>11.0f}" for res in results))
    print(f"{'gate RMS error':<18}" + "".join(f"{res[2]:>11.0f}" for res in results))
    print("\n(lam=0 trusts gate totals -> unstable; large lam trusts your priors.)")


if __name__ == "__main__":
    main()
