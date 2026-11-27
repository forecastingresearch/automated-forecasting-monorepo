"""Queue persistence, claiming and late-start policy without launching real jobs."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import stat
from threading import Barrier

import pytest

from packages.ops import production
from packages.ops.job_queue import Queue, latest_start

MIDNIGHT = datetime(2026, 11, 22, 0, 5, tzinfo=timezone.utc)
FORECAST = {'id': 'forecastbench-round', 'kind': 'forecastbench', 'at': MIDNIGHT.isoformat(),
            'due': '2026-11-22'}
NEWS = {'id': 'recent-news-poll', 'kind': 'news-poll', 'daily_utc': '11:45'}
ECONOMIC = {'id': 'economic-data', 'dashboard': 'eeai', 'kind': 'refresh', 'daily_utc': '15:15'}


def enqueue(queue, job, when=MIDNIGHT):
    return queue.enqueue(job['id'], job, when, latest_start(job, when))


def test_discovery_survives_restart_and_preserves_existing_receipts(tmp_path):
    receipts = tmp_path / 'runs'
    receipts.mkdir()
    (receipts / 'forecastbench-round-20261122T0005.json').write_text('{"status": "running"}')
    database = tmp_path / 'jobs.db'
    queue = Queue(database)
    now = MIDNIGHT.replace(hour=12, minute=15)
    assert queue.discover(now, [NEWS, FORECAST], production.scheduled_between, receipts, MIDNIGHT) == 1
    restarted = Queue(database)
    assert restarted.discover(now, [NEWS, FORECAST], production.scheduled_between, receipts, MIDNIGHT) == 0
    entry, = restarted.list()
    assert (entry['key'], entry['lane'], entry['status']) == ('recent-news-poll-20261122', 'refresh', 'queued')
    assert stat.S_IMODE(database.stat().st_mode) == 0o600


def test_release_activation_window_excludes_past_occurrences(tmp_path):
    queue = Queue(tmp_path / 'jobs.db')
    enabled = MIDNIGHT + timedelta(seconds=1)
    assert queue.discover(enabled, [FORECAST], production.scheduled_between, tmp_path, enabled) == 0
    assert queue.list() == []


def test_timestamp_at_activation_is_discovered_once(tmp_path):
    queue = Queue(tmp_path / 'jobs.db')
    assert queue.discover(MIDNIGHT, [FORECAST], production.scheduled_between, tmp_path, MIDNIGHT) == 1
    assert queue.discover(MIDNIGHT, [FORECAST], production.scheduled_between, tmp_path, MIDNIGHT) == 0


def test_unchanged_schedule_catches_up_across_deploy(tmp_path):
    db = tmp_path / 'jobs.db'
    before_poll = MIDNIGHT.replace(hour=11, minute=44)
    after_poll = before_poll + timedelta(minutes=2)
    assert Queue(db).discover(before_poll, [NEWS], production.scheduled_between, tmp_path, MIDNIGHT,
                              enabled_since=MIDNIGHT) == 0
    assert Queue(db).discover(after_poll, [NEWS], production.scheduled_between, tmp_path, after_poll,
                              enabled_since=MIDNIGHT) == 1
    assert Queue(db).claim('refresh', after_poll)['key'] == 'recent-news-poll-20261122'


@pytest.mark.parametrize('reenabled', [False, True])
def test_enabling_or_changed_schedule_does_not_look_behind_activation(tmp_path, reenabled):
    queue = Queue(tmp_path / 'jobs.db')
    before_poll = MIDNIGHT.replace(hour=11, minute=44)
    activation = before_poll + timedelta(minutes=2)
    initial = NEWS if reenabled else dict(NEWS, daily_utc='11:30')
    queue.discover(before_poll, [initial], production.scheduled_between, tmp_path, before_poll,
                   enabled_since=MIDNIGHT)
    assert queue.discover(activation, [NEWS], production.scheduled_between, tmp_path, activation,
                          enabled_since=activation if reenabled else MIDNIGHT) == 0
    assert queue.list() == []


def test_refresh_can_run_while_forecast_lane_is_occupied(tmp_path):
    queue = Queue(tmp_path / 'jobs.db')
    enqueue(queue, FORECAST)
    job = queue.claim('forecast', MIDNIGHT)
    assert job['key'] == FORECAST['id']
    for refresh, when in ((NEWS, MIDNIGHT.replace(hour=11, minute=45)),
                          (ECONOMIC, MIDNIGHT.replace(hour=15, minute=15))):
        enqueue(queue, refresh, when)
        assert queue.claim('refresh', when)['key'] == refresh['id']
        assert queue.finish(refresh['id'], 'succeeded', when + timedelta(seconds=30))
    assert queue.list(('running',)) == [job]


def test_claim_is_exclusive_with_concurrent_connections(tmp_path):
    db = tmp_path / 'jobs.db'
    enqueue(Queue(db), NEWS)
    enqueue(Queue(db), ECONOMIC)
    ready = Barrier(2)

    def claim():
        ready.wait(timeout=5)
        return Queue(db).claim('refresh', MIDNIGHT)

    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(claim)
        second = pool.submit(claim)
        results = [first.result(), second.result()]
    claimed, = (row for row in results if row is not None)
    assert claimed['key'] == min(NEWS['id'], ECONOMIC['id'])


@pytest.mark.parametrize('job,window', [(FORECAST, timedelta(minutes=1)), (ECONOMIC, timedelta(hours=2))])
def test_claim_rejects_expired_occurrences_even_before_sweep(tmp_path, job, window):
    queue = Queue(tmp_path / 'jobs.db')
    enqueue(queue, job)
    cutoff = MIDNIGHT + window
    assert queue.claim('forecast' if job == FORECAST else 'refresh', cutoff) is None
    expired, = queue.expire(cutoff)
    assert expired['status'] == 'expired'
    assert expired['attempt'] == 0
    assert queue.expire(cutoff) == []


def test_interrupted_paid_claim_cannot_retry(tmp_path):
    db = tmp_path / 'queue.sqlite'
    queue = Queue(db)
    enqueue(queue, FORECAST)
    assert queue.claim('forecast', MIDNIGHT)['attempt'] == 1
    restarted = Queue(db)
    abandoned, = restarted.list(('running',))
    assert restarted.finish(abandoned['key'], 'interrupted', MIDNIGHT + timedelta(seconds=15))
    assert not restarted.retry(FORECAST['id'], MIDNIGHT, 'retry')
    assert not restarted.enqueue(FORECAST['id'], FORECAST, MIDNIGHT, latest_start(FORECAST, MIDNIGHT))
    assert restarted.claim('forecast', MIDNIGHT) is None


def test_expiry_report_is_pending_across_restarts_until_acknowledged(tmp_path):
    db = tmp_path / 'jobs.db'
    queue = Queue(db)
    enqueue(queue, FORECAST)
    cutoff = MIDNIGHT + timedelta(minutes=1)
    expired, = queue.expire(cutoff)
    assert Queue(db).pending_expirations() == [expired]
    Queue(db).mark_expiry_reported(FORECAST['id'], cutoff, status='skipped', reason='No conditions due')
    assert queue.pending_expirations() == []
    assert queue.list()[0]['status'] == 'skipped'


def test_news_retries_wait_and_do_not_exceed_attempt_budget(tmp_path):
    queue = Queue(tmp_path / 'jobs.db')
    enqueue(queue, NEWS)
    for attempt in (1, 2, 3):
        when = MIDNIGHT + timedelta(minutes=5 * (attempt - 1))
        assert queue.claim('refresh', when)['attempt'] == attempt
        assert queue.retry(NEWS['id'], when, 'feed timed out') == (attempt < 3)
        if attempt < 3:
            assert queue.claim('refresh', when + timedelta(minutes=4)) is None
    assert queue.finish(NEWS['id'], 'failed', when, 'feed timed out')
    assert queue.list()[0]['attempt'] == 3


def test_publish_jobs_do_not_auto_retry_and_old_news_expires(tmp_path):
    queue = Queue(tmp_path / 'jobs.db')
    enqueue(queue, ECONOMIC)
    enqueue(queue, NEWS)
    assert queue.claim('refresh', MIDNIGHT)['job'] == ECONOMIC
    assert not queue.retry(ECONOMIC['id'], MIDNIGHT, 'refresh interrupted')
    assert queue.finish(ECONOMIC['id'], 'interrupted', MIDNIGHT)
    when = MIDNIGHT + timedelta(hours=1, minutes=55)
    assert queue.claim('refresh', when)['job'] == NEWS
    assert not queue.retry(NEWS['id'], when, 'feed timed out')


def test_read_only_status_does_not_create_queue(tmp_path):
    path = tmp_path / 'jobs.db'
    assert Queue(path).list() == []
    assert not path.exists()
