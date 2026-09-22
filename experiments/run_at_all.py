#!/usr/bin/env python3
"""Run all supplied workloads through the approximately timed engine."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ["baseline", "llc_spad", "direct_stream", "dhpm_5accel"]


def main() -> None:
    for scenario in SCENARIOS:
        subprocess.run([sys.executable, "-m", "esp_tlm.at_run", "--config", "configs/esp_isscc2024.json", "--scenario", scenario], cwd=ROOT, check=True)
    print("\nscenario        makespan(ns)  phases  max-VC-wait(ns)")
    for scenario in SCENARIOS:
        report = json.loads((ROOT / "results" / f"{scenario}_at.json").read_text())
        noc = report["at_noc"]
        print(f"{scenario:15} {report['makespan_ns']:12.2f} {noc['phase_events']:7d} {noc['max_virtual_channel_queue_ns']:16.2f}")


if __name__ == "__main__":
    main()
