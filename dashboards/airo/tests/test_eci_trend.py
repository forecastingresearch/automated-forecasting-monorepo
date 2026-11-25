"""Publication freshness, safe upstream review, and reference-fit regression."""
import csv
import json
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pytest
from redlines import eci_trend as trend


def snapshot(tmp_path):
    path = tmp_path / 'epoch_capabilities_index_2026-11-25.csv'
    with path.open('w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Model', 'Display name', 'eci', 'date', 'Country (of organization)'])
        for i, (day, score) in enumerate([('2024-03-01', 100), ('2024-04-01', 101),
            ('2024-05-01', 102), ('2024-06-01', 103), ('2024-07-01', 105),
            ('2024-08-01', 107), ('2024-08-01', 106)]):
            writer.writerow([f'm{i}', 'Claude Fable 5' if i == 3 else f'm{i}', score, day, trend.eci.US])
    return path


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(trend, 'CACHE', tmp_path / 'curve.json')
    monkeypatch.setattr(trend, 'STATUS', tmp_path / 'status.json')
    from fri_forecaster import alert
    sender = Mock(return_value=1)
    monkeypatch.setattr(alert, 'send', sender)
    monkeypatch.setattr(trend, 'check_upstream', lambda: {'commit': trend.COMMIT, 'reviewRequired': False})
    return sender


def test_named_break_and_same_day_maximum(tmp_path):
    path = snapshot(tmp_path)
    result = trend.project(path, date(2026, 11, 25), date(2026, 11, 25), samples=100)
    assert len(trend.frontier(path)) == 6
    assert result['fit']['breakpoint'] == 'Claude Fable 5'
    assert result['fit']['anchor']['score'] == 107
    assert result['fit']['pts_per_year'] == 23.9
    assert all(row['p25'] <= row['p50'] <= row['p75'] for row in result['daily'])
    assert result == trend.project(path, date(2026, 11, 25), date(2026, 11, 25), samples=100)


@pytest.mark.parametrize('day', [date(2026, 11, 23), date(2026, 11, 26), date(2026, 11, 29)])
def test_refresh_on_any_publication_day(tmp_path, monkeypatch, runtime, day):
    path = snapshot(tmp_path)
    monkeypatch.setattr(trend.eci, 'latest', lambda: (date(2026, 11, 20), path))
    fetch = Mock(return_value=path)
    monkeypatch.setattr(trend.eci, 'fetch', fetch)
    monkeypatch.setattr(trend, 'project', lambda p, stamp, now: {'snapshot': stamp.isoformat()})
    status = trend.refresh(today=day)
    fetch.assert_called_once_with(today=day)
    assert status['problems'] == []
    assert json.loads(trend.CACHE.read_text())['snapshot'] == day.isoformat()
    runtime.assert_not_called()


def test_failed_refresh_preserves_last_curve_and_alerts_once(tmp_path, monkeypatch, runtime):
    trend.CACHE.write_text('{"old":true}')
    monkeypatch.setattr(trend.eci, 'latest', Mock(side_effect=ValueError('bad data')))
    first = trend.refresh(today=date(2026, 11, 25))
    trend.refresh(today=date(2026, 11, 26))
    assert json.loads(trend.CACHE.read_text()) == {'old': True}
    assert first['refreshError'] == 'ValueError'
    assert 'retaining last good curve' in first['problems'][0]
    assert runtime.call_count == 1


def test_changed_upstream_is_flagged_not_adopted(monkeypatch, runtime):
    monkeypatch.setattr(trend, 'check_upstream', lambda: {'commit': 'a' * 40, 'reviewRequired': True})
    status = trend.refresh(check_only=True)
    assert status['problems'] == ['Upstream code changed; review required']
    assert not trend.CACHE.exists()
    runtime.assert_called_once()


def test_data_only_upstream_commit_needs_no_method_review(monkeypatch):
    source = b'reviewed source'
    import hashlib
    monkeypatch.setattr(trend, 'SOURCE_SHA256', hashlib.sha256(source).hexdigest())
    feed = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>commit/' + 'a' * 40 + '</id></entry></feed>').encode()
    monkeypatch.setattr(trend, 'download', lambda url: feed if url.endswith('.atom') else source)
    assert trend.check_upstream()['reviewRequired'] is False


def test_recovery_clears_error_and_allows_future_alert(monkeypatch, runtime, tmp_path):
    trend.STATUS.write_text(json.dumps({'refreshError': 'OSError', 'problems': ['failed'], 'alerted': 'failed'}))
    path = snapshot(tmp_path)
    monkeypatch.setattr(trend.eci, 'latest', lambda: (date.today(), path))
    monkeypatch.setattr(trend, 'project', lambda *args: {'ok': True})
    status = trend.refresh(today=date.today())
    assert not status['problems']
    assert 'refreshError' not in status and 'alerted' not in status
