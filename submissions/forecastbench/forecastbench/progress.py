"""Check whether the first ForecastBench set is on pace at noon UTC."""
import argparse
import json
from pathlib import Path

import forecastbench as fb
from forecastbench import names, status
from fri_forecaster import alert


def behind_schedule(root, registry):
    first = names.submitted(registry)[0]
    qset = json.loads((root / 'question_set.json').read_text())
    if qset['forecast_due_date'] != root.name:
        raise ValueError('Question set does not match this round')
    behind = []
    # At noon, two thirds of the time to the 18:00 target has elapsed.
    # That calls for two thirds of the 95% minimum in each question category.
    for spec in names.member_specs(registry, first):
        member_dir = Path(fb.member_dir_for_spec(root, spec))
        coverage = fb.coverage(qset, fb.read_results(member_dir / 'results.jsonl'))
        for kind, (done, total) in coverage.items():
            if 30 * done < 19 * total:
                behind.append(f'{member_dir.name}: {kind} {done}/{total}')
    return behind


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    root = parser.parse_args().root
    if (root / 'logs/first-upload-confirmed').exists():
        return
    try:
        behind = behind_schedule(root, names.load())
    except (OSError, ValueError, KeyError, IndexError, SystemExit) as error:
        alert.send('forecastbench', 'first submission progress unavailable',
                   f'{root.name}: unable to check noon progress ({type(error).__name__}).',
                   log=root / 'logs/round.log')
        return
    if behind and not (root / 'logs/first-upload-confirmed').exists():
        alert.send('forecastbench', 'first submission behind pace',
                   f'{root.name}: below the noon coverage checkpoint for an 18:00 UTC target. '
                   + ', '.join(behind) + '\n' + status.report(root)[0], log=root / 'logs/round.log')


if __name__ == '__main__':
    main()
