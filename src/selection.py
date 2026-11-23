"""Weighted decision matrix, sensitivity analysis and Monte-Carlo robustness check."""
import numpy as np

CRITERIA = ["Usefulness", "Reliability", "Privacy", "Fairness & explainability",
            "Cost (5-year)", "Sustainability", "Correctability & accountability"]
ALTS = {"A": "Conventional + deterministic rules", "B": "AI/ML scoring assistance",
        "C": "Blockchain credential verification", "D": "Combined AI/ML + Blockchain"}

W0 = [15, 20, 15, 15, 15, 10, 10]
S0 = {"A": [3, 4, 5, 4, 5, 5, 4], "B": [4, 3, 3, 2, 3, 3, 3],
      "C": [2, 3, 2, 3, 2, 2, 2], "D": [4, 3, 2, 2, 1, 1, 2]}

# Day-4 changed evidence: inconsistent labels, partner withdrawal, halved budget, record correction
W1 = [10, 20, 15, 10, 20, 5, 20]
S1 = {"A": [3, 4, 5, 4, 5, 5, 5], "B": [4, 2, 3, 2, 2, 2, 2],
      "C": [1, 2, 2, 3, 1, 2, 1], "D": [3, 2, 2, 2, 1, 1, 1]}


def totals(weights, scores):
    w = np.array(weights, float) / sum(weights)
    return {k: float(np.dot(w, v)) for k, v in scores.items()}


def contributions(weights, scores):
    w = np.array(weights, float) / sum(weights)
    return {k: [float(w[i] * v[i]) for i in range(len(w))] for k, v in scores.items()}


def sweep_weight(idx, scores=S0, base=W0, grid=range(0, 81, 5)):
    out = []
    others = [i for i in range(len(base)) if i != idx]
    osum = sum(base[i] for i in others)
    for x in grid:
        w = [0.0] * len(base)
        w[idx] = x
        for i in others:
            w[i] = (100 - x) * base[i] / osum
        out.append((x, totals(w, scores)))
    return out


def crossover(series, a="A", b="B"):
    for x, t in series:
        if t[b] >= t[a]:
            return x
    return None


def ml_readiness_sweep(deltas=(0, 0.5, 1, 1.5, 2, 2.5, 3)):
    """Improve B's Reliability, Privacy, Fairness and Correctability together (clean labels, anonymised
    training data, validated explanations); cap at 5."""
    res = []
    for d in deltas:
        s = dict(S0); b = list(S0["B"])
        for i in (1, 2, 3, 6):
            b[i] = min(5, b[i] + d)
        s["B"] = b
        res.append((d, totals(W0, s)))
    return res


def monte_carlo(n=10000, seed=7, weights_only=False):
    rng = np.random.default_rng(seed)
    keys = list(S0)
    wins = {k: 0 for k in keys}
    base = np.array([S0[k] for k in keys], float)
    for _ in range(n):
        w = rng.dirichlet(np.ones(len(CRITERIA)))
        s = base.copy()
        if not weights_only:
            mask = rng.random(s.shape) < 0.3
            s = np.clip(s + mask * rng.choice([-1, 1], size=s.shape), 1, 5)
        t = s @ w
        wins[keys[int(np.argmax(t))]] += 1
    return {k: wins[k] / n for k in keys}
