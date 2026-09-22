#!/usr/bin/env python3
"""Run the four supplied architecture experiments and print a comparison table."""

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results"
SCENARIOS = ["baseline", "llc_spad", "direct_stream", "dhpm_5accel"]


def main() -> None:
    for scenario in SCENARIOS:
        subprocess.run([
            sys.executable, "-m", "esp_tlm.run", "--config", "configs/esp_isscc2024.json",
            "--scenario", scenario, "--out-dir", "results"
        ], cwd=ROOT, check=True)
    print("\nscenario        makespan(ns)  DRAM(bytes)  max-link-wait(ns)")
    for scenario in SCENARIOS:
        r = json.loads((OUT / f"{scenario}.json").read_text())
        print(f"{scenario:15} {r['makespan_ns']:12.2f} {r['dram_bytes']:12d} {r['noc']['max_link_queue_wait_ns']:17.2f}")


if __name__ == "__main__":
    main()
