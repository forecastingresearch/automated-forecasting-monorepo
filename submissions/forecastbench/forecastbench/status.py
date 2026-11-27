"""Read a private round's delivery history, verified receipts and member coverage."""
import argparse
from datetime import date, datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shlex
import sys
import time

import forecastbench as fb
from forecastbench import names, upload
from fri_forecaster import alert


def now():
    return datetime.now(timezone.utc)


def record(root, event, **fields):
    try:
        with (root / 'delivery.jsonl').open('ab+') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            if f.tell():
                f.seek(-1, os.SEEK_END)
                if f.read(1) != b'\n':
                    f.write(b'\n')
            f.write(json.dumps(dict(at=now().isoformat(), event=event, **fields)).encode() + b'\n')
            f.flush()
    except OSError as error:
        print(f'Could not record {event}: {error}', file=sys.stderr, flush=True)


def events(root):
    path = root / 'delivery.jsonl'
    if not path.exists():
        return []
    with path.open() as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        entries = []
        for line in f:
            try:
                if line.endswith('\n'):
                    entries.append(json.loads(line))
            except ValueError:
                print('Skipping damaged delivery journal entry', file=sys.stderr)
        return entries


def received(root, filename):
    # Recovery may have used a private staging copy of the same validated file.
    receipts = [root / 'upload-receipt.json', *root.glob(f'partial-*/{root.name}/upload-receipt.json')]
    for path in receipts:
        if not path.is_file():
            continue
        try:
            receipt = json.loads(path.read_text())
            prefix, account = upload.settings()
            bucket, folder = upload.destination(prefix, root.name)
        except ValueError as error:
            print(f'Cannot verify receipt: {error}', file=sys.stderr)
            continue
        if receipt.get('due') != root.name or receipt.get('account') != account:
            continue
        for obj in receipt.get('objects', []):
            if obj.get('name') != f'{folder}/{filename}':
                continue
            try:
                upload.confirmed(obj, bucket, obj['name'], (root / filename).read_bytes(), root.name)
            except (FileNotFoundError, KeyError, ValueError):
                continue
            return obj['timeCreated']


def retry_command(root, number):
    return f'python -m forecastbench.upload --root {shlex.quote(str(root))} --set-number {number}'


def page_once(root, number, title, message, *, filename=None):
    # The immediate failure and the independent timer may discover one incident together.
    marker = root / f'.delivery-page-{number}'
    with marker.open('a+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        if f.read() or (filename and received(root, filename)):
            return
        if alert.send('forecastbench', title, message, severity='page'):
            f.write(now().isoformat())
            f.flush()


def configured_sets(root):
    reg = names.load()
    return [dict(number=n, name=c, filename=f, members=names.member_specs(reg, c))
            for n, c, _, f in upload.registered_sets(reg, os.environ.get('FB_ORG'),
                                                     os.environ.get('FB_PUBLIC_ORG'), root.name)]


def round_state(root, history):
    for i in reversed(range(len(history))):
        if history[i]['event'] == 'round':
            return history[i]['sets'], history[i:]
    return configured_sets(root), history


def delivery(root, item, history):
    number = item['number']
    relevant = [e for e in history if e.get('number') == number]
    ready = next((e['at'] for e in reversed(relevant) if e['event'] == 'validated'), None)
    if not ready and not any(e['event'] == 'round' for e in history):
        build = root / 'logs' / f'build-{number}.log'
        if build.exists() and build.read_text().rstrip().endswith('ready to upload'):
            ready = datetime.fromtimestamp(build.stat().st_mtime, timezone.utc).isoformat()
    outcome = next((e['event'] for e in reversed(relevant)
                    if e['event'] in ('upload started', 'upload failed')), 'no recorded attempt')
    return received(root, item['filename']), ready, outcome


def check_pending(root):
    history = events(root)
    # No validation has happened yet, or this is an older round.
    if not any(e['event'] == 'validated' for e in history):
        return
    items, history = round_state(root, history)
    for item in items:
        confirmed, ready, outcome = delivery(root, item, history)
        if ready and not confirmed and (now() - datetime.fromisoformat(ready)).total_seconds() >= 600:
            number = item['number']
            page_once(root, number, 'validated submission unconfirmed',
                      f"{root.name} set {number} ({item['name']}) validated at {ready}. "
                      f"Last upload outcome: {outcome}. After sourcing round.env, retry {retry_command(root, number)}",
                      filename=item['filename'])


def worker_counts(root, history):
    owner = next((e['pid'] for e in history if e['event'] == 'round'), None)
    if owner is None:
        return {}, False
    try:
        args = (Path('/proc') / str(owner) / 'cmdline').read_bytes().split(b'\0')
    except (FileNotFoundError, ProcessLookupError):
        return {}, False
    if b'forecastbench.round_run' not in args or os.fsencode(root) not in args:
        return {}, False
    workers = {}
    for e in history:
        if e['event'] in ('member started', 'member finished'):
            workers[e['spec']] = e.get('workers', 0)
    return workers, True


def last_completion(path, rows):
    timestamps = []
    for row in rows.values():
        if not fb.complete(row):
            continue
        if row.get('completed_at'):
            timestamps.append(datetime.fromisoformat(row['completed_at']))
        elif row.get('attempt'):
            # Older result rows reference the saved final answer for the attempt.
            final = path.parent / row['attempt'] / 'final.json'
            if final.is_file():
                timestamps.append(datetime.fromtimestamp(final.stat().st_mtime, timezone.utc))
    if not timestamps:
        return 'unknown'
    last = max(timestamps)
    return f'{last.isoformat()} ({int((now() - last).total_seconds() // 60)} min ago)'


def member_progress(root, item, qset, workers, live):
    deficits = []
    results = {}
    started = False
    for spec in item['members']:
        path = Path(fb.member_dir_for_spec(root, spec)) / 'results.jsonl'
        rows = fb.read_results(path)
        started |= bool(rows or workers.get(spec))
        results[spec] = path, rows
        for kind, (done, total) in fb.coverage(qset, rows).items():
            required = (95 * total + 99) // 100
            if done < required:
                deficits.append((done / required, spec, kind, done, required))
    if started:
        state = 'in progress' if live else 'partial results'
    else:
        state = 'queued' if live or now().date().isoformat() == root.name else 'never started'
    if deficits:
        _, spec, kind, done, required = min(deficits)
        last = last_completion(*results[spec])
        state += (f'; {spec} {kind} {done}/{required} required; workers {workers.get(spec, 0)}'
                  f'; last successful result {last}')
    return state


def report(root, *, history_lines=False, require_uploaded=False):
    if not root.is_dir():
        return f'{root.name}: no saved round', False
    if not (root / 'question_set.json').exists():
        return f'{root.name}: waiting for question set', False
    qset = json.loads((root / 'question_set.json').read_text())
    if qset['forecast_due_date'] != root.name:
        raise ValueError('Question set does not match round date')
    all_events = events(root)
    items, history = round_state(root, all_events)
    workers, live = worker_counts(root, history)
    lines = [f'ForecastBench {root.name} (UTC)']
    if not any(e['event'] == 'round' for e in history):
        lines.append('No saved round roster; set names and members below use the configured registry.')
    landed = 0
    for item in items:
        n = item['number']
        confirmed, ready, outcome = delivery(root, item, history)
        line = f"Set {n} {item['name']} — "
        if confirmed:
            landed += 1
            line += f'upload confirmed {confirmed}'
        elif ready:
            age = int((now() - datetime.fromisoformat(ready)).total_seconds() // 60)
            line += f'validated {ready}, unconfirmed for {age} min, {outcome}'
        elif not require_uploaded:
            line += member_progress(root, item, qset, workers, live)
            if any(e.get('number') == n and e['event'] == 'validation failed' for e in history):
                line += '; previous validation failed'
        else:
            line += 'unconfirmed'
        lines.append(line)
        if history_lines:
            if ready and not any(e['event'] == 'round' for e in history):
                lines.append(f'  {ready} validated (archived build log)')
            for e in all_events:
                if e.get('number') == n or e.get('spec') in item['members']:
                    details = ' '.join(str(e[k]) for k in ('spec', 'workers') if k in e)
                    attempt = f"attempt {e['attempt']} " if 'attempt' in e else ''
                    lines.append(f"  {e['at']} {attempt}{e['event']} {details}".rstrip())
    lines.append(f'{landed}/{len(items)} uploads confirmed')
    return '\n'.join(lines), bool(items) and landed == len(items)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--history', action='store_true')
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--require-uploaded', action='store_true')
    args = parser.parse_args()
    if args.watch:
        while now().date() == date.fromisoformat(args.root.name):
            try:
                check_pending(args.root)
            except (OSError, ValueError, KeyError) as error:
                print(f'Delivery watchdog: {error}', file=sys.stderr, flush=True)
            time.sleep(30)
        return
    summary, complete = report(args.root, history_lines=args.history, require_uploaded=args.require_uploaded)
    print(summary)
    if args.require_uploaded and not complete:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
