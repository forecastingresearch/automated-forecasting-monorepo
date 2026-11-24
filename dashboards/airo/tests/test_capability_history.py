"""Observed chart history must move with the panel's Epoch snapshot."""
import csv
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from redlines import eci
from redlines.views import capability


def write_snapshot(root, day, score):
    path = root / f'epoch_capabilities_index_{day}.csv'
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['Model', 'Display name', 'eci',
            'eci_ci_low', 'eci_ci_high', 'date', 'Country (of organization)'])
        writer.writeheader()
        writer.writerow({'Model': 'test-frontier', 'Display name': 'Test frontier',
            'eci': score, 'date': day, 'Country (of organization)': eci.US})
    return path


def test_new_panel_snapshot_updates_chart_without_editing_trend_or_prompts():
    with tempfile.TemporaryDirectory() as tmp, patch.object(eci, 'SNAPSHOT_DIR', Path(tmp)):
        write_snapshot(Path(tmp), '2026-10-01', 160)
        before = capability.observed_eci_history()
        latest = write_snapshot(Path(tmp), '2026-11-24', 180)
        after = capability.observed_eci_history()
        assert after['snapshot'] == eci.latest()[1].name == latest.name
        assert after['csvDate'] == '2026-11-24'
        assert after['latest']['score'] == 180
        assert before['latest']['score'] == 160


def test_missing_history_in_latest_snapshot_does_not_fall_back_to_old_chart():
    with tempfile.TemporaryDirectory() as tmp, patch.object(eci, 'SNAPSHOT_DIR', Path(tmp)):
        write_snapshot(Path(tmp), '2026-10-01', 160)
        (Path(tmp) / 'epoch_capabilities_index_2026-11-24.csv').write_text(
            'rank,model,eci,ci_low,ci_high,retrieved\n1,New model,180,,,2026-11-24\n')
        with pytest.raises(ValueError, match='panel snapshot'):
            capability.observed_eci_history()


def test_capability_build_uses_current_observations_and_keeps_trend_vintage():
    built = capability.build()['eci']
    observed = capability.observed_eci_history()
    for key, value in observed.items():
        assert built[key] == value
    assert built['trend']['dataDate'] == '2026-09-10'
