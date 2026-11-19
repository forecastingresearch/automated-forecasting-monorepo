"""Ask the panel the economy model: one Baseline call per panel member (instrument.calls), one row per component.

    python3 -m eeai model run                    # the panel; PAID: model and search calls
    python3 -m eeai model run --smoke            # the panel's top model only
    python3 -m eeai model run --split scenario   # a few calls per model instead of one
    python3 -m eeai model run --resume RUN_ID    # the models that run does not have yet
    python3 -m eeai model run --synthetic --out DIR   # no calls: made-up answers

Rows go to eeai/results/model/runs/<stamp>.jsonl (config.MODEL_RUNS) as each
model finishes. A model's first row carries `call`: the scenario
probabilities, the rationales, the prompts, the research evidence, the cost.

A call that delivers less than COMPLETE of what it asked is asked again for
the missing components only, so a call that stops partway does not pay twice.
The call gets the model's own turn and time limits (config.MODEL_MAX_TURNS,
MODEL_TIMEOUT); everything else is the Baseline condition, as in the survey.
"""
import concurrent.futures as cf
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
from datetime import date, datetime, timezone

from .. import config
from ..run import select_members
from . import instrument as I
from . import spec as M

COMPLETE = 0.9


def _blocked(env):
    from fri_forecaster.tools import BLOCK_ENV
    blocked = [p for p in (os.environ.get(BLOCK_ENV) or "").replace(",", "\n").split("\n") if p.strip()]
    blocked += [p for p in config.BLOCKED_URLS if p not in blocked]
    return dict(env or {}, **{BLOCK_ENV: "\n".join(blocked)}), blocked


def ask(member, spec, record, today, run_id, *, split=None, panel=None, retries=1, harness_run=None, env=None,
        synthetic=False):
    """Every call for one model. -> rows, one per component, the first carrying `call`."""
    from fri_forecaster import baseline
    env, blocked = _blocked(env)
    base = os.environ.get("EEAI_PI_DIR") or os.path.join(tempfile.gettempdir(), "eeai-pi")
    every = M.by_id(spec)
    forecasts, problems, why = {}, {}, {}
    probabilities, prob_problems, answers, prompts, usage, evidence, attempts_by = None, [], [], [], [], [], {}
    for call in I.calls(spec, split):
        pairs = I.asked(spec, call)
        want = sum(len(p) for p in pairs.values())
        submit_cells, submit_forecast = I.tools(spec, call)
        only, attempts = None, 0
        while True:
            attempts += 1
            prompt, keys = I.build_prompt(spec, call, record, today, only=only)
            prompts.append({"call": call["id"], "attempt": attempts, "prompt": prompt,
                            "sha256": hashlib.sha256(prompt.encode()).hexdigest()})
            res = baseline.run(member["model"], prompt,
                               workdir=os.path.join(base, f"{member['key']}-{call['id']}-{time.time_ns()}"),
                               cell_schema=I.cell_schema(spec), key_fields=["question_id"], allowed_keys=keys,
                               submit_cells=submit_cells, submit_forecast=submit_forecast, env=env,
                               harness_run=harness_run, max_turns=config.MODEL_MAX_TURNS, timeout=config.MODEL_TIMEOUT)
            usage.append(res.get("usage") or {})
            evidence += [{k: e.get(k) for k in ("tool", "args", "result")} for e in res.get("evidence") or []]
            cells = res.get("cells") or {}
            for cid in keys:
                if cid.startswith("why."):
                    text = (cells.get(cid) or {}).get("rationale")
                    if isinstance(text, str) and text.strip():
                        why[cid] = text
                    continue
                if cid not in cells:
                    problems.setdefault(cid, ["not delivered"])
                    continue
                got, probs = I.clean_cell(spec, every[cid], cells[cid], pairs[cid])
                for y, by_s in got.items():
                    forecasts.setdefault(cid, {}).setdefault(y, {}).update(by_s)
                problems[cid] = probs
            answer = res.get("answer") or {}
            answers.append({"call": call["id"], "rationale": answer.get("rationale"), "key_sources": answer.get("key_sources"),
                            "delivery": res.get("delivery")})
            if call["probabilities"] and probabilities is None:
                probabilities, prob_problems = I.clean_probabilities(spec, answer)
            have = {cid: sum(1 for y, s in pairs[cid] if s in (forecasts.get(cid, {}).get(y) or {})) for cid in pairs}
            got_n = sum(have.values())
            missing = [cid for cid in pairs if have[cid] < len(pairs[cid])]
            missing_why = [g for g, _ in I.rationales(spec, call) if g not in why]
            done = got_n >= COMPLETE * want and (probabilities is not None or not call["probabilities"])
            if done or attempts > retries or not (missing or missing_why or probabilities is None):
                break
            print(f"  retry {member['label']:16} {call['id']} attempt {attempts}: {got_n}/{want} sets", flush=True)
            only = set(missing) | set(missing_why)
        attempts_by[call["id"]] = attempts
    values = sum(len(ps) for f in forecasts.values() for ps in f.values())
    if not values:
        raise RuntimeError(f"no forecasts after {sum(attempts_by.values())} attempt(s)")
    hits = sum(len((e.get("result") or {}).get("results") or []) for e in evidence if e["tool"] == "web_search")
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    call = {"scenario_probabilities": probabilities, "probability_problems": prob_problems, "rationales": why,
            "answers": answers, "evidence": evidence, "search_hits": hits, "grounded": hits > 0, "usage": usage,
            "cost_usd": round(sum(u.get("cost_usd") or 0 for u in usage), 6), "attempts": attempts_by,
            "values": values, "values_asked": M.n_sets(spec), "split": split, "prompts": prompts,
            "system_prompt": baseline.SYSTEM, "reasoning": member.get("reasoning"), "blocked_urls": blocked,
            "max_turns": config.MODEL_MAX_TURNS, "timeout": config.MODEL_TIMEOUT,
            "record": "placeholder" if any("PLACEHOLDER" in v["source"] for v in record.values()) else "data/model/baselines.csv"}
    rows = []
    for i, cid in enumerate(every):
        rows.append({"run_id": run_id, "run_date": today.isoformat(), "elicited_at": stamp,
                     "experiment": config.MODEL_EXPERIMENT, "condition": config.CONDITION, "instrument": spec["instrument"],
                     "model": member["model"], "key": member["key"], "label": member["label"],
                     "question_id": cid, "forecasts": forecasts.get(cid, {}), "problems": problems.get(cid, []),
                     "panel": panel, "call_id": f"{run_id}:{member['key']}",
                     **({"synthetic": True} if synthetic else {}), "call": call if i == 0 else None})
    return rows


def record_for(synthetic, spec):
    """The 2025 record: data/model/baselines.csv, or, for synthetic rows only, the placeholder economy."""
    record = I.load_baselines()
    if not record and synthetic:
        from . import synthetic as syn
        record = syn.placeholder_record(spec)
    return record


def main(args):
    spec = M.load()
    today = date.fromisoformat(args.today) if args.today else datetime.now(timezone.utc).date()
    record = record_for(args.synthetic, spec)
    if not record:
        sys.exit(f"{config.MODEL_BASELINES} is missing: the prompt would offer no 2025 data. "
                 "Build it first (python3 -m eeai model baselines).")
    members, provenance = select_members(args)
    harness_run = None
    if args.synthetic:
        if not args.out:
            sys.exit("--synthetic rows are made up: give them a directory with --out (never results/)")
        from . import synthetic
        harness_run = synthetic.harness_run(spec, record, today)
    else:
        from fri_forecaster import keys
        if "TAVILY_API_KEY" not in keys.load_keys() and not args.allow_ungrounded:
            sys.exit("TAVILY_API_KEY is not set: the models would answer from memory with no search. "
                     "Set it (fri_forecaster.keys says where) or pass --allow-ungrounded.")
    runs = args.out or config.MODEL_RUNS
    os.makedirs(runs, exist_ok=True)
    run_id = f"{today.isoformat()}T0000Z" if args.synthetic else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    path = os.path.join(runs, f"{run_id}.jsonl")
    if args.resume:
        run_id, path = args.resume, os.path.join(runs, f"{args.resume}.jsonl")
        if not os.path.exists(path):
            sys.exit(f"--resume {args.resume}: no {path}")
        with open(path, encoding="utf-8") as f:
            have = [json.loads(line) for line in f if line.strip()]
        today = date.fromisoformat(have[0]["run_date"])
        done = {r["key"] for r in have}
        members = [m for m in members if m["key"] not in done]
        if not members:
            sys.exit(f"--resume {args.resume}: every selected model has already answered")
    n_calls = len(I.calls(spec, args.split))
    print(f"{config.MODEL_EXPERIMENT} / {config.CONDITION} [{spec['instrument']}]: {M.n_sets(spec)} quantile sets, "
          f"{n_calls} call(s) per model, {len(members)} model(s): {', '.join(m['label'] for m in members)}"
          f"{' -- SYNTHETIC, no calls' if args.synthetic else ''}", flush=True)
    lock, failed, spent = threading.Lock(), [], 0.0

    def one(member):
        rows = ask(member, spec, record, today, run_id, split=args.split, panel=provenance, retries=args.retries,
                   harness_run=harness_run, synthetic=args.synthetic)
        with lock, open(path, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return rows

    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(one, m): m for m in members}
        for fut in cf.as_completed(futures):
            m = futures[fut]
            try:
                call = fut.result()[0]["call"]
            except Exception as exc:
                failed.append(m["label"])
                print(f"  FAILED {m['label']:16} {type(exc).__name__}: {str(exc)[:300]}", flush=True)
                continue
            spent += call["cost_usd"]
            print(f"  done   {m['label']:16} {call['values']}/{call['values_asked']} sets, "
                  f"{call['search_hits']} search hits, ${call['cost_usd']:.2f}", flush=True)
    print(f"{path}: {len(members) - len(failed)} of {len(members)} models, ${spent:.2f}"
          + (f"; FAILED: {', '.join(failed)}" if failed else ""), flush=True)
    return 1 if failed else 0
