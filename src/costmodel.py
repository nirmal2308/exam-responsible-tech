"""Planning-level cost and resource model. EVERYTHING here is an ESTIMATE built on explicit
assumptions (unit prices are placeholders to be replaced by procurement quotes)."""

ASSUMP = {
    "students": 5000, "papers_per_student_year": 10, "answers_per_paper": 5,
    "result_windows_per_year": 2, "working_days_per_window": 10,
    "vm_month_inr": 7000, "node_month_inr": 5000, "gpu_hour_inr": 150, "gpu_hours_year": 300,
    "ml_infer_vm_month_inr": 5000, "storage_gb_month_inr": 2.0, "backup_gb_month_inr": 1.2,
    "monitoring_year_inr": 6000, "misc_year_inr": 3000, "fte_year_inr": 900000,
    "label_cost_per_answer_inr": 40, "labelled_answers_year": 3000,
    "vm_kw": 0.12, "node_kw": 0.08, "gpu_kw": 0.25, "grid_kg_per_kwh": 0.71,
    "budget_compute_original_inr": 300000, "budget_compute_revised_inr": 150000,
}


def volumes(m=None):
    a = ASSUMP
    answers = a["students"] * a["papers_per_student_year"] * a["answers_per_paper"]
    scripts = a["students"] * a["papers_per_student_year"]
    events = answers * 6
    out = {"scripts_year": scripts, "answers_year": answers, "audit_events_year": events}
    if m:
        out["audit_gb_year"] = events * m["bytes_per_audit_entry"] / 1e9
        out["chain_verify_minutes_year_est"] = events * m["verify_seconds_per_entry"] / 60
    return out


def model():
    a = ASSUMP
    base_infra = a["vm_month_inr"] * 12 + a["vm_month_inr"] * 3 + 100 * a["storage_gb_month_inr"] * 12 \
        + 200 * a["backup_gb_month_inr"] * 12 + a["monitoring_year_inr"] + a["misc_year_inr"]
    gpu = a["gpu_hour_inr"] * a["gpu_hours_year"]
    infer = a["ml_infer_vm_month_inr"] * 12
    nodes = 3 * a["node_month_inr"] * 12
    fte = a["fte_year_inr"]
    label = a["label_cost_per_answer_inr"] * a["labelled_answers_year"]
    alts = {
        "A": {"infra": base_infra, "staff": 0.15 * fte, "capex": 600000},
        "B": {"infra": base_infra + gpu + infer, "staff": 0.15 * fte + 0.30 * fte + label, "capex": 1000000},
        "C": {"infra": base_infra + nodes, "staff": 0.15 * fte + 0.25 * fte + 0.05 * fte, "capex": 1100000},
        "D": {"infra": base_infra + gpu + infer + nodes,
              "staff": 0.15 * fte + 0.30 * fte + label + 0.30 * fte, "capex": 1500000},
        # Day-4 revised A: one VM, standby only 2 months, plus correction-workflow operations
        "A2": {"infra": a["vm_month_inr"] * 12 + a["vm_month_inr"] * 2 + 100 * a["storage_gb_month_inr"] * 12
               + 200 * a["backup_gb_month_inr"] * 12 + a["monitoring_year_inr"] + a["misc_year_inr"],
               "staff": 0.18 * fte, "capex": 650000},
    }
    kwh = {"A": a["vm_kw"] * 24 * 365 * 1.25,
           "B": a["vm_kw"] * 24 * 365 * 2.25 + a["gpu_kw"] * a["gpu_hours_year"],
           "C": a["vm_kw"] * 24 * 365 * 1.25 + 3 * a["node_kw"] * 24 * 365,
           "A2": a["vm_kw"] * 24 * 365 * 1.17}
    kwh["D"] = kwh["B"] + 3 * a["node_kw"] * 24 * 365
    for k, v in alts.items():
        v["opex"] = v["infra"] + v["staff"]
        v["tco5"] = v["capex"] + 5 * v["opex"]
        v["kwh"] = kwh[k]
        v["kg_co2e"] = kwh[k] * a["grid_kg_per_kwh"]
        v["fits_original_budget"] = v["infra"] <= a["budget_compute_original_inr"]
        v["fits_revised_budget"] = v["infra"] <= a["budget_compute_revised_inr"]
    return alts
