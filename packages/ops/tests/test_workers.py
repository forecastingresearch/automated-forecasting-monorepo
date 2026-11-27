"""Production queue integration without provider calls."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    'production', Path(__file__).parents[1] / 'production.py')
production = importlib.util.module_from_spec(spec)
spec.loader.exec_module(production)


@pytest.fixture
def runtime(tmp_path):
    config = {'root': str(tmp_path), 'path': '/usr/bin:/bin', 'socket': str(tmp_path / 'site.sock')}
    runtime = production.Runtime(config)
    release = runtime.root / 'releases' / 'active'
    (release / 'code').mkdir(parents=True)
    production.write_json(release / 'release.json', {'release': 'active'})
    production.link(release, runtime.current)
    (runtime.root / 'jobs-enabled').touch()
    (runtime.root / 'job-queue-enabled').touch()
    return runtime


def enqueue(runtime, kind, *, now=None, name=None):
    now = now or datetime.now(timezone.utc)
    name = name or kind
    job = {'id': name, 'kind': kind}
    runtime.job_queue().enqueue(name, job, now, now + timedelta(minutes=30))
    return name, job


def receipt(runtime, key):
    return runtime.root / 'runs' / f'{key}.json'


def test_reconcile_terminal_receipt_and_interrupt_paid_claim(runtime, monkeypatch):
    queue = runtime.job_queue()
    now = datetime.now(timezone.utc)
    key, _ = enqueue(runtime, 'forecastbench', now=now)
    assert queue.claim('forecast', now)['key'] == key
    production.write_json(receipt(runtime, key), {'key': key, 'status': 'succeeded'})
    alerts = []
    monkeypatch.setattr(runtime, 'alert', lambda *args, **kwargs: alerts.append(kwargs['title']))

    with runtime.lane_lock('forecast'):
        assert not runtime.work_once('forecast')

    assert queue.list()[0]['status'] == 'succeeded'
    assert alerts == []

    interrupted, _ = enqueue(runtime, 'forecast', now=now, name='interrupt')
    assert queue.claim('forecast', now)['key'] == interrupted
    production.write_json(receipt(runtime, interrupted), {'key': interrupted, 'status': 'running'})

    with runtime.lane_lock('forecast'):
        assert not runtime.work_once('forecast')
        assert not runtime.work_once('forecast')

    assert {row['status'] for row in queue.list()} == {'succeeded', 'interrupted'}
    assert json.loads(receipt(runtime, interrupted).read_text())['status'] == 'interrupted'
    assert alerts == ['run interrupted']


def test_worker_uses_attempt_receipts_for_news_retries(runtime, monkeypatch):
    key, _ = enqueue(runtime, 'news-poll')
    calls = []

    def execute(attempt, job, *, scheduled_at, latest_start):
        calls.append(attempt)
        failed = len(calls) == 1
        production.write_json(receipt(runtime, attempt), {
            'key': attempt, 'status': 'failed' if failed else 'succeeded'})
        return True

    monkeypatch.setattr(runtime, 'execute_job', execute)
    queue = runtime.job_queue()
    original_retry = queue.retry

    # Run the bounded retry now rather than waiting for the production delay.
    monkeypatch.setattr(queue, 'retry', lambda key, now, reason: original_retry(
        key, now, reason, delay=timedelta(0)))
    monkeypatch.setattr(runtime, 'job_queue', lambda: queue)

    with runtime.lane_lock('refresh'):
        assert runtime.work_once('refresh')
        assert queue.list()[0]['status'] == 'queued'
        assert runtime.work_once('refresh')
        assert not runtime.work_once('refresh')

    assert calls == [key, f'{key}-retry-2']
    assert queue.list()[0]['status'] == 'succeeded'
    assert json.loads(receipt(runtime, key).read_text())['status'] == 'failed'


def test_worker_expiry_notice_resumes_from_its_receipt(runtime, monkeypatch):
    key, _ = enqueue(runtime, 'forecastbench')
    alerts = []
    monkeypatch.setattr(runtime, 'execute_job', lambda *args, **kwargs: False)

    def send(*args, **kwargs):
        assert kwargs['require_delivery'] is True
        alerts.append(kwargs['title'])
        return True

    monkeypatch.setattr(runtime, 'alert', send)

    with runtime.lane_lock('forecast'):
        assert runtime.work_once('forecast')
    assert runtime.job_queue().list()[0]['status'] == 'expired'
    assert alerts == []

    # An earlier worker wrote the receipt and died before it could send the notice.
    production.write_json(receipt(runtime, key), {
        'key': key, 'status': 'expired', 'reason': 'Latest start time passed'})
    now = datetime.now(timezone.utc)
    runtime.queue_tick([], now)
    assert alerts == []
    runtime.report_queue_notices(now)
    runtime.report_queue_notices(now + timedelta(minutes=2))

    assert alerts == ['scheduled job expired']
    assert runtime.job_queue().pending_expirations() == []


def test_queue_tick_does_not_wait_for_operation_or_lane_locks(runtime):
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    older = (now - timedelta(minutes=1)).timestamp()
    os.utime(runtime.current, (older, older), follow_symlinks=False)
    os.utime(runtime.root / 'jobs-enabled', (older, older))
    os.utime(runtime.root / 'job-queue-enabled', (older, older))
    news = {'id': 'news', 'kind': 'news-poll', 'daily_utc': now.strftime('%H:%M')}

    with runtime.lock(), runtime.lane_lock('forecast'):
        runtime.queue_tick([news], now)
        assert runtime.job_queue().list()[0]['status'] == 'queued'
    with runtime.lane_lock('forecast'):
        with runtime.lane_lock('forecast', wait=False) as owns_forecast:
            assert not owns_forecast
        with runtime.lane_lock('refresh', wait=False) as owns_refresh:
            assert owns_refresh


def test_worker_exits_one_pass_when_queue_is_disabled(runtime, monkeypatch):
    (runtime.root / 'job-queue-enabled').unlink()
    monkeypatch.setattr(runtime, 'worker_runtimes', lambda: pytest.fail('queue is disabled'))
    runtime.worker('forecast', once=True)


def test_reenable_recovers_interrupted_job_without_restarting_it(runtime, monkeypatch):
    now = datetime.now(timezone.utc)
    key, _ = enqueue(runtime, 'forecastbench', now=now)
    queue = runtime.job_queue()
    assert queue.claim('forecast', now)['key'] == key
    marker = runtime.root / 'job-queue-enabled'
    marker.unlink()
    monkeypatch.setattr(runtime, 'alert', lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime, 'execute_job', lambda *args, **kwargs: pytest.fail('would duplicate paid run'))
    with runtime.lane_lock('forecast'):
        assert not runtime.work_once('forecast')
        assert queue.list()[0]['status'] == 'running'
        marker.touch()
        assert not runtime.work_once('forecast')
    assert queue.list()[0]['status'] == 'interrupted'
    assert json.loads(receipt(runtime, key).read_text())['status'] == 'interrupted'


def test_bad_dashboard_config_does_not_block_other_workers(runtime, monkeypatch, tmp_path):
    directory = tmp_path / 'config'
    directory.mkdir()
    monkeypatch.setenv('DASHBOARD_CONFIG_DIR', str(directory))
    primary = directory / 'airo.json'
    production.write_json(primary, runtime.config)
    (directory / 'eeai.json').write_text('{invalid')
    production.write_json(directory / 'rsi.json', {
        'dashboard': 'rsi', 'root': str(tmp_path / 'rsi'), 'socket': str(tmp_path / 'rsi.sock'),
        'path': '/usr/bin:/bin', 'panel_runtime_config': str(primary)})
    assert [member.name for member in runtime.worker_runtimes()] == ['airo', 'rsi']


def test_worker_recovers_only_unpinned_manual_receipts_in_its_lane(runtime, monkeypatch):
    paid = receipt(runtime, 'paid')
    refresh = receipt(runtime, 'refresh')
    production.write_json(paid, {'key': 'paid', 'job': 'airo', 'status': 'running'})
    production.write_json(refresh, {'key': 'refresh', 'job': 'data', 'kind': 'refresh',
                                    'status': 'running'})
    alerts = []
    monkeypatch.setattr(runtime, 'alert', lambda job, *args, **kwargs: alerts.append(job['kind']))

    with runtime.lane_lock('forecast'):
        with runtime.pin(runtime.root / 'sites/job-paid'):
            assert runtime.recover_worker('forecast')
            assert json.loads(paid.read_text())['status'] == 'running'
        assert not runtime.recover_worker('forecast')

    assert json.loads(paid.read_text())['status'] == 'interrupted'
    assert json.loads(refresh.read_text())['status'] == 'running'
    assert alerts == ['forecast']


def test_idle_worker_does_not_scan_receipts_or_claim(runtime, monkeypatch):
    monkeypatch.setattr(runtime, 'worker_runtimes', lambda: [runtime])
    monkeypatch.setattr(runtime, 'recover_worker', lambda *args: pytest.fail('not maintenance time'))
    monkeypatch.setattr(runtime, 'work_once', lambda *args: pytest.fail('no claimable work'))

    assert not runtime.worker_pass('refresh', maintain=False)
    assert not runtime.job_queue().path.exists()


def test_notice_reconciles_legacy_receipt_before_reporting_expiry(runtime, monkeypatch):
    now = datetime.now(timezone.utc)
    key, _ = enqueue(runtime, 'forecastbench', now=now - timedelta(hours=1))
    production.write_json(receipt(runtime, key), {'key': key, 'job': key, 'status': 'succeeded'})
    monkeypatch.setattr(runtime, 'alert', lambda *args, **kwargs: pytest.fail('legacy run succeeded'))

    runtime.queue_tick([], now)
    runtime.report_queue_notices(now)
    assert runtime.job_queue().list()[0]['status'] == 'succeeded'
    assert runtime.job_queue().pending_expirations() == []


def test_tick_expires_without_running_preflight_or_sending_notice(runtime, monkeypatch):
    now = datetime.now(timezone.utc)
    key, _ = enqueue(runtime, 'forecast', now=now - timedelta(hours=1))
    monkeypatch.setattr(runtime, 'alert', lambda *args, **kwargs: pytest.fail('tick cannot send alerts'))
    monkeypatch.setattr(production, 'output', lambda *args, **kwargs: pytest.fail('tick cannot run preflight'))

    runtime.queue_tick([], now)

    assert runtime.job_queue().pending_expirations()[0]['key'] == key
    assert not receipt(runtime, key).exists()


def test_undelivered_notice_stays_pending_for_a_later_worker_pass(runtime, monkeypatch):
    now = datetime.now(timezone.utc)
    key, _ = enqueue(runtime, 'forecastbench', now=now - timedelta(hours=1))
    attempts = []

    def notify(*args, **kwargs):
        attempts.append(kwargs)
        return len(attempts) == 2

    monkeypatch.setattr(runtime, 'alert', notify)
    runtime.queue_tick([], now)
    runtime.report_queue_notices(now)
    runtime.report_queue_notices(now + timedelta(seconds=59))
    assert len(attempts) == 1
    assert runtime.job_queue().pending_expirations()[0]['key'] == key

    runtime.report_queue_notices(now + timedelta(minutes=1))
    assert len(attempts) == 2
    assert all(attempt['require_delivery'] for attempt in attempts)
    assert runtime.job_queue().pending_expirations() == []


def test_worker_maintenance_sends_notice_without_holding_lanes(runtime, monkeypatch):
    now = datetime.now(timezone.utc)
    enqueue(runtime, 'forecastbench', now=now - timedelta(hours=1))
    runtime.queue_tick([], now)
    code = runtime.current.resolve() / 'code'
    monkeypatch.setattr(production, '__file__', str(code / 'packages/ops/production.py'))
    monkeypatch.setattr(runtime, 'worker_runtimes', lambda: [runtime])

    def notify(*args, **kwargs):
        with runtime.lane_lock('forecast', wait=False) as forecast, runtime.lane_lock('refresh', wait=False) as refresh:
            assert forecast and refresh
        return True

    monkeypatch.setattr(runtime, 'alert', notify)
    runtime.worker('forecast', once=True)
    assert runtime.job_queue().pending_expirations() == []
