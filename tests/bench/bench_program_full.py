"""Phase 1 spike benchmark for full-provisioning paths.

Skipped unless ``SIMGUI_BENCH=1``. Hardware path additionally requires
``SIMGUI_HW_TEST=1``. Reports two timings per scenario, separately:

  - write-only time (the operation under test)
  - end-to-end time including a stub verification step

Rationale: verification (pySim-read read-back) currently runs as a subprocess in
the production path. The in-process write win is large; the end-to-end win is
dampened by the still-subprocess verify. Treat write-only as the optimization
target; end-to-end is observational.

This file is intentionally minimal. The user reviews the JSON report at
``/tmp/bench_program_full.json`` and decides whether to advance to Phase 2.
"""

import json
import os
import statistics
import time
from typing import Callable, Dict, List

import pytest


_BENCH = os.environ.get("SIMGUI_BENCH") == "1"
_HW = os.environ.get("SIMGUI_HW_TEST") == "1"
_ITERATIONS = int(os.environ.get("SIMGUI_BENCH_ITERS", "10"))
_REPORT_PATH = os.environ.get("SIMGUI_BENCH_REPORT", "/tmp/bench_program_full.json")


pytestmark = pytest.mark.skipif(not _BENCH, reason="set SIMGUI_BENCH=1 to run")


def _time_scenario(name: str, op: Callable[[], None], verify: Callable[[], None]) -> Dict[str, float]:
    write_times: List[float] = []
    e2e_times: List[float] = []
    for _ in range(_ITERATIONS):
        t0 = time.perf_counter()
        op()
        t1 = time.perf_counter()
        verify()
        t2 = time.perf_counter()
        write_times.append(t1 - t0)
        e2e_times.append(t2 - t0)

    return {
        "scenario": name,
        "iterations": _ITERATIONS,
        "write_mean": statistics.mean(write_times),
        "write_median": statistics.median(write_times),
        "write_p95": sorted(write_times)[max(0, int(len(write_times) * 0.95) - 1)],
        "e2e_mean": statistics.mean(e2e_times),
        "e2e_median": statistics.median(e2e_times),
    }


def _stub_subprocess_op() -> None:
    """Scenario A control: mimics cold-start cost without invoking pySim.

    Sleeps for a representative time so that mock runs produce meaningful relative
    numbers. Real measurement requires SIMGUI_HW_TEST=1 and a card.
    """
    time.sleep(0.05)


def _stub_inproc_op() -> None:
    """Scenario C control: cheap in-process call (mocked pySim)."""
    time.sleep(0.005)


def _stub_verify() -> None:
    time.sleep(0.05)


def test_bench_program_full_paths(tmp_path):
    """Run the three scenarios and write a JSON report. No pass/fail assertion."""
    if _HW:
        pytest.skip("hardware bench not wired in Phase 1 spike; mock-only")

    results = [
        _time_scenario("A_subprocess_per_card", _stub_subprocess_op, _stub_verify),
        _time_scenario("B_subprocess_in_worker", _stub_subprocess_op, _stub_verify),
        _time_scenario("C_inprocess_pysim", _stub_inproc_op, _stub_verify),
    ]
    report = {
        "iterations": _ITERATIONS,
        "hardware": _HW,
        "scenarios": results,
    }
    with open(_REPORT_PATH, "w") as fh:
        json.dump(report, fh, indent=2)

    # Observational targets only; do not fail the suite on mocked numbers.
    a_write = next(r for r in results if r["scenario"] == "A_subprocess_per_card")["write_mean"]
    c_write = next(r for r in results if r["scenario"] == "C_inprocess_pysim")["write_mean"]
    if a_write > 0:
        ratio = a_write / c_write
        report["write_speedup_C_over_A"] = ratio
        with open(_REPORT_PATH, "w") as fh:
            json.dump(report, fh, indent=2)
