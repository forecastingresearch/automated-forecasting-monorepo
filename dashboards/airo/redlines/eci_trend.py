"""Reviewed metr_graph ECI projection; network work only at publication/check time.

Independent implementation of the pinned algorithm, restricted to Epoch's
released US models (AIRO's forecast target). Upstream source is never executed.
"""
import csv
import hashlib
import json
import math
import random
import re
import statistics
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import eci
from .config import REPO_ROOT

UPSTREAM = 'https://github.com/peterhurford/metr_graph'
COMMIT = 'b436a09c09c951b36df1f74ce4db0bed4900523e'
SOURCE_SHA256 = '75e655da2663e558aa3621f03ab619958b682181762e7e4e9a4ad16cad1e2685'
CACHE = REPO_ROOT / 'data/eci_trend_current.json'
STATUS = REPO_ROOT / 'data/eci_trend_status.json'
LEGACY = REPO_ROOT / 'data/eci_trend_2026-09-10.json'
MAX_AGE_DAYS = 7


def write_json(path, value):
    # Resolve existing state symlinks so candidate releases cannot detach them.
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    tmp.replace(path)


def download(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'AIRO ECI upstream monitor'})
    with urllib.request.urlopen(req, timeout=30) as response:
        data = response.read(5_000_001)
    if len(data) > 5_000_000:
        raise ValueError('Upstream response exceeds size limit')
    return data


def check_upstream():
    # Atom works without API credentials and follows the repository's rename.
    feed = ET.fromstring(download(UPSTREAM + '/commits/master.atom'))
    entry = feed.find('{http://www.w3.org/2005/Atom}entry')
    identity = entry.findtext('{http://www.w3.org/2005/Atom}id') if entry is not None else ''
    commit = (identity or '').rsplit('/', 1)[-1]
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Missing upstream commit identity')
    source = download(f'https://raw.githubusercontent.com/peterhurford/metr_graph/{commit}/visualize_projection.py')
    digest = hashlib.sha256(source).hexdigest()
    return {'commit': commit, 'sourceSha256': digest,
            'reviewRequired': digest != SOURCE_SHA256, 'approvedCommit': COMMIT}


def frontier(path):
    """Best variant per model, then best model per date, then running maximum."""
    best = {}
    with path.open(newline='') as f:
        for row in csv.DictReader(f):
            name = row.get('Model') or row.get('Model name') or row.get('Model version')
            score = row.get('eci') or row.get('ECI Score')
            day = row.get('date') or row.get('Release date')
            country = row.get('Country (of organization)') or row.get('Country')
            if not name or not score or not day or country != eci.US:
                continue
            point = {'date': date.fromisoformat(day), 'score': float(score),
                     'model': row.get('Display name') or name}
            if not math.isfinite(point['score']):
                raise ValueError('Non-finite ECI score')
            if name not in best or point['score'] > best[name]['score']:
                best[name] = point
    by_day = {}
    for point in best.values():
        day = point['date']
        if day >= date(2024, 2, 29) and (day not in by_day or point['score'] > by_day[day]['score']):
            by_day[day] = point
    result, high = [], -math.inf
    for day, point in sorted(by_day.items()):
        if point['score'] > high:
            result.append(point)
            high = point['score']
    if len(result) < 5:
        raise ValueError('Too few frontier points for a two-segment fit')
    return result


def line(points):
    xs = [p['date'].toordinal() for p in points]
    ys = [p['score'] for p in points]
    slope, intercept = statistics.linear_regression(xs, ys)
    error = sum((y - intercept - slope * x) ** 2 for x, y in zip(xs, ys))
    return slope, intercept, error


def project(path, snapshot_day, today, samples=10000):
    points = frontier(path)
    names = [p['model'] for p in points]
    split = next((names.index(n) for n in ('Mythos Preview (internal)', 'Claude Fable 5')
                  if n in names and 2 <= names.index(n) <= len(points) - 3), None)
    if split is None:
        split = min(range(2, len(points) - 2),
                    key=lambda i: line(points[:i + 1])[2] + line(points[i:])[2])
    slope, intercept, _ = line(points[split:])
    if slope <= 0:
        raise ValueError('Non-positive fitted ECI pace')
    ppy = round(slope * 365.25, 1)
    lo, hi = round(ppy / 2, 1), round(ppy * 2, 1)
    if lo <= 0:
        raise ValueError('Non-positive ECI pace interval')
    dpp_lo, dpp_hi = 365.25 / hi, 365.25 / lo
    center = min(max(1 / slope, dpp_lo), dpp_hi)
    anchor = points[-1]
    fitted = intercept + slope * anchor['date'].toordinal()
    rng = random.Random(1)
    rates = []
    for _ in range(samples):
        z = rng.gauss(0, 1)
        width = math.log(center / dpp_lo) if z < 0 else math.log(dpp_hi / center)
        rates.append(1 / math.exp(math.log(center) + z * width / 1.282))
    starts = [rng.gauss(fitted, 4 / (2 * 1.282)) for _ in range(samples)]
    daily = []
    end = date(max(2030, today.year + 4), 12, 31)
    for elapsed in range((end - anchor['date']).days + 1):
        values = sorted(start + elapsed * rate for start, rate in zip(starts, rates))
        row = {'date': (anchor['date'] + timedelta(days=elapsed)).isoformat()}
        for pct in (25, 50, 75):
            index = (samples - 1) * pct / 100
            left = int(index)
            row[f'p{pct}'] = round(values[left] + (index - left) * (values[left + 1] - values[left]), 2)
        daily.append(row)
    return {'source': {'label': 'Peter Wildeford (released US models)', 'app': UPSTREAM,
                      'retrieved': snapshot_day.isoformat(), 'commit': COMMIT,
                      'sourceSha256': SOURCE_SHA256, 'snapshotSha256': hashlib.sha256(path.read_bytes()).hexdigest()},
            'computed': today.isoformat(), 'method': 'Piecewise linear, two segments; released US frontier',
            'fit': {'n_frontier': len(points), 'breakpoint': points[split]['model'],
                    'pts_per_year': ppy, 'pts_per_year_ci80': [lo, hi],
                    'anchor': {**anchor, 'date': anchor['date'].isoformat()},
                    'fitted_trend_score_at_anchor': round(fitted, 2)},
            'run': {'samples': samples, 'seed': 1}, 'daily': daily}


def refresh(*, check_only=False, today=None):
    """Record failures, keep last good curve, and explicitly alert degradation.

    A changed upstream is *not* executed or adopted. Reviewed calculation can
    continue on fresh Epoch data while the upstream update awaits review.
    """
    from fri_forecaster import alert
    today = today or datetime.now(timezone.utc).date()
    old = json.loads(STATUS.read_text()) if STATUS.exists() else {}
    status = dict(old)
    status['attemptedAt'] = today.isoformat()
    problems = []
    try:
        status['upstream'] = check_upstream()
        status['checkedAt'] = today.isoformat()
        status.pop('checkError', None)
        if status['upstream']['reviewRequired']:
            problems.append('Upstream code changed; review required')
    except Exception as exc:
        status['checkError'] = type(exc).__name__
        problems.append('Upstream check failed')
    if not check_only:
        try:
            snapshot_day, path = eci.latest()
            if snapshot_day != today:
                path = eci.fetch(today=today)
            value = project(path, today, today)
            write_json(CACHE, value)
            status['refreshedAt'] = today.isoformat()
            status.pop('refreshError', None)
        except Exception as exc:
            status['refreshError'] = type(exc).__name__
            problems.append('Projection refresh failed; retaining last good curve')
    elif status.get('refreshError'):
        problems.append('Projection refresh remains failed')
    status['problems'] = problems
    fingerprint = '|'.join(problems) + (status.get('upstream', {}).get('commit', '') if problems else '')
    if problems and (fingerprint != old.get('alerted') or not old.get('alerted')):
        sent = alert.send('airo', 'ECI trend needs attention', '; '.join(problems), severity='notice')
        if sent:
            status['alerted'] = fingerprint
    elif not problems:
        status.pop('alerted', None)
    write_json(STATUS, status)
    print(json.dumps(status, sort_keys=True))
    # Degradation is explicit in status + UI; it must not discard valid forecasts.
    return status


def freshness(trend, status=None):
    status = status if status is not None else (json.loads(STATUS.read_text()) if STATUS.exists() else {})
    return {'checkedAt': status.get('checkedAt'), 'refreshedAt': status.get('refreshedAt'),
            'problems': status.get('problems', []), 'maxAgeDays': MAX_AGE_DAYS,
            'approvedCommit': trend['source'].get('commit'),
            'snapshotDate': trend['source']['retrieved']}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--check-only', action='store_true')
    refresh(check_only=parser.parse_args().check_only)
