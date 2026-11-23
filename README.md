# Responsible Technology Adoption - Examination and Credential Platform (demonstrator)

Demonstrator for CSA1023 Software Engineering, Assignment 5 (CO5). Synthetic data only; no real student data.

## Run
    python -m venv .venv
    .venv\Scripts\activate        # Windows (source .venv/bin/activate on Linux/macOS)
    pip install -r requirements.txt
    python run_all.py             # all experiments -> results/results.json, results/synthetic_dataset.csv
    python make_charts.py         # charts -> results/charts/
    python -m unittest -v         # V1-V14 validation scenarios + unit tests

## What it shows
- Deterministic rubric rules (v0 baseline, v1 initial, v2 negation guard, v3 clause-aware) - NOT machine learning
- Role-controlled marks store: workflow, separation of duties, versioned records
- Plain vs append-only vs hash-chained audit trail (tamper tests); redaction; outbox retry; signed credentials
- Decision matrix, sensitivity analysis and cost model

Accuracy numbers are deterministic (fixed seeds). Timings are measured and vary by machine.
Diagram sources are in diagrams/*.dot (render with Graphviz: dot -Tpng file.dot -o file.png).
