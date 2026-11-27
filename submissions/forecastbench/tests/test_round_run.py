from argparse import Namespace
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from types import SimpleNamespace

from forecastbench import round_run


def make_runner(tmp_path, calls=2, upload=True):
    (tmp_path / 'logs').mkdir()
    return round_run.RoundRun(Namespace(root=tmp_path, due='2026-01-04', calls=calls, upload=upload,
                                        sample=None, timeout=None, tag=None))


def submission(number, *members):
    return round_run.Submission(number, f'example-{number}', 'Example Team', 'mean', members)


def run_submissions(runner, *submissions):
    with ThreadPoolExecutor(max_workers=runner.args.calls) as pool, ThreadPoolExecutor(max_workers=1) as uploader:
        return runner.run_submissions(pool, uploader, submissions)


def test_later_set_uses_freed_workers_and_uploads_before_first(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)
    slow_started, later_uploaded = Event(), Event()
    lock = Lock()
    active = {}
    events = []

    def forecast(spec, workers):
        with lock:
            active[spec] = workers
            events.append(('start', spec))
            assert sum(active.values()) <= 2
        if spec == 'slow':
            slow_started.set()
            assert later_uploaded.wait(5)
        elif spec == 'fast':
            assert slow_started.wait(5)
        else:
            with lock:
                assert active == {'slow': 1, 'later': 1}
        with lock:
            del active[spec]
            events.append(('finish', spec))

    def invoke(module, *args, **kwargs):
        number = args[args.index('--set-number') + 1]
        if module == 'forecastbench.upload':
            assert not (runner.logs / 'upload-confirmed').exists()
            events.append(('upload', number))
            if number == 2:
                assert not (runner.logs / 'first-upload-confirmed').exists()
                later_uploaded.set()
        return 0

    monkeypatch.setattr(runner, 'run_member', forecast)
    monkeypatch.setattr(round_run, 'invoke', invoke)
    code = run_submissions(runner, submission(1, 'fast', 'slow'), submission(2, 'later'))
    assert code == 0
    assert events.index(('upload', 2)) < events.index(('finish', 'slow')) < events.index(('upload', 1))
    assert (runner.logs / 'first-upload-confirmed').exists()
    assert (runner.logs / 'upload-confirmed').exists()
    assert runner.round_log.read_text().count('build exited 0') == 2


def test_shared_member_has_one_writer_and_retry_precedes_new_work(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)
    later_started, later_finished, shared_retry_started = Event(), Event(), Event()
    attempts = Counter()
    active = set()
    built = []
    uploaded = []
    lock = Lock()

    def forecast(spec, workers):
        with lock:
            assert spec not in active
            active.add(spec)
            attempts[spec] += 1
            attempt = attempts[spec]
        if spec == 'shared' and attempt == 1:
            assert later_started.wait(5)
        elif spec == 'later':
            later_started.set()
            assert shared_retry_started.wait(5)
        elif spec == 'shared':
            shared_retry_started.set()
            assert later_finished.wait(5)
        elif spec == 'last':
            assert shared_retry_started.is_set()
        with lock:
            active.remove(spec)
        if spec == 'later':
            later_finished.set()

    def build(s, attempt):
        with lock:
            assert active.isdisjoint(s.members)
            if s.number == 2:
                assert attempts['shared'] == 2
        built.append((s.number, attempt))
        return s.number != 1 or attempt == 2

    def upload(s, total):
        uploaded.append(s.number)
        return True

    monkeypatch.setattr(runner, 'run_member', forecast)
    monkeypatch.setattr(runner, 'build', build)
    monkeypatch.setattr(runner, 'upload', upload)
    code = run_submissions(runner, submission(1, 'shared', 'first'),
                           submission(2, 'later', 'shared'), submission(3, 'last'))
    assert code == 0
    assert attempts == {'shared': 2, 'first': 2, 'later': 1, 'last': 1}
    assert built[0] == (1, 1)
    assert sorted(built) == [(1, 1), (1, 2), (2, 1), (3, 1)]
    assert sorted(uploaded) == [1, 2, 3]


def test_upload_failure_keeps_other_sets_and_uses_no_forecast_retry(tmp_path, monkeypatch):
    runner = make_runner(tmp_path, calls=1)
    forecasts = []
    uploads = []

    def invoke(module, *args, **kwargs):
        if module == 'forecastbench.upload':
            number = args[args.index('--set-number') + 1]
            uploads.append(number)
            return int(number == 1)
        return 0

    monkeypatch.setattr(runner, 'run_member', lambda spec, slots: forecasts.append(spec))
    monkeypatch.setattr(round_run, 'invoke', invoke)
    assert run_submissions(runner, submission(1, 'a'), submission(2, 'b')) == 4
    assert forecasts == ['a', 'b']
    assert uploads == [1, 2]
    assert not (runner.logs / 'first-upload-confirmed').exists()
    assert not (runner.logs / 'upload-confirmed').exists()


def test_provider_key_refusal_pages_once_when_members_overlap(tmp_path, monkeypatch):
    runner = make_runner(tmp_path, upload=False)
    pages = []
    monkeypatch.setenv('FORECASTER_ENV_FILE', '/tmp/example-keys')
    monkeypatch.setattr(round_run.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=2))
    monkeypatch.setattr(round_run.alert, 'send', lambda *args, **kwargs: pages.append(args))
    monkeypatch.setattr(runner, 'build', lambda *args: False)
    members = ['provider/model-a@high,airo-none,exa', 'provider/model-b@high,airo-none,tavily']
    assert run_submissions(runner, submission(1, *members)) == 1
    assert len(pages) == 1
    assert pages[0][:2] == ('forecastbench', 'run FAILED')
    assert "provider's API key was refused" in pages[0][2]
    assert (runner.logs / 'paged').exists()


def test_scoring_members_run_after_upload_and_reuse_submitted_work(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)
    conditions = {'first': {}, 'score': {'submit': False}}
    members = {'first': ('common',), 'score': ('common', 'score-only')}
    registry = {'conditions': conditions, 'names': {'example-first': {'aggregate': 'mean'}}}
    forecasts = []

    def forecast(spec, slots):
        if spec == 'score-only':
            assert (runner.logs / 'upload-confirmed').exists()
        forecasts.append(spec)

    monkeypatch.setenv('FB_ORG', 'Example Team')
    monkeypatch.setattr(round_run.names, 'member_specs', lambda reg, condition: members[condition])
    monkeypatch.setattr(round_run.names, 'current', lambda reg, condition: f'example-{condition}')
    monkeypatch.setattr(round_run, 'invoke', lambda *args, **kwargs: 0)
    monkeypatch.setattr(runner, 'run_member', forecast)
    assert runner.run(registry) == 0
    assert forecasts == ['common', 'score-only', 'score-only']
