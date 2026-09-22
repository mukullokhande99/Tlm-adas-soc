"""Print the supplied workload catalogue from the platform configuration."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "configs" / "esp_isscc2024.json").read_text())

for name, scenario in CFG["scenarios"].items():
    jobs = scenario["jobs"]
    modes = ", ".join(sorted({job["mode"] for job in jobs}))
    engines = ", ".join(job["accelerator"] for job in jobs)
    print(f"{name}: {len(jobs)} jobs | {modes} | {engines}")
