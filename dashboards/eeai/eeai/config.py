"""Paths. Everything EEAI owns is in this directory: the code, data/ (the
questions and the record), web/ (the page's source), tests/, and two folders
that are not tracked -- results/ (the run files) and site/ (the built page).
EEAI_RESULTS moves the results (a production box keeps them outside the
release); EEAI_ECI_DIR names another directory of Epoch snapshots and automatic
model rows. Outside this directory EEAI uses only the harness
(packages/forecaster), the dashboard kit (packages/dashboard) and AIRO's Epoch snapshots (dashboards/airo/data)."""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
try:
    import dashboard  # noqa: F401
    import fri_forecaster  # noqa: F401
except ImportError:
    # One repository: the harness and the dashboard kit are under packages/, so
    # a bare checkout works without installing them (pip install -e packages/...).
    sys.path[:0] = [str(REPO_ROOT / "packages" / "forecaster"), str(REPO_ROOT / "packages" / "dashboard")]

DATA = HERE / "data"
QUESTIONS = DATA / "questions.json"
HISTORY = DATA / "history.csv"
# The Epoch snapshots (and a box's automatic model rows) the panel is chosen
# from: AIRO's data/ (dashboards/airo), which its scheduled jobs keep current.
ECI_DIR = Path(os.environ.get("EEAI_ECI_DIR") or REPO_ROOT / "dashboards" / "airo" / "data")
RESULTS = Path(os.environ.get("EEAI_RESULTS") or HERE / "results")
RUNS = RESULTS / "runs"
PAGE_DIR = HERE / "web"
# The built site: index.html, the download, and the files the page links to.
SITE = HERE / "site"

# What the models may not search or read: FRI's own pages (the human panel's
# answers to this survey are published there) and FRI's Substack. Regexes for
# fri_forecaster.tools' URL guard, matched anywhere in a URL, so an archived
# copy is blocked too. A snippet on someone else's page can still quote them.
BLOCKED_URLS = (r"forecastingresearch\.org", r"forecastingresearch\.substack\.com")

EXPERIMENT = "eeai"
CONDITION = "baseline"

# The economy model (eeai/model): its own definition and record, run files,
# simulation summaries and page source, beside the survey's.
MODEL_DATA = DATA / "model"
MODEL_COMPONENTS = MODEL_DATA / "components.json"
MODEL_BASELINES = MODEL_DATA / "baselines.csv"
MODEL_SOURCE = MODEL_DATA / "source"
MODEL_RESULTS = RESULTS / "model"
MODEL_RUNS = MODEL_RESULTS / "runs"
MODEL_SIMS = MODEL_RESULTS / "sims"
MODEL_PAGE_DIR = HERE / "web-model"
MODEL_EXPERIMENT = "eeai-model"
# One call per model delivers all ~19,000 quantile sets, far more than any
# other call (pi compacts the context as it fills; submit_cells keeps what was
# delivered on disk), so it gets more turns and time than the Baseline
# condition's 100 turns and 3 hours. Nothing else about the condition changes.
MODEL_MAX_TURNS = 500
MODEL_TIMEOUT = 12 * 3600
