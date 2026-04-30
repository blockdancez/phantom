"""Tests for the lightweight run-history registry used by /stats/pipeline."""

from __future__ import annotations

import time

from src.scheduler import runs


def test_record_start_and_finish_success():
    runs.reset()
    started = runs.record_start("collect_data")
    time.sleep(0.01)
    runs.record_finish("collect_data", started, status="success")

    last = runs.last_run("collect_data")
    assert last is not None
    assert last.status == "success"
    assert last.duration_ms is not None and last.duration_ms >= 0
    assert last.error is None


def test_record_finish_failed():
    runs.reset()
    started = runs.record_start("process_data")
    runs.record_finish(
        "process_data", started, status="failed", error="ValueError: boom"
    )
    last = runs.last_run("process_data")
    assert last is not None
    assert last.status == "failed"
    assert last.error == "ValueError: boom"


def test_all_last_runs_returns_latest_per_job():
    runs.reset()
    started_a = runs.record_start("a")
    runs.record_finish("a", started_a, status="success")
    started_b = runs.record_start("b")
    runs.record_finish("b", started_b, status="failed", error="x")

    snapshot = runs.all_last_runs()
    assert set(snapshot) == {"a", "b"}
    assert snapshot["a"].status == "success"
    assert snapshot["b"].status == "failed"


def test_last_run_empty_returns_none():
    runs.reset()
    assert runs.last_run("never_ran") is None


def test_history_is_bounded():
    runs.reset()
    for _ in range(50):
        started = runs.record_start("burst")
        runs.record_finish("burst", started, status="success")
    # Internal deque maxlen should keep only the last 20.
    assert len(runs._runs["burst"]) <= 20
    runs.reset()
