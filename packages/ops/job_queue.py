"""Durable scheduled occurrences for one dashboard on the production host."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3

REFRESH_START_WINDOW = timedelta(hours=2)
FORECAST_START_WINDOW = timedelta(minutes=1)
NEWS_RETRY_DELAY = timedelta(minutes=5)
NEWS_ATTEMPTS = 3
DISCOVERY_WINDOW = timedelta(days=2)
TERMINAL_STATES = frozenset({'succeeded', 'failed', 'skipped', 'interrupted', 'expired'})

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    key TEXT PRIMARY KEY,
    job TEXT NOT NULL,
    lane TEXT NOT NULL CHECK (lane IN ('forecast', 'refresh')),
    scheduled TEXT NOT NULL,
    latest_start TEXT NOT NULL,
    available TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN
        ('queued', 'running', 'expired', 'succeeded', 'failed', 'skipped', 'interrupted')),
    attempt INTEGER NOT NULL DEFAULT 0,
    started TEXT,
    finished TEXT,
    reason TEXT,
    reported_at TEXT
)
"""

SCHEDULES = """
CREATE TABLE IF NOT EXISTS schedules (
    job_id TEXT PRIMARY KEY,
    definition TEXT NOT NULL,
    enabled_since TEXT NOT NULL,
    scanned_until TEXT NOT NULL
)
"""

CLAIM_INDEX = """
CREATE INDEX IF NOT EXISTS jobs_to_claim ON jobs (lane, scheduled, key)
    WHERE status = 'queued'
"""

EXPIRY_INDEX = """
CREATE INDEX IF NOT EXISTS jobs_to_report ON jobs (scheduled, key)
    WHERE status = 'expired' AND reported_at IS NULL
"""

RUNNING_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS one_running_job_per_lane ON jobs (lane)
    WHERE status = 'running'
"""


def lane_for(job):
    return 'refresh' if job['kind'] in ('news-poll', 'eci-upstream', 'refresh') else 'forecast'


def latest_start(job, scheduled):
    window = REFRESH_START_WINDOW if lane_for(job) == 'refresh' else FORECAST_START_WINDOW
    return scheduled + window


def stamp(when):
    if when.utcoffset() is None:
        raise ValueError('Job queue timestamps must have a timezone')
    return when.astimezone(timezone.utc).isoformat(timespec='microseconds')


def unpack(row):
    result = dict(row)
    result['job'] = json.loads(result['job'])
    return result


class Queue:
    def __init__(self, path):
        self.path = Path(path).absolute()

    @contextmanager
    def _write(self):
        # Pre-create privately; the database and its journal hold the scheduled job payloads.
        fd = os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                db.execute(SCHEMA)
                db.execute(SCHEDULES)
                db.execute(CLAIM_INDEX)
                db.execute(RUNNING_INDEX)
                db.execute(EXPIRY_INDEX)
                yield db
        finally:
            db.close()

    @staticmethod
    def _enqueue(db, key, job, scheduled, deadline):
        return bool(db.execute(
            """INSERT INTO jobs (key, job, lane, scheduled, latest_start, available, status)
               VALUES (?, ?, ?, ?, ?, ?, 'queued') ON CONFLICT(key) DO NOTHING""",
            (key, json.dumps(job), lane_for(job), stamp(scheduled), stamp(deadline), stamp(scheduled)),
        ).rowcount)

    def enqueue(self, key, job, scheduled, latest_start):
        with self._write() as db:
            return self._enqueue(db, key, job, scheduled, latest_start)

    def discover(self, now, jobs, scheduled_between, receipt_dir, since, *, enabled_since=None):
        """Enqueue due occurrences since schedule activation, preserving existing receipts."""
        if since > now:
            return 0
        enabled = stamp(enabled_since or since)
        definitions = {job['id']: json.dumps(job, sort_keys=True) for job in jobs}
        with self._write() as db:
            previous = {row['job_id']: row for row in db.execute('SELECT * FROM schedules')}
            floors = {}
            for job_id, definition in definitions.items():
                prior = previous.get(job_id)
                if prior and prior['enabled_since'] == enabled and prior['definition'] == definition:
                    # A release change does not interrupt discovery for this schedule.
                    after = datetime.fromisoformat(prior['scanned_until'])
                    floors[job_id] = max(after, now - DISCOVERY_WINDOW)
                    until = max(now, after)
                else:
                    # Include an activation that falls exactly on a due minute.
                    floors[job_id] = since - timedelta(microseconds=1)
                    until = now
                db.execute('INSERT OR REPLACE INTO schedules VALUES (?, ?, ?, ?)',
                           (job_id, definition, enabled, stamp(until)))
            db.executemany('DELETE FROM schedules WHERE job_id = ?',
                           [(job_id,) for job_id in previous.keys() - definitions.keys()])
            if not floors:
                return 0
            return sum(self._enqueue(db, key, job, when, latest_start(job, when))
                       for key, job, when in scheduled_between(jobs, min(floors.values()),
                                                              now + timedelta(microseconds=1))
                       if when > floors[job['id']] and not (receipt_dir / f'{key}.json').exists())

    def has_work(self, lane, now):
        """Read whether the lane has a claim to reconcile or an eligible job."""
        at = stamp(now)
        return bool(self._read(
            """SELECT * FROM jobs
               WHERE lane = ? AND (status = 'running'
                   OR (status = 'queued' AND available <= ? AND ? < latest_start))
               LIMIT 1""",
            (lane, at, at),
        ))

    def claim(self, lane, now):
        """Claim the earliest eligible occurrence in a single database transaction."""
        at = stamp(now)
        with self._write() as db:
            row = db.execute(
                """SELECT key FROM jobs
                   WHERE lane = ? AND status = 'queued' AND available <= ? AND ? < latest_start
                     AND NOT EXISTS (SELECT 1 FROM jobs WHERE lane = ? AND status = 'running')
                   ORDER BY scheduled, key LIMIT 1""",
                (lane, at, at, lane),
            ).fetchone()
            if row is None:
                return None
            db.execute(
                """UPDATE jobs SET status = 'running', attempt = attempt + 1,
                         started = ?, finished = NULL, reason = NULL WHERE key = ?""",
                (at, row['key']),
            )
            return unpack(db.execute('SELECT * FROM jobs WHERE key = ?', (row['key'],)).fetchone())

    def finish(self, key, status, now, reason=None):
        if status not in TERMINAL_STATES:
            raise ValueError(f'Invalid completed job status: {status}')
        with self._write() as db:
            return bool(db.execute(
                """UPDATE jobs SET status = ?, finished = ?, reason = ?
                   WHERE key = ? AND status = 'running'""",
                (status, stamp(now), reason, key),
            ).rowcount)

    def retry(self, key, now, reason, delay=NEWS_RETRY_DELAY):
        """Requeue a failed free news poll while freshness and attempt limits allow."""
        available = stamp(now + delay)
        with self._write() as db:
            return bool(db.execute(
                """UPDATE jobs SET status = 'queued', available = ?, finished = ?, reason = ?
                   WHERE key = ? AND lane = 'refresh' AND json_extract(job, '$.kind') = 'news-poll'
                     AND status IN ('running', 'failed', 'interrupted')
                     AND attempt < ? AND ? < latest_start""",
                (available, stamp(now), reason, key, NEWS_ATTEMPTS, available),
            ).rowcount)

    def expire(self, now):
        at = stamp(now)
        with self._write() as db:
            rows = db.execute(
                """UPDATE jobs SET status = 'expired', finished = ?,
                         reason = 'Latest start time passed'
                   WHERE status = 'queued' AND latest_start <= ? RETURNING *""",
                (at, at),
            ).fetchall()
        return [unpack(row) for row in rows]

    def pending_expirations(self):
        return self._read("""SELECT * FROM jobs WHERE status = 'expired' AND reported_at IS NULL
                          ORDER BY scheduled, key""", [])

    def mark_expiry_reported(self, key, now, *, status='expired', reason=None):
        """Acknowledge a report and reconcile its cadence result in the same transaction."""
        if status not in TERMINAL_STATES:
            raise ValueError(f'Invalid expiry report status: {status}')
        with self._write() as db:
            db.execute("""UPDATE jobs SET reported_at = ?, status = ?, reason = COALESCE(?, reason)
                          WHERE key = ? AND status = 'expired' AND reported_at IS NULL""",
                       (stamp(now), status, reason, key))

    def _read(self, query, parameters):
        if not self.path.exists():
            return []
        db = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            # Another process may have created the file but be about to install
            # the schema. Status should still be available on the first tick.
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name = 'jobs'").fetchone():
                return []
            return [unpack(row) for row in db.execute(query, parameters)]
        finally:
            db.close()

    def list(self, statuses=None, limit=30):
        query = 'SELECT * FROM jobs'
        parameters = []
        if statuses:
            query += ' WHERE status IN (' + ', '.join('?' for _ in statuses) + ')'
            parameters.extend(statuses)
        query += ' ORDER BY scheduled DESC, key DESC LIMIT ?'
        parameters.append(limit)
        return self._read(query, parameters)
