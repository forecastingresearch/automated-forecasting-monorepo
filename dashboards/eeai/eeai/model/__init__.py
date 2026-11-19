"""EEAI's economy model (v0): accounting identities over 22 industries and 22
occupation groups, whose components the panel forecasts as quantiles.

    data/model/components.json   the definition (hand-written; spec.py expands it)
    data/model/baselines.csv     the 2025 record offered in the prompt (make_baselines.py)
    python3 -m eeai model prompt          the prompt; calls nothing
    python3 -m eeai model run             PAID: one call per panel member -> results/model/runs/
    python3 -m eeai model simulate FILE   the run file -> results/model/sims/ (needs numpy)
    python3 -m eeai build                 both pages: index.html (the survey) and model.html

The design is FRI's note "Initial economy model for the dashboard" (13 and 18
November 2026). The README's "Economy model" section says what is asked and
what is still open.
"""
