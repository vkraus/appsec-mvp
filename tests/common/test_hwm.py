from datetime import datetime, timezone

import pytest

from src.common.hwm import HwmStore, UpdatedAtHwm, CommitShaHwm, ScanIdHwm


@pytest.fixture
def store(tmp_path):
    # Lightweight JSON-backed store used by tests; production uses a Delta
    # HWM table. Interface is identical.
    return HwmStore(tmp_path / "hwm.json")


def test_updated_at_hwm_reads_empty_as_epoch(store):
    strat = UpdatedAtHwm(key="sonarqube.issues", store=store)
    assert strat.read() == datetime(1970, 1, 1, tzinfo=timezone.utc)


def test_updated_at_hwm_round_trips(store):
    strat = UpdatedAtHwm(key="sonarqube.issues", store=store)
    ts = datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc)
    strat.write(ts)
    assert strat.read() == ts


def test_commit_sha_hwm_per_repo(store):
    strat = CommitShaHwm(key="semgrep", store=store)
    assert strat.read("org/repo-a") is None
    strat.write("org/repo-a", "deadbeef")
    assert strat.read("org/repo-a") == "deadbeef"
    assert strat.read("org/repo-b") is None


def test_scan_id_hwm(store):
    strat = ScanIdHwm(key="zap", store=store)
    assert strat.read() is None
    strat.write("scan-42")
    assert strat.read() == "scan-42"
