from __future__ import annotations

import argparse
import json
from pathlib import Path

from .simulator import SoCSimulator, write_report
from .types import AccessMode, Job


def parse_jobs(raw_jobs: list[dict]) -> list[Job]:
    return [Job(**{**job, "mode": AccessMode(job["mode"])}) for job in raw_jobs]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ESP-inspired SoC LT virtual platform")
    parser.add_argument("--config", required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--out-dir", default="results")
    args = parser.parse_args()
    cfg = json.loads(Path(args.config).read_text())
    if args.scenario not in cfg["scenarios"]:
        raise SystemExit(f"Unknown scenario {args.scenario!r}; choose from {', '.join(cfg['scenarios'])}")
    scenario = cfg["scenarios"][args.scenario]
    scoped = {**cfg, "tiles": {**cfg["tiles"], **scenario.get("tile_override", {})}}
    sim = SoCSimulator(scoped)
    report = sim.run(args.scenario, parse_jobs(scenario["jobs"]))
    json_path, csv_path = write_report(report, args.out_dir)
    print(f"{args.scenario}: {report.makespan_ns:.2f} ns, {len(report.jobs)} jobs")
    print(f"Report: {json_path}\nTrace: {csv_path}")


if __name__ == "__main__":
    main()
