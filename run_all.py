"""Run every experiment of the demonstrator and write results/results.json.

    python run_all.py

Deterministic: the synthetic dataset, the Monte-Carlo checks and the simulated
examiner noise all use fixed seeds, so accuracy numbers reproduce exactly.
Timing and size figures are MEASURED on the machine that runs the script and will vary.
"""
import csv, json, os, statistics, time
import numpy as np
from src import dataset as D
from src.rubric_engine import score_v0, score_v1, score_v2, score_v3, grade_band
from src import selection as SEL
from src import costmodel as COST
from src.validation import run_validation, fresh, happy_path
from src.store import Store

OUT = os.path.join(os.path.dirname(__file__), "results")
os.makedirs(os.path.join(OUT, "charts"), exist_ok=True)

# ---------------------------------------------------------------- pre-registered predictions (written BEFORE the first run)
PREDICTIONS = {
    "C1": "Initial rules (v1) credit >=85% of paraphrased points (baseline v0 <=5%) but <=20% of unfamiliar-term points; "
          "v1 falsely credits >=90% of negated points.",
    "C2": "Revised rules (v2): negation guard cuts false credit on negated points to <=20%, and HIGH moderation priority "
          "captures >=90% of scripts whose suggestion is >=2 marks away from the expert mark while flagging <=60% of scripts.",
    "C3": "Plain audit table detects 0 of 4 tamper types; hash chain with external anchor detects 4 of 4; chain without "
          "anchor misses tail truncation; no log scheme can detect a wrong-but-legitimate mark.",
    "C4": "Authorization matrix: 77 of 77 role-action checks match the written specification.",
    "C5": "During a verification-service outage all 20 local marks stay published and all 20 messages are eventually delivered exactly once per idempotency key.",
}

QS = D.QUESTIONS


def qwk(a, b, k=D.MAX_MARK + 1):
    a, b = np.array(a), np.array(b)
    O = np.zeros((k, k))
    for x, y in zip(a, b):
        O[x, y] += 1
    W = np.array([[(i - j) ** 2 for j in range(k)] for i in range(k)], float) / (k - 1) ** 2
    E = np.outer(O.sum(1), O.sum(0)) / O.sum()
    return float(1 - (W * O).sum() / (W * E).sum())


def pass_(m):
    return m >= D.PASS_MARK


def main():
    res = {"predictions": PREDICTIONS}
    data = D.generate()
    res["dataset"] = {"n": len(data), "seed": D.SEED, "per_question": D.N_PER_QUESTION,
                      "variant_probabilities": D.P_VARIANT, "run_on_share_target": D.P_RUN_ON,
                      "run_on_share_actual": sum(r["run_on"] for r in data) / len(data),
                      "variant_counts": {}, "expert_mark_distribution": {}}
    vc = {}
    for r in data:
        for v in r["variants"].values():
            vc[v] = vc.get(v, 0) + 1
    res["dataset"]["variant_counts"] = vc
    res["dataset"]["expert_mark_distribution"] = {m: sum(1 for r in data if r["expert_mark"] == m) for m in range(6)}
    with open(os.path.join(OUT, "synthetic_dataset.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["id", "category", "answer_text", "variants", "expert_mark", "simulated_historical_mark", "run_on"])
        for r in data:
            w.writerow([r["id"], r["category"], r["text"], ";".join(f"{k}={v}" for k, v in r["variants"].items()),
                        r["expert_mark"], r["hist_mark"], r["run_on"]])

    engines = {"v0": score_v0, "v1": score_v1, "v2": score_v2, "v3": score_v3}
    outs = {k: [f(r["text"], QS[r["qid"]]) for r in data] for k, f in engines.items()}

    # ---------------- script-level metrics
    sl = {}
    for k, o in outs.items():
        d = np.array([x["mark"] - r["expert_mark"] for x, r in zip(o, data)])
        sl[k] = {"exact": float((d == 0).mean()), "within1": float((np.abs(d) <= 1).mean()), "mae": float(np.abs(d).mean()),
                 "bias": float(d.mean()),
                 "passfail_agree": float(np.mean([pass_(x["mark"]) == pass_(r["expert_mark"]) for x, r in zip(o, data)])),
                 "silent_ge2": float((np.abs(d) >= 2).mean())}
    res["script_level"] = sl

    # ---------------- point-level credit rates by variant
    pl = {}
    for k, o in outs.items():
        c = {}
        for x, r in zip(o, data):
            for pid, v in r["variants"].items():
                a = c.setdefault(v, [0, 0]); a[0] += pid in x["credited"]; a[1] += 1
        pl[k] = {v: {"credited": a, "total": b, "rate": a / b} for v, (a, b) in c.items()}
    res["point_level"] = pl

    # ---------------- script subsets
    subsets = {
        "all scripts": lambda r: True,
        "contains paraphrase": lambda r: "paraphrase" in r["variants"].values(),
        "contains unfamiliar term": lambda r: "unfamiliar" in r["variants"].values(),
        "contains negated statement": lambda r: "negated" in r["variants"].values(),
        "run-on style answer": lambda r: r["run_on"],
        "clean (exact/absent only)": lambda r: set(r["variants"].values()) <= {"exact", "absent"},
    }
    ss = {}
    for name, cond in subsets.items():
        idx = [i for i, r in enumerate(data) if cond(r)]
        ss[name] = {"n": len(idx)}
        for k, o in outs.items():
            ss[name][k] = {"exact": float(np.mean([o[i]["mark"] == data[i]["expert_mark"] for i in idx])),
                           "mae": float(np.mean([abs(o[i]["mark"] - data[i]["expert_mark"]) for i in idx]))}
    res["subsets"] = ss

    # ---------------- stakes-discrepancy matrix (v1 vs v2)
    def classify(sug, exp):
        d = sug - exp
        if d == 0: return "exact"
        if d < 0: return "under-marked, pass/fail flips" if (pass_(exp) and not pass_(sug)) else "under-marked, same outcome"
        return "over-marked, pass/fail flips" if (not pass_(exp) and pass_(sug)) else "over-marked, same outcome"
    classes = ["exact", "under-marked, same outcome", "under-marked, pass/fail flips",
               "over-marked, same outcome", "over-marked, pass/fail flips"]
    sdm = {}
    for k in ("v1", "v2", "v3"):
        m = {c: {"n": 0, "high": 0, "any_flag": 0} for c in classes}
        for x, r in zip(outs[k], data):
            c = classify(x["mark"], r["expert_mark"])
            m[c]["n"] += 1
            if k in ("v2", "v3"):
                m[c]["high"] += x["priority"] == "HIGH"
                m[c]["any_flag"] += x["priority"] in ("HIGH", "MEDIUM")
        sdm[k] = m
    res["stakes_matrix"] = sdm

    # ---------------- moderation-priority evaluation (v2 and v3)
    res["moderation_by_engine"] = {}
    for _k in ("v2", "v3"):
        _o = outs[_k]
        _d = [abs(x["mark"] - r["expert_mark"]) for x, r in zip(_o, data)]
        _ge2 = [i for i, d in enumerate(_d) if d >= 2]; _ge1 = [i for i, d in enumerate(_d) if d >= 1]
        _fl = [i for i, (x, r) in enumerate(zip(_o, data)) if pass_(x["mark"]) != pass_(r["expert_mark"])]
        _hi = [x["priority"] == "HIGH" for x in _o]; _an = [x["priority"] in ("HIGH", "MEDIUM") for x in _o]
        _r = lambda idx, flag: (sum(flag[i] for i in idx) / len(idx)) if idx else None
        res["moderation_by_engine"][_k] = {"n_ge2": len(_ge2), "n_ge1": len(_ge1), "n_flip": len(_fl),
            "recall_high_ge2": _r(_ge2, _hi), "recall_high_ge1": _r(_ge1, _hi), "recall_high_flip": _r(_fl, _hi),
            "recall_any_ge2": _r(_ge2, _an), "recall_any_ge1": _r(_ge1, _an), "recall_any_flip": _r(_fl, _an),
            "share_high": sum(_hi) / len(_hi), "share_high_or_medium": sum(_an) / len(_an),
            "negation_flag_without_negated_content": sum(1 for x, r in zip(_o, data) if "NEGATION" in x["flags"] and "negated" not in r["variants"].values()),
            "flag_counts": {f: sum(f in x["flags"] for x in _o) for f in ("NEGATION", "UNMATCHED_CONTENT", "BOUNDARY")}}
    o2 = outs["v3"]
    diff = [abs(x["mark"] - r["expert_mark"]) for x, r in zip(o2, data)]
    ge2 = [i for i, d in enumerate(diff) if d >= 2]
    ge1 = [i for i, d in enumerate(diff) if d >= 1]
    flip = [i for i, (x, r) in enumerate(zip(o2, data)) if pass_(x["mark"]) != pass_(r["expert_mark"])]
    high = [x["priority"] == "HIGH" for x in o2]
    anyf = [x["priority"] in ("HIGH", "MEDIUM") for x in o2]
    rec = lambda idx, flag: (sum(flag[i] for i in idx) / len(idx)) if idx else None
    res["moderation"] = {"n_ge2": len(ge2), "n_ge1": len(ge1), "n_flip": len(flip),
                         "recall_high_ge2": rec(ge2, high), "recall_high_ge1": rec(ge1, high),
                         "recall_high_flip": rec(flip, high), "recall_any_ge2": rec(ge2, anyf),
                         "recall_any_ge1": rec(ge1, anyf), "recall_any_flip": rec(flip, anyf),
                         "share_high": sum(high) / len(high), "share_high_or_medium": sum(anyf) / len(anyf),
                         "flag_counts": {f: sum(f in x["flags"] for x in o2) for f in ("NEGATION", "UNMATCHED_CONTENT", "BOUNDARY")},
                         "priority_counts": {p: sum(x["priority"] == p for x in o2) for p in ("HIGH", "MEDIUM", "LOW")}}
    # false-negation rate: scripts flagged NEGATION that contain no negated variant
    fn = sum(1 for x, r in zip(o2, data) if "NEGATION" in x["flags"] and "negated" not in r["variants"].values())
    res["moderation"]["negation_flag_without_negated_content"] = fn
    # threshold sweep for the unmatched-content rule
    sweep = []
    for th in (1, 2, 3, 4):
        oo = [score_v3(r["text"], QS[r["qid"]], unmatched_threshold=th) for r in data]
        hi = [x["priority"] == "HIGH" for x in oo]
        sweep.append({"threshold": th, "share_high": sum(hi) / len(hi), "recall_ge2": rec(ge2, hi), "recall_ge1": rec(ge1, hi)})
    res["threshold_sweep"] = sweep

    # ---------------- design revision v1 -> v2 summary
    res["revision"] = {"v1_negated_false_credit": pl["v1"]["negated"]["rate"], "v3_negated_false_credit": pl["v3"]["negated"]["rate"],
                       "v1_over_marked_flip": sdm["v1"]["over-marked, pass/fail flips"]["n"],
                       "v3_over_marked_flip": sdm["v3"]["over-marked, pass/fail flips"]["n"]}

    # ---------------- label inconsistency (Task 6)
    cat = {}
    for c in sorted({r["category"] for r in data}):
        rows = [(i, r) for i, r in enumerate(data) if r["category"] == c]
        e = [r["expert_mark"] for _, r in rows]; h = [r["hist_mark"] for _, r in rows]
        eng = [o2[i]["mark"] for i, _ in rows]
        cat[c] = {"n": len(rows),
                  "hist_vs_expert_exact": float(np.mean([a == b for a, b in zip(e, h)])),
                  "hist_vs_expert_within1": float(np.mean([abs(a - b) <= 1 for a, b in zip(e, h)])),
                  "hist_vs_expert_ge2": float(np.mean([abs(a - b) >= 2 for a, b in zip(e, h)])),
                  "hist_vs_expert_qwk": qwk(e, h),
                  "engine_vs_expert_exact": float(np.mean([a == b for a, b in zip(e, eng)])),
                  "engine_vs_hist_exact": float(np.mean([a == b for a, b in zip(h, eng)])),
                  "engine_vs_hist_within1": float(np.mean([abs(a - b) <= 1 for a, b in zip(h, eng)])),
                  "engine_vs_expert_within1": float(np.mean([abs(a - b) <= 1 for a, b in zip(e, eng)]))}
    res["categories"] = cat
    # noise-ceiling simulation: even a PERFECT scorer cannot beat the reference it is judged against
    rng = np.random.default_rng(11)
    exp_marks = np.array([r["expert_mark"] for r in data])
    ceil = []
    for sd in (0.2, 0.35, 0.5, 0.8, 1.0, 1.25, 1.5):
        ref = np.clip(np.rint(exp_marks + rng.normal(0, sd, len(exp_marks))), 0, D.MAX_MARK)
        ceil.append({"sd": sd, "exact_ceiling": float(np.mean(ref == exp_marks)), "within1_ceiling": float(np.mean(np.abs(ref - exp_marks) <= 1))})
    res["noise_ceiling"] = ceil
    res["policy_suppress_inconsistent"] = {"category": "Software Engineering",
                                           "scripts_routed_to_manual": cat["Software Engineering"]["n"],
                                           "share_of_all_scripts": cat["Software Engineering"]["n"] / len(data)}

    # ---------------- display policy: suggestions are WITHHELD when priority is HIGH
    dp = {}
    for label, cats in (("all categories", None), ("Day-4: Software Engineering suppressed", {"Operating Systems", "Database Systems"})):
        shown = [(x, r) for x, r in zip(outs["v3"], data) if x["priority"] != "HIGH" and (cats is None or r["category"] in cats)]
        d_ = [x["mark"] - r["expert_mark"] for x, r in shown]
        dp[label] = {"shown": len(shown), "share_shown": len(shown) / len(data),
                     "exact": float(np.mean([v == 0 for v in d_])), "within1": float(np.mean([abs(v) <= 1 for v in d_])),
                     "ge2": int(sum(abs(v) >= 2 for v in d_)),
                     "passfail_flips": int(sum(pass_(x["mark"]) != pass_(r["expert_mark"]) for x, r in shown)),
                     "mae": float(np.mean([abs(v) for v in d_]))}
    res["display_policy"] = dp
    res["high_by_category"] = {c: float(np.mean([x["priority"] == "HIGH" for x, r in zip(outs["v3"], data) if r["category"] == c])) for c in sorted({r["category"] for r in data})}

    # ---------------- validation, tamper matrix
    vres, tm, bypass = run_validation()
    res["validation"] = vres
    res["tamper_matrix"] = tm
    res["tamper_bypass"] = bypass

    # ---------------- measured performance and size
    t0 = time.perf_counter()
    reps = 20
    for _ in range(reps):
        for r in data:
            score_v2(r["text"], QS[r["qid"]])
    ms_per_answer = (time.perf_counter() - t0) / (reps * len(data)) * 1000
    s = fresh()
    n = 6000
    t0 = time.perf_counter()
    for i in range(n):
        s.audit("ex1", "SUBMIT_MARK", f"R{i}", {"mark": 3, "suggestion": 3, "override_reason": None})
    append_ms = (time.perf_counter() - t0) / n * 1000
    t0 = time.perf_counter(); ok, _ = s.verify_chain(); vt = time.perf_counter() - t0
    rows = s.db.execute("SELECT * FROM audit_chain").fetchall()
    pay = s.db.execute("SELECT * FROM audit_payload").fetchall()
    size = (sum(len(str(v)) for r in rows for v in tuple(r)) + sum(len(str(v)) for r in pay for v in tuple(r))) / len(rows)
    count = s.db.execute("SELECT COUNT(*) c FROM audit_chain").fetchone()["c"]
    meas = {"rule_ms_per_answer": ms_per_answer, "audit_append_ms_per_entry": append_ms,
            "verify_seconds_per_entry": vt / count, "verify_seconds_total": vt, "verify_entries": count,
            "bytes_per_audit_entry": size}
    res["measured"] = meas

    # ---------------- selection model
    res["selection"] = {
        "criteria": SEL.CRITERIA, "alts": SEL.ALTS, "w0": SEL.W0, "s0": SEL.S0, "w1": SEL.W1, "s1": SEL.S1,
        "totals0": SEL.totals(SEL.W0, SEL.S0), "totals1": SEL.totals(SEL.W1, SEL.S1),
        "contrib0": SEL.contributions(SEL.W0, SEL.S0), "contrib1": SEL.contributions(SEL.W1, SEL.S1),
        "sweep_usefulness": SEL.sweep_weight(0), "sweep_cost": SEL.sweep_weight(4),
        "crossover_usefulness": SEL.crossover(SEL.sweep_weight(0, grid=range(0, 96))),
        "crossover_cost": SEL.crossover(SEL.sweep_weight(4, grid=range(0, 96))),
        "ml_sweep": SEL.ml_readiness_sweep(), "mc": SEL.monte_carlo(), "mc_weights_only": SEL.monte_carlo(weights_only=True),
        "revised_mc": None,
    }
    # revised-model Monte Carlo (weights only)
    rng = np.random.default_rng(9); keys = list(SEL.S1); base = np.array([SEL.S1[k] for k in keys], float); wins = {k: 0 for k in keys}
    for _ in range(10000):
        w = rng.dirichlet(np.ones(7)); wins[keys[int(np.argmax(base @ w))]] += 1
    res["selection"]["revised_mc"] = {k: v / 10000 for k, v in wins.items()}

    # ---------------- cost model
    res["cost"] = {"assumptions": COST.ASSUMP, "alts": COST.model(), "volumes": COST.volumes(meas)}

    # ---------------- final checks against predictions
    pb = lambda k, v: pl[k][v]["rate"]
    res["prediction_check"] = {
        "C1": bool(pb("v1", "paraphrase") >= 0.85 and pb("v0", "paraphrase") <= 0.05 and pb("v1", "unfamiliar") <= 0.20 and pb("v1", "negated") >= 0.90),
        "C2_negation_v2": bool(pb("v2", "negated") <= 0.20),
        "C2_recall_v2": bool(res["moderation_by_engine"]["v2"]["recall_high_ge2"] >= 0.90),
        "C2_share_v2": bool(res["moderation_by_engine"]["v2"]["share_high"] <= 0.60),
        "C2_negation_v3": bool(pb("v3", "negated") <= 0.20),
        "C2_recall_v3": bool(res["moderation_by_engine"]["v3"]["recall_high_ge2"] >= 0.90),
        "C2_share_v3": bool(res["moderation_by_engine"]["v3"]["share_high"] <= 0.60),
        "C3": bool(next(v for v in vres if v["id"] == "V9")["passed"] and next(v for v in vres if v["id"] == "V10")["passed"]),
        "C4": bool(next(v for v in vres if v["id"] == "V4")["passed"]),
        "C5": bool(next(v for v in vres if v["id"] == "V13")["passed"]),
    }
    with open(os.path.join(OUT, "results.json"), "w") as f:
        json.dump(res, f, indent=1, default=lambda o: o if not isinstance(o, (np.floating, np.integer)) else o.item())

    # ---------------- console report
    print("=" * 78); print("EXAMINATION PLATFORM - RESPONSIBLE TECHNOLOGY DEMONSTRATOR"); print("=" * 78)
    print(f"Synthetic answers: {len(data)} (seed {D.SEED}); variants: {vc}")
    print("\n[1] Script-level agreement with expert mark (all scripts)")
    print(f"{'engine':<8}{'exact':>8}{'within +/-1':>13}{'MAE':>8}{'bias':>8}{'pass/fail':>11}{'|diff|>=2':>11}")
    for k in ("v0", "v1", "v2", "v3"):
        m = sl[k]; print(f"{k:<8}{m['exact']*100:>7.1f}%{m['within1']*100:>12.1f}%{m['mae']:>8.2f}{m['bias']:>8.2f}{m['passfail_agree']*100:>10.1f}%{m['silent_ge2']*100:>10.1f}%")
    print("\n[2] Point-level credit rate by answer type (share of rubric points credited)")
    print(f"{'type':<12}{'expert':>8}{'v0':>8}{'v1':>8}{'v2':>8}{'v3':>8}")
    for v in ("exact", "paraphrase", "unfamiliar", "negated", "absent"):
        print(f"{v:<12}{'credit' if v in D.CREDITED else 'none':>8}" + "".join(f"{pl[k][v]['rate']*100:>7.1f}%" for k in ("v0", "v1", "v2", "v3")))
    print("\n[3] Stakes-discrepancy matrix")
    for k in ("v1", "v2", "v3"):
        print(f"  {k}:")
        for c in classes:
            m = sdm[k][c]; extra = f"  HIGH-flagged {m['high']}, any flag {m['any_flag']}" if k != "v1" else "  (no flags in v1: silent)"
            print(f"    {c:<34}{m['n']:>4}{extra}")
    print("\n[4] Moderation priority")
    for k, mo in res["moderation_by_engine"].items():
        print(f"  {k}: HIGH share {mo['share_high']*100:.1f}%, HIGH+MEDIUM {mo['share_high_or_medium']*100:.1f}%; recall of |diff|>=2 {mo['recall_high_ge2']*100:.1f}% (n={mo['n_ge2']}); "
              f"recall of pass/fail flips {mo['recall_high_flip']*100:.1f}% (n={mo['n_flip']}); NEGATION flags on scripts with no negated content: {mo['negation_flag_without_negated_content']}")
    print("\n[5] Tamper matrix"); 
    for t, row in tm.items():
        print(f"  {t:<34}" + " | ".join(f"{sc}: {v}" for sc, v in row.items()))
    print("\n[6] Validation scenarios")
    for v in vres:
        print(f"  {'PASS' if v['passed'] else 'FAIL'} {v['id']:<4}{v['title']}")
    print(f"\n[7] Measured: rules {ms_per_answer:.3f} ms/answer; audit append {append_ms:.3f} ms/entry; chain verify {vt:.2f} s for {count} entries; {size:.0f} B/entry")
    print("\n[8] Predictions vs observation:", res["prediction_check"])
    print("\nResults written to results/results.json and results/synthetic_dataset.csv")


if __name__ == "__main__":
    main()
