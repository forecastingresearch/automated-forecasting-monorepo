"""Run and deliver a prepared ForecastBench round within one worker budget."""
import argparse
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys

from forecastbench import file_org, names, status
from fri_forecaster import alert


@dataclass(frozen=True)
class Submission:
    number: int
    name: str
    organization: str
    aggregate: str
    members: tuple[str, ...]


def member_slots(members, calls):
    """Divide a condition's budget evenly, or give each member one slot."""
    if members:
        base, extra = divmod(calls, len(members))
        for index, member in enumerate(members):
            yield member, max(1, base + int(index < extra))


def invoke(module, *args, **kwargs):
    return subprocess.run([sys.executable, '-m', module, *map(str, args)], **kwargs).returncode


class RoundRun:
    def __init__(self, args):
        self.args = args
        self.logs = args.root / 'logs'
        self.round_log = self.logs / 'round.log'
        self.uploaded = 0
        self.member_attempts = Counter()

    def log(self, message):
        line = f'{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} {message}'
        with self.round_log.open('a') as log:
            print(line, file=log)
        print(line, flush=True)

    def run_member(self, spec, workers):
        head, mode, *search = spec.split(',')
        model, thinking = head.split('@', 1)
        cmd = ['run', '--root', self.args.root, '--question-set', f'{self.args.due}-llm.json',
               '--model', model, '--thinking', thinking, '--workers', workers]
        if mode == 'research':
            cmd.append('--research')
        elif mode == 'noresearch':
            cmd.append('--no-research')
        elif mode == 'airo-none':
            cmd.append('--baseline')
        elif mode.startswith('airo-'):
            cmd.extend(['--airo', mode.removeprefix('airo-')])
        if search:
            cmd.extend(['--search', search[0]])
        if self.args.sample is not None:
            cmd.extend(['--sample', self.args.sample])
        if self.args.timeout is not None:
            cmd.extend(['--timeout', self.args.timeout])
        filename = '-'.join([model, mode, *search]).replace('/', '_') + '.log'
        with (self.logs / filename).open('a') as log:
            rc = subprocess.run([sys.executable, '-u', '-m', 'forecastbench', *map(str, cmd)],
                                stdout=log, stderr=subprocess.STDOUT).returncode
        self.log(f'{spec} exited {rc} (0 = complete, 1 = short of 95%, 2 = its key was refused)')
        status.record(self.args.root, 'member finished', spec=spec, attempt=self.member_attempts[spec], rc=rc)
        if rc == 2:
            self.page_refused_key(model.split('/', 1)[0])

    def page_refused_key(self, provider):
        # Several members may discover the same refused key in parallel.
        try:
            (self.logs / f'key-refused-{provider}').touch(exist_ok=False)
        except FileExistsError:
            return
        tag = f' {self.args.tag}' if self.args.tag else ''
        keys_file = os.environ['FORECASTER_ENV_FILE']
        alert.send('forecastbench', 'run FAILED',
                   f"{self.args.due}: {provider}'s API key was refused. Fix the keys file ({keys_file}) "
                   f'and rerun scripts/fb_round.sh {self.args.due}{tag}. Completed forecasts are kept.',
                   log=self.round_log)
        (self.logs / 'paged').touch()

    def build(self, submission, attempt):
        fields = [item for spec in submission.members for item in ('--member', spec)]
        with (self.logs / f'build-{submission.number}.log').open('w') as log:
            rc = invoke('forecastbench', 'build', '--aggregate', submission.aggregate,
                        '--root', self.args.root, '--set-number', submission.number,
                        '--name', submission.name, '--org', submission.organization, *fields,
                        stdout=log, stderr=subprocess.STDOUT)
        status.record(self.args.root, 'validated' if rc == 0 else 'validation failed',
                      number=submission.number, attempt=attempt, rc=rc)
        self.log(f'set {submission.number} ({submission.name}, as {submission.organization}): '
                 f'pass {attempt}, build exited {rc} (0 = ready to upload)')
        return rc == 0

    def upload(self, submission, total):
        if invoke('forecastbench.upload', '--root', self.args.root, '--set-number', submission.number):
            return False
        self.log(f'set {submission.number}: upload confirmed')
        if submission.number == 1:
            (self.logs / 'first-upload-confirmed').touch()
        # uploads run on a single thread and share one on-disk receipt.
        self.uploaded += 1
        if self.uploaded == total:
            (self.logs / 'upload-confirmed').touch()
        return True

    def start_members(self, pool, queue, active):
        free = self.args.calls - sum(slots for _, slots in active.values())
        for spec, desired in queue:
            if free == 0:
                return
            if spec in active:
                continue
            slots = min(desired, free)
            self.log(f'starting {spec} with {slots} worker(s)')
            self.member_attempts[spec] += 1
            status.record(self.args.root, 'member started', spec=spec,
                          attempt=self.member_attempts[spec], workers=slots)
            active[spec] = (pool.submit(self.run_member, spec, slots), slots)
            free -= slots

    @staticmethod
    def finish_members(active):
        futures = {future: spec for spec, (future, _) in active.items()}
        done, _ = wait(futures, return_when=FIRST_COMPLETED)
        for future in done:
            future.result()
            spec = futures[future]
            del active[spec]
            yield spec

    def run_submissions(self, pool, uploader, submissions):
        # Each set can request one retry. Shared members have at most one
        # writer and their completed attempts count for all dependent sets.
        pending = {submission: 1 for submission in submissions}
        active = {}
        attempts = Counter()
        uploads = []
        build_failed = False
        while pending:
            for submission, attempt in list(pending.items()):
                if any(spec in active or attempts[spec] < attempt for spec in submission.members):
                    continue
                if self.build(submission, attempt):
                    del pending[submission]
                    if self.args.upload:
                        uploads.append(uploader.submit(self.upload, submission, len(submissions)))
                elif attempt == 1 and any(attempts[spec] == 1 for spec in submission.members):
                    pending[submission] = 2
                else:
                    build_failed = True
                    del pending[submission]

            # Registry order gives the first set, including its retries, first
            # claim on free worker slots. Other sets use slots as they free up.
            queue = ((spec, slots) for submission, attempt in pending.items()
                     for spec, slots in member_slots(submission.members, self.args.calls)
                     if attempts[spec] < attempt)
            self.start_members(pool, queue, active)
            if active:
                attempts.update(self.finish_members(active))
        upload_results = [upload.result() for upload in uploads]
        if build_failed:
            return 1
        return 0 if all(upload_results) else 4

    def run_optional(self, pool, conditions, submitted_members):
        # Keep the existing two passes for scoring-only conditions, reusing
        # member results already produced by submissions or an earlier group.
        for _ in range(2):
            ran = set(submitted_members)
            for members in conditions:
                active = {}
                todo = {spec: slots for spec, slots in member_slots(
                    [spec for spec in members if spec not in ran], self.args.calls)}
                while todo:
                    self.start_members(pool, todo.items(), active)
                    for spec in self.finish_members(active):
                        del todo[spec]
                        ran.add(spec)

    def run(self, registry):
        conditions = registry['conditions']
        submitted = names.submitted(registry)
        public = names.public_of(registry)
        submissions = []
        optional = []
        for condition in [*submitted, *(c for c in conditions if c not in submitted)]:
            members = tuple(dict.fromkeys(names.member_specs(registry, condition)))
            if condition in submitted:
                name = names.current(registry, condition)
                org = os.environ['FB_PUBLIC_ORG' if condition in public else 'FB_ORG']
                aggregate = registry['names'][name]['aggregate']
                submissions.append(Submission(len(submissions) + 1, name, org, aggregate, members))
            else:
                optional.append(members)
        status.record(self.args.root, 'round', pid=os.getpid(), sets=[
            dict(number=s.number, name=s.name, members=s.members,
                 filename=f'{self.args.due}.{file_org(s.organization)}.{s.number}.json')
            for s in submissions])
        with ThreadPoolExecutor(max_workers=self.args.calls) as members, ThreadPoolExecutor(max_workers=1) as uploader:
            rc = self.run_submissions(members, uploader, submissions)
            if not self.args.upload or rc == 0:
                self.run_optional(members, optional, {spec for s in submissions for spec in s.members})
        return rc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--due', required=True)
    parser.add_argument('--calls', required=True, type=int)
    parser.add_argument('--tag')
    parser.add_argument('--sample', type=int)
    parser.add_argument('--timeout', type=int)
    parser.add_argument('--upload', action='store_true')
    args = parser.parse_args()
    if args.calls < 1:
        parser.error('--calls must be positive')
    return RoundRun(args).run(names.load())


if __name__ == '__main__':
    sys.exit(main())
