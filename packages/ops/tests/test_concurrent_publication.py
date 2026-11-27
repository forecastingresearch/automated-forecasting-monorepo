"""Concurrency and retention tests for scheduled deployments, without provider calls."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from threading import Event

import pytest

from test_production import dashboard, p, release, runtime


def installed_release(runtime, index):
    name = f'20300101T00000{index}-' + 'a' * 12
    version = release(runtime, name)
    site = runtime.root / 'sites' / name
    site.mkdir()
    p.link(site, version / 'site')
    return version


def run_receipt(runtime, key):
    return json.loads((runtime.root / 'runs' / (key + '.json')).read_text())


def test_forecastbench_keeps_pinned_code_and_site_after_deploy(runtime, monkeypatch):
    primary, next_release, latest = [installed_release(runtime, i) for i in range(3)]
    p.link(primary, runtime.current)
    forecast_started = Event()
    forecast_finished = Event()
    news_finished = Event()
    staging_site = runtime.root / 'sites/job-round'
    verified_code = []

    def job(argv, **options):
        if any(str(a).endswith('fb_cron.sh') for a in argv):
            (staging_site / 'partial').touch()
            forecast_started.set()
            if not forecast_finished.wait(5):
                raise TimeoutError('waiting for rollout')
        elif argv[-1] == 'poll':
            news_finished.set()
        elif 'forecastbench.status' in argv[2]:
            verified_code.append(options['cwd'])

    monkeypatch.setattr(p, 'run', job)
    monkeypatch.setattr(runtime, 'verify_site', lambda _: None)
    monkeypatch.setattr(runtime, 'probe', lambda _: None)
    runtime.config['keep_releases'] = 2
    with ThreadPoolExecutor(max_workers=2) as threads:
        forecast = threads.submit(runtime.execute_job, 'round',
                                  {'id': 'round', 'kind': 'forecastbench', 'due': '2030-01-01'})
        try:
            assert forecast_started.wait(5)
            news = threads.submit(runtime.execute_job, 'poll', {'id': 'poll', 'kind': 'news-poll'})
            assert news_finished.wait(5)
            assert news.result(timeout=5)
            assert run_receipt(runtime, 'round')['status'] == 'running'
            with runtime.lock():
                runtime.activate(next_release)
                runtime.activate(latest)
                runtime.prune_locked()
                assert primary.is_dir()
                assert (staging_site / 'partial').is_file()
        finally:
            forecast_finished.set()
        assert forecast.result(timeout=5)
    assert verified_code == [primary / 'code']
    assert run_receipt(runtime, 'round')['status'] == 'succeeded'
    with runtime.lock():
        runtime.prune_locked()
    assert not primary.exists()


def test_forecast_publisher_rejects_concurrent_publication_change(runtime, monkeypatch):
    primary = installed_release(runtime, 0)
    p.link(primary, runtime.current)
    started = Event()
    finish = Event()

    def build(argv, **options):
        site = Path(options['env']['REDLINES_DOCROOT'])
        started.set()
        if not finish.wait(5):
            raise TimeoutError('waiting for publication')
        (site / 'index.html').write_bytes(dashboard('old candidate', 25))
        for name in p.DATA_FILES:
            (site / name).write_text('candidate')

    monkeypatch.setattr(p, 'output', lambda *a, **kw: 'fixture publish')
    monkeypatch.setattr(p, 'run', build)
    monkeypatch.setattr(runtime, 'alert', lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime, 'publish_public', lambda *_: pytest.fail('stale candidate'))
    newer_site = runtime.root / 'sites/job-newer'
    newer_site.mkdir()
    with ThreadPoolExecutor(max_workers=1) as threads:
        forecast = threads.submit(runtime.execute_job, 'forecast', {'id': 'forecast', 'kind': 'forecast'})
        try:
            assert started.wait(5)
            with runtime.lock():
                p.link(newer_site, primary / 'site')
        finally:
            finish.set()
        with pytest.raises(RuntimeError, match='Active publication changed'):
            forecast.result(timeout=5)
    assert (primary / 'site').resolve() == newer_site
    assert (runtime.root / 'sites/job-forecast/index.html').is_file()
    assert run_receipt(runtime, 'forecast')['stage'] == 'publish FAILED'


def test_execution_rechecks_queued_job_against_active_release(runtime, monkeypatch):
    primary = installed_release(runtime, 0)
    p.link(primary, runtime.current)
    p.write_json(primary / 'code' / p.JOBS, [])
    monkeypatch.setattr(p, 'run', lambda *args, **kwargs: pytest.fail('changed job'))
    job = {'id': 'poll', 'kind': 'news-poll', 'daily_utc': '11:45'}
    now = datetime.now(timezone.utc)
    assert not runtime.execute_job('expired', job, latest_start=now - timedelta(seconds=1))
    assert not (runtime.root / 'runs/expired.json').exists()
    assert runtime.execute_job('changed', job, latest_start=now + timedelta(seconds=30))
    receipt = run_receipt(runtime, 'changed')
    assert receipt['status'] == 'skipped'
    assert receipt['reason'] == 'Scheduled job changed before launch'


def test_queue_deploy_builds_without_holding_operation_lock(runtime, monkeypatch):
    from test_production import fake_install, published_release

    old = published_release(runtime)
    fake_install(runtime, monkeypatch)
    (runtime.root / 'job-queue-enabled').touch()
    command = p.run
    installing = Event()
    finish = Event()

    def build(argv, **options):
        if 'build-release' in argv:
            name = argv[argv.index('--release') + 1]
            assert '--concurrent-build' in argv
            runtime.build_release(name, 'a' * 40, concurrent=True)
        elif argv[:3] == ['python3', '-m', 'venv']:
            installing.set()
            if not finish.wait(5):
                raise TimeoutError('waiting for poll')
        else:
            command(argv, **options)

    monkeypatch.setattr(runtime, 'builder', lambda code: (code / p.LAUNCHER, True))
    monkeypatch.setattr(p, 'run', build)
    with ThreadPoolExecutor(max_workers=2) as threads:
        deployment = threads.submit(runtime.deploy)
        try:
            assert installing.wait(5)
            news = threads.submit(runtime.execute_job, 'poll', {'id': 'poll', 'kind': 'news-poll'})
            assert news.result(timeout=5)
            assert runtime.current.resolve() == old
        finally:
            finish.set()
        deployment.result(timeout=5)
    assert runtime.current.resolve() != old


def test_queue_rejects_rollback_to_legacy_scheduler_before_switch(runtime, monkeypatch):
    prior, active = [installed_release(runtime, i) for i in range(2)]
    p.link(active, runtime.current)
    p.link(prior, runtime.root / 'previous')
    (runtime.root / 'job-queue-enabled').touch()
    monkeypatch.setattr(runtime, 'builder', lambda _: (Path('legacy.py'), False))
    with pytest.raises(RuntimeError, match='disable the job queue'):
        runtime.rollback()
    assert runtime.current.resolve() == active


def test_related_dashboards_use_independent_operation_locks(tmp_path, runtime):
    primary_config = tmp_path / 'primary.json'
    p.write_json(primary_config, runtime.config)
    (runtime.root / 'job-queue-enabled').touch()
    child = p.Runtime({
        'root': str(tmp_path / 'eeai'), 'dashboard': 'eeai', 'socket': 'eeai.sock',
        'path': '/usr/bin', 'panel_runtime_config': str(primary_config),
    })
    with ThreadPoolExecutor(max_workers=1) as threads:
        with runtime.lock():
            def take_child_lock():
                with child.lock():
                    return True
            assert threads.submit(take_child_lock).result(timeout=5)


def test_deploy_leaves_a_newer_publication_selected(runtime, monkeypatch):
    from test_production import fake_install, published_release

    old = published_release(runtime)
    fake_install(runtime, monkeypatch)
    (runtime.root / 'job-queue-enabled').touch()
    command = p.run
    original_prepare = runtime.publish_frontend
    snapshot_pinned = Event()
    finish = Event()
    original_site = runtime.root / 'sites/original'
    (old / 'site').rename(original_site)
    p.link(original_site, old / 'site')
    newer_site = runtime.root / 'sites/job-newer'
    newer_site.mkdir()

    def build(argv, **options):
        if 'build-release' in argv:
            name = argv[argv.index('--release') + 1]
            runtime.build_release(name, 'a' * 40, concurrent=True)
        else:
            command(argv, **options)

    def frontend(code, site, *, source):
        result = original_prepare(code, site, source=source)
        assert source == original_site
        snapshot_pinned.set()
        if not finish.wait(5):
            raise TimeoutError('waiting for a new publication')
        return result

    monkeypatch.setattr(runtime, 'builder', lambda code: (code / p.LAUNCHER, True))
    monkeypatch.setattr(runtime, 'publish_frontend', frontend)
    monkeypatch.setattr(p, 'run', build)
    with ThreadPoolExecutor(max_workers=1) as threads:
        deployment = threads.submit(runtime.deploy)
        try:
            assert snapshot_pinned.wait(5)
            with runtime.lock():
                p.link(newer_site, old / 'site')
        finally:
            finish.set()
        with pytest.raises(RuntimeError, match='Active publication changed'):
            deployment.result(timeout=5)
    assert runtime.current.resolve() == old
    assert (old / 'site').resolve() == newer_site
    assert len(list((runtime.root / 'releases').glob('*/failed.json'))) == 1


def test_seed_cannot_overwrite_a_result_created_during_deploy(runtime, monkeypatch):
    candidate = installed_release(runtime, 0)
    code = candidate / 'code'
    source = code / p.AIRO / 'results' / 'accrued.jsonl'
    source.parent.mkdir()
    source.write_text('tracked seed')
    target = runtime.state / 'results' / 'accrued.jsonl'
    real_copy = p.shutil.copy2

    def copy_with_concurrent_writer(src, tmp):
        assert not target.exists()
        target.write_text('new forecast')
        real_copy(src, tmp)

    monkeypatch.setattr(p.shutil, 'copy2', copy_with_concurrent_writer)
    runtime.attach_state(code)
    assert target.read_text() == 'new forecast'
    assert source.resolve() == target
    assert list(target.parent.iterdir()) == [target]
