"""python3 -m eeai {prompt,run,build}"""
import argparse
import sys
from datetime import date, datetime, timezone

from . import config, instrument, survey as S


def cmd_prompt(args):
    from fri_forecaster import baseline, panel
    from .baselines import current
    survey = S.load()
    today = date.fromisoformat(args.today) if args.today else datetime.now(timezone.utc).date()
    prompt, qids = instrument.build_prompt(survey, S.history(current(today)), today)
    members, _ = panel.panel(snapshot_dir=config.ECI_DIR)
    print(f"##### {config.EXPERIMENT} / {config.CONDITION} [{survey['instrument']}]: {len(qids)} questions, "
          f"{S.n_values(survey, today)} values + Part 1, {len(prompt)} chars #####")
    print(prompt)
    print("##### TOOLS: " + ", ".join(t["name"] for t in baseline.research_tools())
          + ", submit_cells, submit_forecast; no system prompt; turn limit "
          + f"{baseline.MAX_TURNS} #####")
    print("##### PANEL: " + ", ".join(f"{m['label']} ({m['pi_model']}, thinking {m['reasoning']})" for m in members)
          + " #####")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m eeai", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prompt", help="print the prompt, the tools and the panel; calls nothing")
    p.add_argument("--today")
    r = sub.add_parser("run", help="ask the panel (PAID unless --synthetic)")
    r.add_argument("--smoke", action="store_true", help="the panel's top model only")
    r.add_argument("--models", help="panel members by key or label, comma-separated")
    r.add_argument("--resume", metavar="RUN_ID", help="add the models an earlier run file lacks, under its run id and date")
    r.add_argument("--workers", type=int, default=4)
    r.add_argument("--retries", type=int, default=1, help="extra calls for a model that delivers too little")
    r.add_argument("--out", help="directory for the run file (default eeai/results/runs)")
    r.add_argument("--today", help="the run date, YYYY-MM-DD (default today, UTC)")
    r.add_argument("--synthetic", action="store_true", help="no calls: made-up answers (needs --out)")
    r.add_argument("--allow-ungrounded", action="store_true", help="allow a run without the selected search API key")
    b = sub.add_parser("build", help="the run files -> the page")
    b.add_argument("--publication", action="store_true", help="require complete real panel runs before export")
    b.add_argument("--runs", help="directory of run files (default eeai/results/runs)")
    b.add_argument("--out", help="write only the page, to this file (and the download beside it)")
    b.add_argument("--json", help="also write the page's data here")
    b.add_argument("--site", help="the site folder to write (default eeai/site): index.html, the download, web/")
    sub.add_parser("resolve", help="record due source revisions and reviewed outcomes under EEAI_RESULTS")
    sub.add_parser("refresh", help="refresh economic baselines and check due outcomes")
    replay = sub.add_parser("replay", help="inspect a historical FRED target without storing it")
    replay.add_argument("question")
    replay.add_argument("year", type=int)
    replay.add_argument("--as-of", required=True, type=date.fromisoformat)
    replay.add_argument("--history", action="store_true", help="show every distinct source vintage value")
    decision = sub.add_parser("decide", help="record an adjudication or a correction")
    decision.add_argument("file")
    human = sub.add_parser("summarize-human", aliases=["import-human"], help="compute the public summary from private weighted survey CSVs")
    human.add_argument("directory")
    human.add_argument("--extracted-on", required=True)
    human.add_argument("--out", help="write the public CSV here (default: the tracked dashboard summary)")
    args = ap.parse_args(argv)
    if args.cmd in ("summarize-human", "import-human"):
        from .human import SUMMARY, summarize
        print(summarize(args.directory, args.extracted_on, args.out or SUMMARY))
        return 0
    if args.cmd == "replay":
        import json
        from . import resolve
        q = next((q for q in S.load()["questions"] if q["id"] == args.question), None)
        if not q or q["resolver"] != "fred":
            ap.error("replay requires an automated economic question")
        periods = resolve.dates(q["resolution"]["method"], args.year)
        day = args.as_of.isoformat()
        got = [] if args.history else None
        if day >= periods[0]:
            got = resolve.read_target(q, periods, day, history=args.history)
        print(json.dumps(got if got is not None else {"status": "awaiting_evidence"}, indent=2))
        return 0
    if args.cmd == "decide":
        from .decisions import apply
        apply(args.file)
        return 0
    if args.cmd == "refresh":
        import json
        from . import baselines, resolve
        day = datetime.now(timezone.utc).date()
        resolved = resolve.refresh(day)
        # Forecasts read the latest completed dated baseline. Advance it only
        # once the resolution pass has finished.
        print(json.dumps(baselines.refresh(day), indent=2))
        print(f"{resolved} resolved target(s)")
        return 0
    if args.cmd == "resolve":
        from .resolve import refresh
        print(f"{refresh()} resolved target(s)")
        return 0
    if args.cmd == "prompt":
        return cmd_prompt(args)
    if args.cmd == "run":
        from . import run
        return run.main(args)
    from . import build
    return build.main(args)


if __name__ == "__main__":
    sys.exit(main())
