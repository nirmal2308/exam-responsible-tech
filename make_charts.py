"""Generate every chart used in the report from results/results.json.
    python make_charts.py
"""
import json, os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

HERE = os.path.dirname(__file__)
R = json.load(open(os.path.join(HERE, "results", "results.json")))
OUT = os.path.join(HERE, "results", "charts")
os.makedirs(OUT, exist_ok=True)

NAVY, BLUE, TEAL, AMBER, RED, GREEN, GREY, LIGHT = "#1F3864", "#2E75B6", "#2A9D8F", "#E9A23B", "#C0392B", "#5B8C3A", "#8C8C8C", "#DEEAF6"
ENG_COL = {"v0": GREY, "v1": AMBER, "v2": BLUE, "v3": NAVY}
ENG_LAB = {"v0": "v0 baseline (keywords)", "v1": "v1 initial (stem+synonyms)", "v2": "v2 (+negation guard, flags)", "v3": "v3 (clause-aware)"}
plt.rcParams.update({"font.size": 9, "axes.titlesize": 10, "axes.titleweight": "bold", "axes.spines.top": False,
                     "axes.spines.right": False, "axes.grid": True, "grid.alpha": 0.25, "figure.dpi": 100, "savefig.dpi": 200})


def save(fig, name):
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, name), bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------- 1 stakeholder influence/interest grid
stake = [("Controller of\nexaminations", 9, 9), ("Examiners", 7, 9), ("Moderators", 6.5, 7.5), ("Students", 3, 9.5),
         ("Department\nheads", 6, 5), ("Administrators", 5.5, 3.5), ("External verifiers /\npartner institutions", 3.5, 4),
         ("Data-protection\nofficer", 7.5, 4.5)]
fig, ax = plt.subplots(figsize=(6.6, 4.4))
ax.axhline(5, color=GREY, lw=0.8); ax.axvline(5, color=GREY, lw=0.8)
for n, x, y in stake:
    ax.scatter(x, y, s=170, color=BLUE, edgecolor=NAVY, zorder=3)
    ax.annotate(n, (x, y), textcoords="offset points", xytext=(9, 4), fontsize=8)
ax.set_xlim(0, 10.5); ax.set_ylim(0, 10.8)
ax.set_xlabel("Influence over the decision (1-10)"); ax.set_ylabel("Impact of the outcome on the stakeholder (1-10)")
for (x, y, t) in [(0.3, 10.3, "Keep informed"), (5.3, 10.3, "Manage closely"), (0.3, 0.3, "Monitor"), (5.3, 0.3, "Keep satisfied")]:
    ax.text(x, y, t, color=NAVY, fontsize=8.5, fontweight="bold", alpha=0.7)
ax.set_title("Stakeholder influence-impact map (author's judgement)")
save(fig, "fig_stakeholders.png")

# ---------------------------------------------------------------- 2 weighted contributions (original)
S = R["selection"]; crit = S["criteria"]
palette = [NAVY, BLUE, TEAL, GREEN, AMBER, "#C77D5B", RED]
def stacked(contrib, totals, title, fname, keys=("A", "B", "C", "D"), labels=None):
    fig, ax = plt.subplots(figsize=(6.8, 3.9))
    left = np.zeros(len(keys))
    for i, c in enumerate(crit):
        vals = np.array([contrib[k][i] for k in keys])
        ax.barh(range(len(keys)), vals, left=left, color=palette[i], label=c, edgecolor="white")
        left += vals
    for j, k in enumerate(keys):
        ax.text(left[j] + 0.05, j, f"{totals[k]:.2f}", va="center", fontweight="bold", color=NAVY)
    ax.set_yticks(range(len(keys)))
    ax.set_yticklabels(labels or [f"{k}: {S['alts'][k]}" for k in keys], fontsize=8.5)
    ax.invert_yaxis(); ax.set_xlim(0, 5.2); ax.set_xlabel("Weighted score (max 5)")
    ax.legend(ncol=2, fontsize=7.5, loc="lower right", frameon=False); ax.set_title(title)
    save(fig, fname)
stacked(S["contrib0"], S["totals0"], "Weighted decision matrix: contribution of each criterion", "fig_matrix_original.png")

# ---------------------------------------------------------------- 3 sensitivity
fig, axs = plt.subplots(1, 3, figsize=(7.4, 3.0))
ax = axs[0]
xs = [x for x, _ in S["sweep_usefulness"]]
for k, c in zip("ABCD", [NAVY, AMBER, GREY, RED]):
    ax.plot(xs, [t[k] for _, t in S["sweep_usefulness"]], color=c, marker="o", ms=2.5, label=k)
ax.axvline(S["crossover_usefulness"], color=RED, ls=":", lw=1)
ax.set_title("S1: weight of Usefulness"); ax.set_xlabel("Usefulness weight (%)"); ax.set_ylabel("Weighted score"); ax.legend(fontsize=7, frameon=False)
ax = axs[1]
ds = [d for d, _ in S["ml_sweep"]]
ax.plot(ds, [t["A"] for _, t in S["ml_sweep"]], color=NAVY, marker="o", ms=3, label="A")
ax.plot(ds, [t["B"] for _, t in S["ml_sweep"]], color=AMBER, marker="o", ms=3, label="B")
ax.set_title("S2: ML readiness of B"); ax.set_xlabel("Score gain on 4 criteria"); ax.legend(fontsize=7, frameon=False)
ax = axs[2]
mc = S["mc"]
ax.bar(list(mc.keys()), [v * 100 for v in mc.values()], color=[NAVY, AMBER, GREY, RED])
ax.set_title("S3: share of 10,000 random\nweight+score draws won"); ax.set_ylabel("%"); ax.set_ylim(0, 105)
for i, v in enumerate(mc.values()):
    ax.text(i, v * 100 + 2, f"{v*100:.1f}", ha="center", fontsize=8)
save(fig, "fig_sensitivity.png")

# ---------------------------------------------------------------- 4 point-level credit by answer type
pl = R["point_level"]; types = ["exact", "paraphrase", "unfamiliar", "negated", "absent"]
fig, ax = plt.subplots(figsize=(6.8, 3.6))
w = 0.2
for i, k in enumerate(["v0", "v1", "v2", "v3"]):
    vals = [pl[k][t]["rate"] * 100 for t in types]
    ax.bar(np.arange(5) + (i - 1.5) * w, vals, w, color=ENG_COL[k], label=ENG_LAB[k])
ax.set_xticks(range(5)); ax.set_xticklabels(["exact\nkeyword", "paraphrase\n(known synonym)", "unfamiliar\nterm", "negated\nstatement", "absent\n(no point)"], fontsize=8)
ax.set_ylabel("Rubric points credited (%)"); ax.set_ylim(0, 118)
for x0 in (0, 1, 2):
    ax.text(x0, 109, "expert: credit", ha="center", fontsize=7.5, color=GREEN)
for x0 in (3, 4):
    ax.text(x0, 109, "expert: no credit", ha="center", fontsize=7.5, color=RED)
ax.legend(fontsize=7.5, ncol=2, frameon=False, loc="center right", bbox_to_anchor=(1.0, 0.55))
ax.set_title("Point-level behaviour of each engine by answer type")
save(fig, "fig_point_credit.png")

# ---------------------------------------------------------------- 5 script-level metrics + subsets
sl = R["script_level"]
fig, axs = plt.subplots(1, 2, figsize=(7.4, 3.3), gridspec_kw={"width_ratios": [1, 1.5]})
ax = axs[0]
ks = ["v0", "v1", "v2", "v3"]
ax.bar(range(4), [sl[k]["mae"] for k in ks], color=[ENG_COL[k] for k in ks])
for i, k in enumerate(ks):
    ax.text(i, sl[k]["mae"] + 0.03, f"{sl[k]['mae']:.2f}", ha="center", fontsize=8)
ax.set_xticks(range(4)); ax.set_xticklabels(ks); ax.set_ylabel("Mean absolute error (marks of 5)"); ax.set_title("Script-level error")
ax = axs[1]
ss = R["subsets"]; names = ["all scripts", "contains paraphrase", "contains unfamiliar term", "contains negated statement", "run-on style answer"]
for i, k in enumerate(ks):
    ax.bar(np.arange(len(names)) + (i - 1.5) * 0.2, [ss[n][k]["exact"] * 100 for n in names], 0.2, color=ENG_COL[k], label=k)
ax.set_xticks(range(len(names))); ax.set_xticklabels(["all\n(240)", "paraphrase\n(164)", "unfamiliar\n(131)", "negated\n(103)", "run-on\n(71)"], fontsize=8)
ax.set_ylabel("Exact agreement with expert (%)"); ax.set_title("Exact agreement by script type"); ax.legend(fontsize=7.5, ncol=4, frameon=False, loc="upper right")
ax.set_ylim(0, 70)
save(fig, "fig_script_level.png")

# ---------------------------------------------------------------- 6 stakes-discrepancy stacked bars
sm = R["stakes_matrix"]
classes = ["exact", "under-marked, same outcome", "under-marked, pass/fail flips", "over-marked, same outcome", "over-marked, pass/fail flips"]
cols = [GREEN, "#9DC3E6", BLUE, "#F5C37A", RED]
fig, ax = plt.subplots(figsize=(6.8, 2.9))
for j, k in enumerate(["v1", "v2", "v3"]):
    left = 0
    for c, col in zip(classes, cols):
        n = sm[k][c]["n"]
        ax.barh(j, n, left=left, color=col, edgecolor="white", label=c if j == 0 else None)
        if n >= 8:
            ax.text(left + n / 2, j, str(n), ha="center", va="center", color="white" if col in (BLUE, RED, GREEN) else "black", fontsize=8)
        left += n
ax.set_yticks(range(3)); ax.set_yticklabels(["v1 initial", "v2 revised", "v3 clause-aware"]); ax.invert_yaxis()
ax.set_xlabel("Scripts (n = 240)"); ax.set_title("Stakes-discrepancy: where suggestions differ from the expert mark")
ax.legend(fontsize=7, ncol=3, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.28))
save(fig, "fig_stakes.png")

# ---------------------------------------------------------------- 7 flag trade-off
sw = R["threshold_sweep"]
fig, ax = plt.subplots(figsize=(6.2, 3.2))
ax.plot([s["threshold"] for s in sw], [s["recall_ge2"] * 100 for s in sw], marker="o", color=NAVY, label="Recall of errors >= 2 marks")
ax.plot([s["threshold"] for s in sw], [s["recall_ge1"] * 100 for s in sw], marker="s", color=BLUE, label="Recall of errors >= 1 mark")
ax.plot([s["threshold"] for s in sw], [s["share_high"] * 100 for s in sw], marker="^", color=RED, ls="--", label="Share of scripts flagged HIGH")
ax.set_xticks([1, 2, 3, 4]); ax.set_xlabel("Unmatched-content threshold (clauses)"); ax.set_ylabel("%")
ax.axvline(2, color=GREY, ls=":"); ax.text(2.04, 8, "chosen\noperating point", fontsize=7.5, color=GREY)
ax.legend(fontsize=7.5, frameon=False, loc="lower left", bbox_to_anchor=(0.35, 0.1)); ax.set_title("Safety versus workload: flag threshold sweep (v3)")
save(fig, "fig_flag_tradeoff.png")

# ---------------------------------------------------------------- 8 tamper matrix
tm = R["tamper_matrix"]; tests = list(tm.keys()); schemes = ["plain", "trig", "chain", "chain+anchor"]
sch_lab = ["Plain audit\ntable", "Append-only\ntable (triggers)", "Hash chain", "Hash chain +\nexternal anchor"]
fig, ax = plt.subplots(figsize=(6.9, 2.8))
ax.grid(False)
for i, t in enumerate(tests):
    for j, s in enumerate(schemes):
        v = tm[t][s]
        if v == "DETECTED": col, txt = GREEN, "detected"
        elif v == "UNDETECTED": col, txt = RED, "undetected"
        else: col, txt = AMBER, "blocked by SQL,\nbypass undetected"
        ax.add_patch(plt.Rectangle((j, len(tests) - 1 - i), 0.96, 0.92, color=col, alpha=0.9))
        ax.text(j + 0.48, len(tests) - 1 - i + 0.46, txt, ha="center", va="center", color="white", fontsize=8, fontweight="bold")
ax.set_xlim(0, 4); ax.set_ylim(0, len(tests))
ax.set_xticks([j + 0.48 for j in range(4)]); ax.set_xticklabels(sch_lab, fontsize=8)
ax.set_yticks([len(tests) - 1 - i + 0.46 for i in range(len(tests))]); ax.set_yticklabels([t.split(" ", 1)[0] + " " + t.split(" ", 1)[1] for t in tests], fontsize=8)
ax.xaxis.tick_top(); [s.set_visible(False) for s in ax.spines.values()]; ax.tick_params(length=0)
save(fig, "fig_tamper.png")

# ---------------------------------------------------------------- 9 cost
C = R["cost"]["alts"]; names = ["A", "B", "C", "D", "A2"]
lab = ["A", "B", "C", "D", "A-rev"]
fig, axs = plt.subplots(1, 2, figsize=(7.4, 3.3))
ax = axs[0]
cap = [C[k]["capex"] / 1e5 for k in names]; inf = [5 * C[k]["infra"] / 1e5 for k in names]; stf = [5 * C[k]["staff"] / 1e5 for k in names]
ax.bar(lab, cap, color=GREY, label="Build (one-off)"); ax.bar(lab, inf, bottom=cap, color=BLUE, label="Infrastructure x5 yr")
ax.bar(lab, stf, bottom=np.array(cap) + np.array(inf), color=NAVY, label="People & labelling x5 yr")
for i, k in enumerate(names):
    ax.text(i, C[k]["tco5"] / 1e5 + 1, f"{C[k]['tco5']/1e5:.1f}", ha="center", fontsize=8)
ax.set_ylabel("Rs. lakh over 5 years (estimate)"); ax.set_title("Five-year total cost of ownership"); ax.legend(fontsize=7, frameon=False)
ax = axs[1]
inf1 = [C[k]["infra"] / 1e5 for k in names]
cols2 = [GREEN if C[k]["fits_revised_budget"] else (AMBER if C[k]["fits_original_budget"] else RED) for k in names]
ax.bar(lab, inf1, color=cols2)
ax.axhline(R["cost"]["assumptions"]["budget_compute_original_inr"] / 1e5, color=NAVY, ls="--"); ax.text(-0.45, 3.06, "original budget", ha="left", fontsize=7.5, color=NAVY)
ax.axhline(R["cost"]["assumptions"]["budget_compute_revised_inr"] / 1e5, color=RED, ls="--"); ax.text(1.6, 1.55, "halved budget", ha="left", fontsize=7.5, color=RED)
for i, v in enumerate(inf1):
    ax.text(i, v + 0.06, f"{v:.2f}", ha="center", fontsize=8)
ax.set_ylabel("Rs. lakh per year (estimate)"); ax.set_title("Annual computing cost vs budget")
ax.legend(handles=[Patch(color=GREEN, label="fits halved budget"), Patch(color=AMBER, label="fits original only"), Patch(color=RED, label="fits neither")], fontsize=7, frameon=False, loc="upper left")
ax.set_ylim(0, 4.6)
save(fig, "fig_cost.png")

# ---------------------------------------------------------------- 10 risk heat map
risks = [  # id, short, likelihood, impact
    ("R1", "Automation bias / anchoring", 4, 4), ("R2", "Vocabulary bias against unconventional writers", 4, 4),
    ("R3", "Flag read as probability", 3, 4), ("R4", "Leak of student answers and marks", 3, 5),
    ("R5", "Inaccurate mark cannot be corrected", 3, 4), ("R6", "Accountability gap for published results", 2, 5),
    ("R7", "Inconsistent examiner reference data", 4, 3), ("R8", "Valid chain mistaken for correct marks", 3, 3),
    ("R9", "Budget cuts erode monitoring/backups", 3, 3)]
json.dump([{"id": a, "name": b, "L": c, "I": d, "score": c * d} for a, b, c, d in risks], open(os.path.join(HERE, "results", "risks.json"), "w"), indent=1)
fig, ax = plt.subplots(figsize=(5.8, 4.4))
ax.grid(False)
for L in range(1, 6):
    for I in range(1, 6):
        s = L * I
        col = "#9BCB7B" if s <= 6 else ("#F6D36B" if s <= 12 else "#E8836B")
        ax.add_patch(plt.Rectangle((I - 0.5, L - 0.5), 1, 1, color=col, alpha=0.75, ec="white"))
cells = {}
for rid, _, L, I in risks:
    cells.setdefault((L, I), []).append(rid)
for (L, I), ids in cells.items():
    ax.text(I, L, "\n".join(ids), ha="center", va="center", fontsize=8.5, fontweight="bold", color=NAVY)
ax.set_xlim(0.5, 5.5); ax.set_ylim(0.5, 5.5); ax.set_xticks(range(1, 6)); ax.set_yticks(range(1, 6))
ax.set_xlabel("Impact (1 low - 5 severe)"); ax.set_ylabel("Likelihood (1 rare - 5 almost certain)")
ax.set_title("Inherent risk heat map (before safeguards)")
save(fig, "fig_risk_heatmap.png")

# ---------------------------------------------------------------- 11 revised matrix
t0, t1 = S["totals0"], S["totals1"]
fig, ax = plt.subplots(figsize=(6.4, 3.3))
x = np.arange(4)
ax.bar(x - 0.2, [t0[k] for k in "ABCD"], 0.4, color=GREY, label="Original evidence and weights")
ax.bar(x + 0.2, [t1[k] for k in "ABCD"], 0.4, color=NAVY, label="Day-4 evidence and weights")
for i, k in enumerate("ABCD"):
    ax.text(i - 0.2, t0[k] + 0.05, f"{t0[k]:.2f}", ha="center", fontsize=8); ax.text(i + 0.2, t1[k] + 0.05, f"{t1[k]:.2f}", ha="center", fontsize=8)
ax.set_xticks(x); ax.set_xticklabels(["A: rules +\nhuman (A-rev)", "B: AI/ML", "C: Blockchain", "D: Combined"], fontsize=8.5)
ax.set_ylabel("Weighted score (max 5)"); ax.set_ylim(0, 5.3); ax.legend(fontsize=8, frameon=False); ax.set_title("Selection model before and after the changed requirement")
save(fig, "fig_matrix_revised.png")

# ---------------------------------------------------------------- 12 label inconsistency
cat = R["categories"]; cn = ["Operating Systems", "Database Systems", "Software Engineering"]
fig, axs = plt.subplots(1, 3, figsize=(7.5, 3.1))
ax = axs[0]
ax.bar(range(3), [cat[c]["hist_vs_expert_qwk"] for c in cn], color=[BLUE, BLUE, RED])
ax.set_xticks(range(3)); ax.set_xticklabels(["OS", "DBMS", "SE"]); ax.set_ylim(0, 1.05); ax.set_title("Historical vs expert\n(weighted kappa)")
for i, c in enumerate(cn):
    ax.text(i, cat[c]["hist_vs_expert_qwk"] + 0.02, f"{cat[c]['hist_vs_expert_qwk']:.2f}", ha="center", fontsize=8)
ax = axs[1]
ax.bar(np.arange(3) - 0.2, [cat[c]["engine_vs_expert_exact"] * 100 for c in cn], 0.4, color=NAVY, label="vs expert reference")
ax.bar(np.arange(3) + 0.2, [cat[c]["engine_vs_hist_exact"] * 100 for c in cn], 0.4, color=AMBER, label="vs historical marks")
ax.set_xticks(range(3)); ax.set_xticklabels(["OS", "DBMS", "SE"]); ax.set_ylabel("Exact agreement of v3 (%)"); ax.set_title("Same engine, two references"); ax.legend(fontsize=7, frameon=False, loc="upper right"); ax.set_ylim(0, 70)
ax = axs[2]
nc = R["noise_ceiling"]
ax.plot([n["sd"] for n in nc], [n["exact_ceiling"] * 100 for n in nc], marker="o", color=NAVY, label="exact")
ax.plot([n["sd"] for n in nc], [n["within1_ceiling"] * 100 for n in nc], marker="s", color=BLUE, label="within +/-1")
ax.set_xlabel("Reference noise (SD, marks)"); ax.set_ylabel("Best possible agreement (%)"); ax.set_title("Ceiling for a perfect scorer"); ax.legend(fontsize=7, frameon=False); ax.set_ylim(0, 105)
save(fig, "fig_label_inconsistency.png")
print("charts written:", sorted(os.listdir(OUT)))
