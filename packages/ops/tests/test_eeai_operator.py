"""Exercise the installed dispatcher against a private, offline EEAI installation."""
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import shutil
import ssl
import subprocess
import sys
import time
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
import zipfile

from dashboard import page, site
from eeai import config, survey
import pytest

OPS = Path(__file__).resolve().parents[1]
ROOT = OPS.parents[1]
sys.path.insert(0, str(OPS))
import eeai_operator as operator

DAY = '2026-02-04'
AT = '2026-11-19T15:15:00Z'
SHA = 'a' * 40
BASELINE = {'source': 'fred', 'as_of': DAY}
JOB = {'id': 'eeai-economic-data', 'dashboard': 'eeai', 'kind': 'refresh', 'daily_utc': '15:15'}


@pytest.fixture
def installed(tmp_path):
    root = tmp_path / 'runtime'
    active = root / 'releases' / '20261010T000000-aaaaaaaaaaaa'
    code = active / 'code'
    old = root / 'sites' / 'original'
    config_dir = tmp_path / 'private'
    public = tmp_path / 'public'
    bin_dir = tmp_path / 'bin'
    runs = root / 'state/results'
    for path in (old, code / 'code', code / 'packages/ops', code / 'dashboards',
                 code / '.venv/bin', config_dir, public, bin_dir, runs):
        path.mkdir(parents=True)
    (root / 'current').symlink_to(active)
    (active / 'site').symlink_to(old)
    (code / 'dashboards/eeai').symlink_to(ROOT / 'dashboards/eeai')
    (code / 'packages/ops/jobs.json').write_text(json.dumps([JOB]))
    document = survey.load()
    rows = [dict(instrument=document['instrument'], run_id='finished', run_date='2026-01-01',
                 label='Fixture model', question_id=q['id'], forecasts={}, rationale='Fixture',
                 model='test/model', panel={'k': 1, 'members': [{'label': 'Fixture model'}]})
            for q in document['questions']]
    (runs / 'finished.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    (old / 'index.html').write_text('<html><head>' + page.block('EEAI', {'synthetic': False}) + '</head></html>')
    with zipfile.ZipFile(old / operator.ARCHIVE, 'w') as archive:
        archive.writestr('history.csv', config.HISTORY.read_bytes())
    original = dict(dashboard='eeai', release=active.name, commit=SHA, frontend_commit=SHA,
                    data_snapshot=site.snapshot(old, (operator.ARCHIVE,)))
    for release_file in (active / 'release.json', old / 'release.json', public / 'release.json'):
        release_file.write_text(json.dumps(original))
    for name in ('index.html', operator.ARCHIVE):
        (public / name).write_bytes((old / name).read_bytes())

    def script(path, body):
        path.write_text('#!' + sys.executable + '\n' + body)
        path.chmod(0o755)

    # Use real production dispatch and build. Freeze the scheduler clock,
    # replace the FRED transport and capture scheduler alerts locally.
    script(code / 'code/production.py', f"""
import datetime, os, sys
sys.path.insert(0, {str(OPS)!r})
import production as p
class Clock(datetime.datetime):
    @classmethod
    def now(cls, tz):
        return cls.fromisoformat(os.environ['FIXTURE_NOW']).astimezone(tz)
p.datetime = Clock
p.Runtime.alert = lambda *args, **kwargs: None
command_result = p.eeai_operator.command_result
def fake_fred(argv, **kwargs):
    if argv[-1] == 'fred':
        route = kwargs['env']
        assert 'FRED_API_KEY' not in route
        assert route.get('HTTPS_PROXY') == 'http://fixture-user:private-value@proxy.invalid:8080'
        return os.environ.get('FIXTURE_FRED', 'missing_key_response'), None
    return command_result(argv, **kwargs)
p.eeai_operator.command_result = fake_fred
p.main()
""")
    script(code / '.venv/bin/python', f"""
import os, sys
from pathlib import Path
if sys.argv[1:] == ['-m', 'eeai', 'refresh']:
    with Path(os.environ['FIXTURE_CALLS']).open('a') as log:
        log.write('upstream\\n')
    if os.environ.get('FIXTURE_UPSTREAM_FAILURE'):
        sys.exit('Fixture FRED access failure')
    baselines = Path(os.environ['EEAI_RESULTS']) / 'baselines'
    baselines.mkdir(parents=True, exist_ok=True)
    (baselines / '{DAY}.csv').write_bytes(Path({str(config.HISTORY)!r}).read_bytes())
    sys.exit(0)
assert sys.argv[1:4] == ['-m', 'eeai', 'build']
os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
""")
    script(bin_dir / 'systemctl', """
import json, os, sys
from pathlib import Path
settings = json.loads(Path(os.environ['FIXTURE_SYSTEMD']).read_text())
if sys.argv[1] == 'show-environment':
    print('LANG=C')
elif sys.argv[-1] == settings['service']:
    for name, value in settings['properties'].items():
        print(f'{name}={value}')
elif sys.argv[-1] == settings['timer']:
    print('LoadState=loaded')
    print('UnitFileState=' + settings['enablement'])
    print('ActiveState=' + settings['activity'])
    print('Triggers=' + settings['service'])
    print('TimersCalendar={ OnCalendar=*-*-* *:*:00 UTC ; next_elapse=Thursday }')
else:
    sys.exit(1)
""")
    publisher = bin_dir / 'ship'
    script(publisher, """
import os, sys
from pathlib import Path
source, public = Path(sys.argv[-1]), Path(os.environ['FIXTURE_PUBLIC'])
with Path(os.environ['FIXTURE_CALLS']).open('a') as log:
    log.write('publish ' + source.name + '\\n')
if os.environ.get('FIXTURE_TRANSFER_FAILURE') and source.name.startswith('job-'):
    sys.exit('Private publisher diagnostic')
for name in ('index.html', 'eeai-data.zip', 'release.json'):
    value = (source / name).read_bytes()
    if os.environ.get('FIXTURE_STALE_ZIP') and source.name.startswith('job-') and name.endswith('.zip'):
        continue
    (public / name).write_bytes(value)
""")
    verifier = bin_dir / 'check'
    script(verifier, """
import hashlib, json, os, sys
from pathlib import Path
public = Path(os.environ['FIXTURE_PUBLIC'])
expected = json.load(sys.stdin)
actual = json.loads((public / 'release.json').read_text())
mode = os.environ.get('FIXTURE_PUBLIC_MODE')
if mode == 'crash':
    sys.exit('Private verification diagnostic')
checks = {'release.json': mode or (
    'verified' if (actual['data_snapshot']['sha256'] == expected['data_snapshot_sha256']
                   and actual['frontend_commit'] == expected['frontend_commit']) else 'stale')}
for name, info in expected['files'].items():
    content = (public / name).read_bytes()
    checks[name] = ('verified' if len(content) == info['size']
                    and hashlib.sha256(content).hexdigest() == info['sha256'] else 'stale')
print(json.dumps(checks))
""")
    settings = dict(root=str(root), dashboard='eeai', path=os.environ['PATH'], socket=str(root / 'site.sock'),
                    scheduler_service='fixture-scheduler.service', scheduler_timer='fixture-scheduler.timer',
                    public_url='https://dashboard.invalid/eeai/', public_publisher=[str(publisher)],
                    public_verifier=[str(verifier)], min_free_bytes=0)
    config_path = config_dir / 'eeai.json'
    config_path.write_text(json.dumps(settings))
    proxy = 'http://fixture-user:private-value@proxy.invalid:8080'
    envfile = config_dir / 'scheduler.env'
    envfile.write_text(f'HTTPS_PROXY="{proxy}"\nDASHBOARD_CONFIG_DIR={config_dir}\n')
    systemd_props = {key: '' for key in operator.UNIT_PROPERTIES}
    systemd_props.update(LoadState='loaded', EnvironmentFiles=f'{envfile} (ignore_errors=no)',
                         MainPID='0', PrivateNetwork='no',
                         ExecStart=f'{{ path={OPS}/dashboardctl ; argv[]={OPS}/dashboardctl tick-all ; pid=0 }}')
    systemd = dict(service=settings['scheduler_service'], timer=settings['scheduler_timer'],
                   activity='active', enablement='enabled', properties=systemd_props)
    systemd_file = tmp_path / 'systemd.json'
    calls = tmp_path / 'calls'
    env = dict(os.environ, DASHBOARD_CONFIG_DIR=str(config_dir), HTTPS_PROXY=proxy, NO_PROXY='',
               FIXTURE_NOW=AT, FIXTURE_PUBLIC=str(public), FIXTURE_SYSTEMD=str(systemd_file), FIXTURE_CALLS=str(calls),
               PATH=str(bin_dir) + os.pathsep + os.environ['PATH'])
    for key in ('https_proxy', 'no_proxy'):
        env.pop(key, None)

    def cli(*args, **overrides):
        systemd_file.write_text(json.dumps(systemd))
        config_path.write_text(json.dumps(settings))
        command = (args if args[:1] == ('tick-all',) else ('eeai', *args))
        return subprocess.run([sys.executable, OPS / 'dashboardctl', *command],
                              env={**env, **overrides}, capture_output=True, text=True, timeout=25)

    return SimpleNamespace(cli=cli, root=root, active=active, old=old, public=public, original=original,
                           code=code, settings=settings, systemd=systemd, envfile=envfile, env=env,
                           enable=lambda: (root / 'jobs-enabled').touch(), calls=calls, results=runs)


@pytest.mark.parametrize('mode,proxy,fred,delivery,rc', [
    ('healthy', 'matched', 'missing_key_response', 'verified', 0),
    ('different_proxy', 'mismatched', 'missing_key_response', 'verified', 1),
    ('bypass', 'mismatched', 'missing_key_response', 'verified', 1),
    ('unreadable_environment', 'unknown', 'unverifiable', 'verified', 1),
    ('connect_denied', 'matched', 'proxy_connect_denied', 'verified', 1),
    ('login_redirect', 'matched', 'missing_key_response', 'login_redirect', 1),
    ('access_denied', 'matched', 'missing_key_response', 'access_denied', 1),
    ('stale', 'matched', 'missing_key_response', 'stale', 1),
    ('crash', 'matched', 'missing_key_response', 'unverifiable', 1),
])
def test_doctor_through_dashboardctl(installed, mode, proxy, fred, delivery, rc):
    installed.enable()
    overrides = {}
    if mode == 'different_proxy':
        overrides['HTTPS_PROXY'] = 'http://different.invalid/'
    elif mode == 'bypass':
        with installed.envfile.open('a') as env:
            env.write('NO_PROXY=.stlouisfed.org\n')
    elif mode == 'unreadable_environment':
        installed.envfile.unlink()
    elif mode == 'connect_denied':
        overrides['FIXTURE_FRED'] = 'proxy_connect_denied'
    elif mode == 'stale':
        replacement = {**installed.original, 'frontend_commit': 'b' * 40}
        (installed.public / 'release.json').write_text(json.dumps(replacement))
    elif mode != 'healthy':
        overrides['FIXTURE_PUBLIC_MODE'] = mode
    before = set(installed.root.rglob('*'))
    result = installed.cli('doctor', **overrides)
    assert result.returncode == rc, result.stderr
    out = json.loads(result.stdout)
    assert out['hostname'] == socket.gethostname()
    assert out['project'] == 'eeai'
    assert out['release']['frontend_commit'] == SHA
    assert out['scheduler']['command'][-1] == 'tick-all'
    assert out['scheduler']['environment_source'] == (
        'systemd EnvironmentFile missing' if mode == 'unreadable_environment' else 'systemd configuration')
    assert out['https_proxy_settings'] == proxy
    assert out['fred']['result'] == fred
    if mode == 'bypass':
        assert out['fred']['route'] == 'direct'
    assert out['public_delivery']['result'] == delivery
    assert out['completed_runs']['result'] == 'run_files_present'
    assert 'private-value' not in result.stdout + result.stderr
    assert 'Private verification diagnostic' not in result.stdout + result.stderr
    assert set(installed.root.rglob('*')) == before
    assert not installed.calls.exists()


def test_status_distinguishes_legacy_publication_unverified_receipt_and_disabled_job(installed):
    runs = installed.root / 'runs'
    runs.mkdir()
    (runs / 'legacy.json').write_text(json.dumps({'job': JOB['id'], 'status': 'succeeded', 'started': AT}))
    report = json.loads(installed.cli('status').stdout)
    assert report['frontend_commit'] == SHA
    assert report['published_baseline'] == {'source': 'unknown', 'as_of': None}
    assert report['latest_verified_refresh'] is None
    assert report['economic_schedule']['state'] == 'disabled'
    assert report['economic_schedule']['next_scheduled_utc'] is None
    installed.enable()
    installed.systemd['activity'] = 'inactive'
    assert json.loads(installed.cli('status').stdout)['economic_schedule']['state'] == 'disabled'
    installed.systemd['activity'] = 'active'
    report = json.loads(installed.cli('status').stdout)
    assert report['economic_schedule']['next_scheduled_utc'] == '2026-11-20T15:15:00+00:00'
    (installed.old / 'release.json').unlink()
    (installed.active / 'release.json').unlink()
    report = json.loads(installed.cli('status').stdout)
    assert report['release'] is None
    assert report['frontend_commit'] is None


def test_public_verifier_failure_reports_unverified_restoration(installed):
    result = installed.cli('refresh', '--verify', '--run-id', 'unavailable', FIXTURE_PUBLIC_MODE='crash')
    assert result.returncode == 1, result.stderr + result.stdout
    receipt = json.loads(result.stdout)
    assert receipt['stage'] == 'verify_public'
    assert receipt['public_verification']['result'] == 'unverifiable'
    assert receipt['recovery'] == 'republished_unverified'
    assert (installed.active / 'site').resolve() == installed.old
    assert json.loads((installed.public / 'release.json').read_text()) == installed.original


def test_manual_and_scheduled_refresh_verify_the_real_builder(installed):
    result = installed.cli('refresh', '--verify', '--run-id', 'manual')
    assert result.returncode == 0, result.stderr + result.stdout
    receipt = json.loads(result.stdout)
    assert receipt['status'] == 'succeeded'
    assert receipt['stage'] == 'verified'
    assert receipt['baseline'] == BASELINE
    assert receipt['public_verification']['checks'] == dict.fromkeys(
        ('release.json', 'index.html', operator.ARCHIVE), 'verified')
    assert installed.calls.read_text().splitlines() == ['upstream', 'publish job-manual']
    installed.cli('refresh', '--verify', '--run-id', 'manual').check_returncode()
    assert installed.calls.read_text().splitlines() == ['upstream', 'publish job-manual']
    report = json.loads(installed.cli('status').stdout)
    assert report['published_baseline'] == BASELINE
    assert report['latest_verified_refresh']['verified_at'] == receipt['verified_at']
    assert report['latest_refresh_failure'] is None
    assert report['release']['frontend_commit'] == SHA
    assert report['release']['data_snapshot']['sha256'] == receipt['data_snapshot_sha256']
    assert json.loads((installed.active / 'release.json').read_text()) == report['release']
    assert (installed.active / 'site/index.html').read_bytes() == (installed.public / 'index.html').read_bytes()
    with zipfile.ZipFile(installed.public / operator.ARCHIVE) as archive:
        assert json.loads(archive.read('baseline.json')) == BASELINE
        assert archive.read('history.csv') == config.HISTORY.read_bytes()
    installed.enable()
    os.utime(installed.root / 'jobs-enabled', (0, 0))
    scheduled = installed.cli('tick-all')
    assert scheduled.returncode == 0, scheduled.stderr
    assert installed.calls.read_text().splitlines()[-2:] == ['upstream', 'publish job-eeai-economic-data-20261119']
    scheduled = json.loads((installed.root / 'runs/eeai-economic-data-20261119.json').read_text())
    assert scheduled['status'] == 'succeeded' and scheduled['stage'] == 'verified'


@pytest.mark.parametrize('mode,stage', [('upstream', 'upstream'), ('build', 'build'),
                                        ('transfer', 'transfer'), ('stale_zip', 'verify_public')])
def test_refresh_failure_keeps_selection_and_records_recovery(installed, mode, stage):
    overrides = {}
    if mode == 'upstream':
        overrides['FIXTURE_UPSTREAM_FAILURE'] = '1'
    if mode == 'build':
        (installed.results / 'finished.jsonl').unlink()
    if mode == 'transfer':
        overrides['FIXTURE_TRANSFER_FAILURE'] = '1'
    if mode == 'stale_zip':
        overrides['FIXTURE_STALE_ZIP'] = '1'
    result = installed.cli('refresh', '--verify', '--run-id', 'broken', **overrides)
    assert result.returncode == 1, result.stderr + result.stdout
    receipt = json.loads(result.stdout)
    assert receipt['status'] == 'failed' and receipt['stage'] == stage
    assert receipt.get('verified_at') is None
    assert (installed.active / 'site').resolve() == installed.old
    assert json.loads((installed.public / 'release.json').read_text()) == installed.original
    report = json.loads(installed.cli('status').stdout)
    assert report['latest_verified_refresh'] is None
    assert report['latest_refresh_failure']['key'] == 'broken'
    if stage in ('transfer', 'verify_public'):
        assert receipt['recovery'] == 'restored'
        assert installed.calls.read_text().splitlines()[-2:] == ['publish job-broken', 'publish original']
        if stage == 'verify_public':
            assert receipt['public_verification']['checks'][operator.ARCHIVE] == 'stale'
        retry = installed.cli('refresh', '--verify', '--retry', 'broken', '--run-id', 'fixed')
        assert retry.returncode == 0, retry.stderr + retry.stdout
        assert json.loads(retry.stdout)['retry_of'] == 'broken'
        assert installed.calls.read_text().splitlines() == ['upstream', 'publish job-broken', 'publish original', 'publish job-fixed']
        installed.cli('republish').check_returncode()
        assert installed.calls.read_text().splitlines()[-1] == 'publish job-fixed'
    else:
        assert installed.calls.read_text().splitlines() == ['upstream']
    assert 'Private publisher diagnostic' not in result.stderr + result.stdout


@pytest.mark.parametrize('error,state', [
    (HTTPError(operator.FRED_URL, 400, '', {}, io.BytesIO(
        b'{"error_code":400,"error_message":"Bad Request. The variable api_key is not set."}')), 'missing_key_response'),
    (HTTPError(operator.FRED_URL, 403, '', {}, io.BytesIO(b'{"message":"denied"}')), 'unverifiable'),
    (URLError(OSError('Tunnel connection failed: 403 Forbidden')), 'proxy_connect_denied'),
    (URLError(socket.gaierror('Name or service not known')), 'dns'),
    (URLError(ssl.SSLError('certificate verify failed')), 'tls'),
    (TimeoutError(), 'timeout'),
])
def test_keyless_fred_probe_classifies_transport_and_application_response(monkeypatch, error, state):
    class Opener:
        def open(self, url, **kwargs):
            assert url.startswith('https://api.stlouisfed.org/fred/series/observations?')
            assert 'api_key' not in url
            raise error
    monkeypatch.setattr(operator, 'build_opener', lambda *handlers: Opener())
    assert operator.fred_probe() == state


def test_direct_public_probe_distinguishes_login_stale_and_bin_content(monkeypatch):
    base = 'https://dashboard.invalid/'
    expected = dict(url=base, frontend_commit=SHA, data_snapshot_sha256='b' * 64,
                    files={'index.html': dict(sha256=hashlib.sha256(b'abc').hexdigest(), size=3),
                           operator.ARCHIVE: dict(sha256=hashlib.sha256(b'xyz').hexdigest(), size=3)})

    class Opener:
        def open(self, request, **kwargs):
            if request.full_url.endswith('release.json'):
                raise HTTPError(request.full_url, 302, '', {'Location': '/sign-in'}, io.BytesIO())
            payload = io.BytesIO(b'abc' if request.full_url == base else b'xyzmore')
            payload.status = 200
            return payload

    monkeypatch.setattr(operator, 'build_opener', lambda *handlers: Opener())
    assert operator.public_probe(expected) == {'release.json': 'login_redirect', 'index.html': 'verified',
                                               operator.ARCHIVE: 'stale'}


@pytest.mark.parametrize('args,active,valid', [
    ('airo worker --lane refresh', 'active', True),
    ('airo worker --lane forecast', 'active', False),
    ('airo worker --lane refresh', 'failed', False),
])
def test_doctor_uses_actual_refresh_worker_route(tmp_path, monkeypatch, args, active, valid):
    worker = dict.fromkeys(operator.UNIT_PROPERTIES, '')
    worker.update(LoadState='loaded', ActiveState=active, UnitFileState='enabled',
                  ExecStart=f'{{ path=/usr/bin/python3 ; argv[]=/usr/bin/python3 /bin/dashboardctl {args} ; pid=0 }}')
    monkeypatch.setattr(operator, 'unit_properties', lambda *_: worker)
    monkeypatch.setattr(operator, 'scheduler_environment',
                        lambda unit: ({'DASHBOARD_CONFIG_DIR': str(tmp_path)}, 'service process'))
    cfg = tmp_path / 'eeai.json'
    cfg.touch()
    info, route, _ = operator.refresh_worker({})
    assert bool(info['active'] and operator.installation_matches(route, cfg, 'eeai')) == valid


def test_two_workers_replay_november_22_while_forecast_process_is_running(installed, tmp_path):
    """Exercise the dispatcher, SQLite claims, child processes and EEAI publication offline."""
    directory = Path(installed.env['DASHBOARD_CONFIG_DIR'])
    root = tmp_path / 'primary'
    active = root / 'releases' / installed.active.name
    code = active / 'code'
    fb = code / 'submissions/forecastbench/scripts'
    for path in [fb, code / 'code', code / 'dashboards/airo/code', code / 'packages/ops',
                 code / '.venv/bin', active / 'site', root / 'home/.config/fri-forecaster']:
        path.mkdir(parents=True, exist_ok=True)
    # The live worker re-execs when its installed scheduler differs from current.
    # Give this fixture a real installed module and retain its offline transports.
    for module in OPS.glob('*.py'):
        shutil.copy2(module, code / 'packages/ops' / module.name)
    (code / 'packages/dashboard').symlink_to(ROOT / 'packages/dashboard')
    shim = (installed.code / 'code/production.py').read_text()
    (code / 'code/production.py').write_text(shim.replace(repr(str(OPS)), repr(str(code / 'packages/ops'))))
    (active / 'release.json').write_text(json.dumps({'dashboard': 'airo', 'release': active.name}))
    (root / 'current').symlink_to(active)
    (root / 'home/.config/fri-forecaster/round.env').write_text('')
    (code / '.venv/bin/python').write_text(
        '#!/bin/sh\ncase "$*" in *forecastbench.status*) exit 0;; *recent_news.py*poll) '
        'echo "news" >> "$FIXTURE_CALLS";; *) exit 19;; esac\n')
    (code / '.venv/bin/python').chmod(0o755)
    (fb / 'fb_cron.sh').write_text(
        'set -eu\necho forecast >> "$FIXTURE_CALLS"\n'
        'for ((i=0; i<600; i++)); do [[ -e "$FINISH_ROUND" ]] && exit 0; sleep 0.05; done\nexit 1\n')
    primary = directory / 'airo.json'
    primary.write_text(json.dumps(dict(root=str(root), path=os.environ['PATH'],
                                      socket=str(root / 'site.sock'), min_free_bytes=0)))
    installed.settings['panel_runtime_config'] = str(primary)
    installed.cli('status').check_returncode()  # write the selected private config
    due = '2026-11-22'
    jobs = [dict(id='forecastbench-round', kind='forecastbench', at=due + 'T00:05:00Z', due=due),
            dict(id='news', kind='news-poll', daily_utc='11:45'), JOB]
    for package in [code, installed.code]:
        (package / 'packages/ops/jobs.json').write_text(json.dumps(jobs))
    for path in [root / 'jobs-enabled', installed.root / 'jobs-enabled', root / 'job-queue-enabled']:
        path.touch()
        os.utime(path, (0, 0))
    for pointer in [root / 'current', installed.root / 'current']:
        # The simulated scheduler only admits schedules active at the test time.
        epoch = 1795305600  # 2026-11-22 00:00 UTC
        os.utime(pointer, (epoch, epoch), follow_symlinks=False)
    finish = tmp_path / 'finish-round'
    def command(clock, *args, background=False):
        argv = [sys.executable, OPS / 'dashboardctl', *args]
        env = dict(installed.env, FIXTURE_NOW=f'{due}T{clock}:00Z', FINISH_ROUND=str(finish))
        if background:
            return subprocess.Popen(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return subprocess.run(argv, env=env, capture_output=True, text=True, check=True, timeout=12)

    command('00:05', 'tick-all')
    paid = command('00:05', 'airo', 'worker', '--lane', 'forecast', '--once', background=True)
    try:
        for _ in range(200):
            if installed.calls.exists() or paid.poll() is not None:
                break
            time.sleep(.025)
        assert paid.poll() is None and installed.calls.read_text().splitlines() == ['forecast']
        for clock in ('11:45', '15:15'):
            command(clock, 'tick-all')
            command(clock, 'tick-all')  # another scheduler process discovers the same minute
            command(clock, 'airo', 'worker', '--lane', 'refresh', '--once')
            assert paid.poll() is None
        assert installed.calls.read_text().splitlines() == [
            'forecast', 'news', 'upstream', 'publish job-eeai-economic-data-20261122']
        receipt = json.loads((installed.root / 'runs/eeai-economic-data-20261122.json').read_text())
        assert receipt['stage'] == 'verified'
    finally:
        finish.touch()
        try:
            _, err = paid.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            paid.kill()
            paid.communicate()
            raise
    assert paid.returncode == 0, err
    report = json.loads(command('15:15', 'airo', 'status').stdout)
    assert {row['status'] for row in report['scheduled_runs']} == {'succeeded'}
