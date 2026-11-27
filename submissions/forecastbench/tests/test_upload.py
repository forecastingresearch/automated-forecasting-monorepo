"""Submission validation, non-overwriting retries and alerts; no cloud calls."""
import base64
import contextlib
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import textwrap
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import forecastbench as fb
from forecastbench import names, progress, status, upload


DUE = '2026-11-22'
NOW = datetime(2026, 11, 22, 8, tzinfo=timezone.utc)
ACCOUNT = 'uploader@example-project.iam.gserviceaccount.com'
PREFIX = 'gs://example-bucket/team/binary'
QSET = {'forecast_due_date': DUE, 'question_set': DUE + '-llm.json', 'questions': [
    {'source': 'metaculus', 'id': 'm', 'resolution_dates': 'N/A'},
    {'source': 'fred', 'id': 'd', 'resolution_dates': ['2026-12-01', '2026-12-02']},
]}


class FakeStorage:
    def __init__(self, account):
        self.objects = {}
        self.writes = []
        self.fail_after_write = False

    def request(self, bucket, name, data=None):
        key = (bucket, name)
        if data is None:
            return dict(self.objects[key])
        if key in self.objects:
            raise HTTPError('fake', 412, 'already exists', {}, None)
        self.writes.append(key)
        self.objects[key] = {'bucket': bucket, 'name': name,
                             'md5Hash': base64.b64encode(hashlib.md5(data).digest()).decode(),
                             'size': str(len(data)), 'generation': '1',
                             'timeCreated': NOW.isoformat()}
        if self.fail_after_write:
            raise TimeoutError('lost upload response')
        return dict(self.objects[key])


class UploadTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / DUE
        self.root.mkdir()
        config = patch.object(upload, 'config_dir', return_value=Path(self.temp.name) / 'private')
        config.start()
        self.addCleanup(config.stop)
        (self.root / 'question_set.json').write_text(json.dumps(QSET))
        self.reg = names.load(Path(__file__).parents[1] / 'examples/names.example.json')
        self.reg['conditions'] = {'solo': self.reg['conditions']['solo']}
        entry = self.reg['names']['solo-oak']
        entry['harness']['pi'] = fb.harness.PINNED_PI_VERSION
        entry['harness']['prompt_version'] = names.prompt_version(entry)
        entry['fingerprint'] = names.fingerprint(entry)
        specs = names.member_specs(self.reg, 'solo')
        member = entry['members'][0]
        self.member_path = Path(fb.member_dir(str(self.root), member['pi_model'],
                                            member['options']['thinking'], 'research'))
        self.member_path.mkdir(parents=True)
        (self.member_path / 'manifest.json').write_text('{}')
        results = [{'id': q['id'], 'source': q['source'], 'wanted': fb.dates_of(q),
                    'probabilities': {d: 0.4 for d in fb.dates_of(q)}} for q in QSET['questions']]
        (self.member_path / 'results.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in results))
        self.build_args = ['build', '--root', str(self.root), '--member', specs[0],
                           '--org', 'Example Team', '--name', 'solo-oak', '--set-number', '1']
        self.build()
        self.path = self.root / f'{DUE}.example-team.1.json'
        self.storage = FakeStorage(ACCOUNT)
        self.clock = patch.object(upload, 'utcnow', return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def build(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return fb.main(self.build_args)

    def run_upload(self, set_number=None):
        return upload.upload(self.root, self.reg, 'Example Team', None, PREFIX, ACCOUNT,
                             storage_factory=lambda account: self.storage, set_number=set_number)

    def rewrite(self, fs):
        self.path.write_text(json.dumps(fs))
        prov_path = Path(str(self.path) + '.provenance.json')
        prov = json.loads(prov_path.read_text())
        prov['submission_sha256'] = hashlib.sha256(self.path.read_bytes()).hexdigest()
        prov_path.write_text(json.dumps(prov))

    def test_uploads_only_registered_sets_and_records_verified_receipt(self):
        (self.root / 'not-a-submission.json').write_text('{}')
        result = self.run_upload()
        self.assertEqual(result['status'], 'uploaded')
        self.assertEqual(len(self.storage.writes), 1)
        self.assertEqual(result, json.loads((self.root / 'upload-receipt.json').read_text()))
        self.assertEqual(result['objects'][0]['name'], f'team/binary/{DUE}/{self.path.name}')

    def test_upload_counts_only_open_questions(self):
        questions = [dict(QSET['questions'][0], status='resolved'), QSET['questions'][1]]
        (self.root / 'question_set.json').write_text(json.dumps(dict(QSET, questions=questions)))
        self.assertEqual(self.build(), 0)
        self.assertEqual({r['id'] for r in json.loads(self.path.read_text())['forecasts']}, {'d'})
        self.assertEqual(self.run_upload()['status'], 'uploaded')

    def test_noon_checkpoint_checks_market_and_dataset_completion_separately(self):
        self.assertEqual(progress.behind_schedule(self.root, self.reg), [])
        log = self.member_path / 'results.jsonl'
        log.write_text(log.read_text().splitlines()[0] + '\n')
        self.assertEqual(progress.behind_schedule(self.root, self.reg),
                         [f'{self.member_path.name}: dataset 0/1'])

    def test_selected_upload_preserves_number_and_partial_receipt(self):
        self.reg['conditions']['second'] = {'current': 'second-oak'}
        self.reg['names']['second-oak'] = dict(self.reg['names']['solo-oak'], condition='second')
        with self.assertRaises(FileNotFoundError):
            self.run_upload()
        self.assertFalse(self.storage.writes)
        self.assertEqual(self.run_upload(1)['status'], 'uploading')
        self.build_args[self.build_args.index('--name') + 1] = 'second-oak'
        self.build_args[-1] = '2'
        self.assertEqual(self.build(), 0)
        receipt = self.run_upload(2)
        self.assertEqual(receipt['status'], 'uploaded')
        self.assertEqual([obj['name'].rsplit('.', 2)[-2] for obj in receipt['objects']], ['1', '2'])
        self.assertEqual(self.run_upload(1)['status'], 'uploaded')
        self.assertEqual(len(self.storage.writes), 2)

    def test_median_registration_requires_median_build(self):
        entry = self.reg['names']['solo-oak']
        entry['aggregate'] = 'median'
        entry['fingerprint'] = names.fingerprint(entry)
        with self.assertRaisesRegex(ValueError, 'aggregation does not match'):
            self.run_upload()
        self.build_args.extend(['--aggregate', 'median'])
        self.assertEqual(self.build(), 0)
        self.assertEqual(self.run_upload()['status'], 'uploaded')

    def test_upload_checks_registered_search_backend(self):
        entry = self.reg['names']['solo-oak']
        for search in ('exa', 'keenable'):
            with self.subTest(search=search):
                entry['members'][0]['options']['search_backend'] = search
                entry['fingerprint'] = names.fingerprint(entry)
                with self.assertRaisesRegex(ValueError, 'members do not match'):
                    upload.submissions(self.root, self.reg, 'Example Team', None)
                spec, = names.member_specs(self.reg, 'solo')
                dest = Path(fb.member_dir_for_spec(self.root, spec))
                self.member_path.rename(dest)
                self.member_path = dest
                self.build_args[self.build_args.index('--member') + 1] = spec
                self.assertEqual(self.build(), 0)
                _, files = upload.submissions(self.root, self.reg, 'Example Team', None)
                self.assertEqual(len(files), 1)

    def test_retry_recovers_from_lost_response_without_overwriting(self):
        self.storage.fail_after_write = True
        with self.assertRaises(TimeoutError):
            self.run_upload()
        self.storage.fail_after_write = False
        self.assertEqual(self.run_upload()['status'], 'uploaded')
        self.assertEqual(len(self.storage.writes), 1)

    def test_existing_different_remote_object_fails(self):
        self.run_upload()
        next(iter(self.storage.objects.values()))['md5Hash'] = 'different'
        with self.assertRaisesRegex(ValueError, 'could not be verified'):
            self.run_upload()
        self.assertEqual(len(self.storage.writes), 1)

    def test_changed_file_or_question_set_refuses_before_cloud_write(self):
        self.path.write_text(self.path.read_text() + ' ')
        with self.assertRaisesRegex(ValueError, 'stale build provenance'):
            self.run_upload()
        self.assertFalse(self.storage.writes)
        self.build()
        (self.root / 'question_set.json').write_text(json.dumps(QSET) + ' ')
        with self.assertRaisesRegex(ValueError, 'stale build provenance'):
            self.run_upload()

    def test_incomplete_dataset_question_and_invalid_probabilities_refused(self):
        fs = json.loads(self.path.read_text())
        fs['forecasts'].pop()
        self.rewrite(fs)
        with self.assertRaisesRegex(ValueError, 'below 95%'):
            self.run_upload()
        fs['forecasts'][0]['forecast'] = float('nan')
        self.rewrite(fs)
        with self.assertRaisesRegex(ValueError, 'invalid forecasts'):
            self.run_upload()
        self.assertFalse(self.storage.writes)

    def test_complete_aggregate_with_short_member_refused(self):
        prov_path = Path(str(self.path) + '.provenance.json')
        prov = json.loads(prov_path.read_text())
        prov['member_coverage'][self.member_path.name]['dataset'] = [0, 1]
        prov_path.write_text(json.dumps(prov))
        with self.assertRaisesRegex(ValueError, 'member is below 95%'):
            self.run_upload()
        self.assertFalse(self.storage.writes)

    def test_rehearsals_and_outside_utc_date_refused(self):
        for time in (datetime(2026, 11, 21, 23, 59, tzinfo=timezone.utc),
                     datetime(2026, 11, 23, tzinfo=timezone.utc)):
            with patch.object(upload, 'utcnow', return_value=time):
                with self.assertRaisesRegex(ValueError, 'UTC date'):
                    self.run_upload()
        renamed = self.root.with_name(DUE + '-rehearsal')
        self.root.rename(renamed)
        self.root = renamed
        with self.assertRaisesRegex(ValueError, 'rehearsal'):
            self.run_upload()
        self.assertFalse(self.storage.writes)

    def test_expired_auth_pages_and_returns_failure(self):
        with patch.object(upload.names, 'load', return_value=self.reg), \
                patch.object(upload, 'upload', side_effect=RuntimeError('authentication failed')), \
                patch.object(upload.alert, 'send') as send:
            self.assertEqual(upload.main(['--root', str(self.root), '--set-number', '1']), 1)
        self.assertEqual(send.call_args.args[:2], ('forecastbench', 'upload FAILED'))
        self.assertIn(f'--root {self.root} --set-number 1', send.call_args.args[2])
        self.assertEqual(send.call_args.kwargs['severity'], 'page')

    def record_plan(self):
        status.record(self.root, 'round', pid=0, sets=[
            dict(number=1, name='solo', filename=self.path.name,
                 members=names.member_specs(self.reg, 'solo'))])

    def test_overdue_alert_deduplicates_and_retries_undelivered_page(self):
        self.record_plan()
        with patch.object(status, 'now', return_value=NOW):
            status.record(self.root, 'validated', number=1, attempt=1)
        with patch.object(status.alert, 'send', side_effect=[0, 1]) as send:
            with patch.object(status, 'now', return_value=NOW + timedelta(seconds=599)):
                status.check_pending(self.root)
            send.assert_not_called()
            with patch.object(status, 'now', return_value=NOW + timedelta(minutes=10)):
                status.check_pending(self.root)
                status.check_pending(self.root)
                status.page_once(self.root, 1, 'upload FAILED', 'late failure')
                status.check_pending(self.root)
            self.assertEqual(send.call_count, 2)
            self.assertIn('--set-number 1', send.call_args.args[2])

    def test_delivered_failure_page_suppresses_watchdog(self):
        self.record_plan()
        with patch.object(status, 'now', return_value=NOW):
            status.record(self.root, 'validated', number=1, attempt=1)
        with patch.object(status, 'now', return_value=NOW + timedelta(minutes=11)), \
                patch.object(upload.names, 'load', return_value=self.reg), \
                patch.object(upload, 'upload', side_effect=TimeoutError()), \
                patch.object(status.alert, 'send', return_value=1) as send:
            self.assertEqual(upload.main(['--root', str(self.root), '--set-number', '1']), 1)
            status.check_pending(self.root)
            send.assert_called_once()
            self.assertIn('upload failed', status.report(self.root, history_lines=True)[0])

    def test_status_checks_receipt_content_destination_and_recovery(self):
        self.record_plan()
        self.run_upload(1)
        staged = self.root / 'partial-upload-test' / DUE
        staged.mkdir(parents=True)
        (self.root / 'upload-receipt.json').rename(staged / 'upload-receipt.json')
        with patch.object(upload, 'settings', return_value=(PREFIX, ACCOUNT)):
            self.assertTrue(status.report(self.root)[1])
            self.path.write_bytes(b'changed')
            self.assertFalse(status.report(self.root)[1])
        self.build()
        with patch.object(upload, 'settings', return_value=('gs://wrong-bucket/team/binary', ACCOUNT)):
            self.assertFalse(status.report(self.root)[1])

    def test_status_displays_member_category_and_latest_success(self):
        self.record_plan()
        path = self.member_path / 'results.jsonl'
        market = json.loads(path.read_text().splitlines()[0])
        market['completed_at'] = NOW.isoformat()
        path.write_text(json.dumps(market) + '\n{"torn"')
        text, complete = status.report(self.root)
        self.assertFalse(complete)
        self.assertIn('dataset 0/1 required', text)
        self.assertIn('workers 0', text)
        self.assertIn(NOW.isoformat(), text)

    def test_personal_account_cannot_be_used_accidentally(self):
        with self.assertRaisesRegex(ValueError, 'dedicated service-account'):
            upload.Storage('person@example.org')

    def test_private_key_authentication_does_not_use_personal_gcloud_login(self):
        private = upload.config_dir()
        private.mkdir()
        (private / 'key.json').write_text('{}')
        credentials = unittest.mock.Mock(service_account_email=ACCOUNT, token='token')
        with patch('google.oauth2.service_account.Credentials.from_service_account_file', return_value=credentials), \
                patch('google.auth.transport.requests.Request'), patch.object(upload.subprocess, 'run') as gcloud:
            self.assertEqual(upload.Storage(ACCOUNT).token, 'token')
            credentials.refresh.assert_called_once()
            gcloud.assert_not_called()
            credentials.service_account_email = 'wrong@other.iam.gserviceaccount.com'
            with self.assertRaisesRegex(ValueError, 'does not belong'):
                upload.Storage(ACCOUNT)

    def test_transport_pins_identity_and_forbids_overwrite(self):
        token = unittest.mock.Mock(returncode=0, stdout='secret-token\n')
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{}'
        with patch.object(upload.subprocess, 'run', return_value=token) as auth, \
                patch.object(upload.urllib.request, 'urlopen', return_value=response) as request:
            client = upload.Storage(ACCOUNT)
            client.request('bucket', 'team/round/file.json', b'{}')
        self.assertEqual(auth.call_args.args[0], ['gcloud', 'auth', 'print-access-token', ACCOUNT, '--quiet'])
        req = request.call_args.args[0]
        self.assertIn('ifGenerationMatch=0', req.full_url)
        self.assertIn('name=team%2Fround%2Ffile.json', req.full_url)
        self.assertEqual(req.get_header('Authorization'), 'Bearer secret-token')
        self.assertEqual(req.data, b'{}')


class CronTest(unittest.TestCase):
    def test_cron_starts_delivery_and_propagates_failures(self):
        source = Path(__file__).parents[1] / 'scripts'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scripts = root / 'scripts'
            scripts.mkdir()
            for name in ('fb_cron.sh', 'fb_round.sh'):
                shutil.copy2(source / name, scripts / name)
            def executable(name, body):
                path = root / name
                path.write_text('#!/bin/bash\n' + textwrap.dedent(body))
                path.chmod(0o700)
                return path

            fake_py = executable('python', """
                printf '%s\\n' "$*" >> "$FAKE_CALLS"
                case "$2/$3" in
                  forecastbench.names/conditions)
                    echo submitted
                    echo second
                    if [[ "${4:-}" == --all ]]; then echo optional; fi ;;
                  forecastbench.round_run/--root)
                    if [[ "$FAKE_LATE" == 1 ]]; then sleep 0.1; fi
                    if [[ "$FAKE_ROUND_RC" == 0 ]]; then
                      touch "$4/logs/first-upload-confirmed" "$4/logs/upload-confirmed"
                    fi
                    exit "$FAKE_ROUND_RC" ;;
                esac
                exit 0
            """)
            executable('curl', 'exit 0\n')
            executable('date', """
                case "$*" in
                  '-u +%F') echo 2026-11-22 ;;
                  '-u +%s') echo "$FAKE_LATE" ;;
                  '-u -d 2026-11-22 12:00 UTC +%s'|'-u -d 2026-11-22 20:00 UTC +%s') echo 1 ;;
                  *) /usr/bin/date "$@" ;;
                esac
            """)
            conf = root / 'round.env'
            conf.write_text('panel_members() { echo "test member"; }\n')
            calls_path = root / 'calls'
            env = dict(os.environ, FORECASTER_ROUND_ENV=str(conf), FAKE_CALLS=str(calls_path),
                       PATH=f"{root}:{os.environ['PATH']}", PY=str(fake_py), ROUNDS_DIR=str(root / 'rounds'),
                       FB_ORG='Example Team', CALLS='12', SAMPLE='', PI_CODING_AGENT_DIR=str(root / 'pi'))
            for expected, late in ((0, 0), (4, 0), (1, 0), (0, 1)):
                with self.subTest(expected=expected, late=late):
                    calls_path.write_text('')
                    result = subprocess.run(
                        ['bash', str(scripts / 'fb_cron.sh'), DUE],
                        env=dict(env, FAKE_ROUND_RC=str(expected), FAKE_LATE=str(late)),
                        capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, expected, result.stderr)
                    calls = calls_path.read_text()
                    self.assertIn('forecastbench.round_run', calls)
                    self.assertIn(f'--due {DUE} --calls 12 --upload', calls)
                    self.assertEqual('run FAILED' in calls, expected == 1)
                    if late:
                        self.assertLess(calls.index('forecastbench.progress'), calls.index('upload still pending'))


if __name__ == '__main__':
    unittest.main()
