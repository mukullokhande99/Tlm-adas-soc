from __future__ import annotations

import argparse
import json
from pathlib import Path

from .at import ATSoCSimulator, write_at_report
from .run import parse_jobs


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ESP-inspired approximately timed virtual platform")
    parser.add_argument("--config", required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--out-dir", default="results")
    args = parser.parse_args()
    cfg = json.loads(Path(args.config).read_text())
    scenario = cfg["scenarios"].get(args.scenario)
    if scenario is None:
        raise SystemExit(f"Unknown scenario {args.scenario!r}")
    scoped = {**cfg, "tiles": {**cfg["tiles"], **scenario.get("tile_override", {})}}
    report = ATSoCSimulator(scoped).run(args.scenario, parse_jobs(scenario["jobs"]))
    paths = write_at_report(report, args.out_dir)
    print(f"{args.scenario} [AT]: {report.makespan_ns:.2f} ns; {len(report.events)} phase events")
    print("\n".join(f"Output: {path}" for path in paths))


if __name__ == "__main__":
    main()
