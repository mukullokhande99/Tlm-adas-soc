from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .dhpm import TokenPowerManager
from .noc import MeshNoC
from .resources import QueuedResource
from .types import AccessMode, Job, JobResult, Report, Transaction


class SoCSimulator:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        noc_cfg = cfg["noc"]
        self.noc = MeshNoC(**noc_cfg)
        self.cpu_tile = cfg["tiles"]["cpu_tiles"][0]
        self.accel_tiles = cfg["tiles"]["accelerator_tiles"]
        self.llc_tiles = cfg["tiles"]["llc_tiles"]
        self.spad_tiles = cfg["tiles"]["spad_tiles"]
        mem = cfg["memory"]
        self.dram = QueuedResource("dram", **mem["dram"])
        self.llcs = {tile: QueuedResource(f"llc{tile}", **mem["llc"]) for tile in self.llc_tiles}
        self.spads = {tile: QueuedResource(f"spad{tile}", **mem["spad"]) for tile in self.spad_tiles}
        self.dhpm = TokenPowerManager(**cfg["dhpm"])
        self.accel_available = {name: 0.0 for name in self.accel_tiles}
        self.completed: dict[str, JobResult] = {}

    def _transport(self, name: str, source: int, target: int, bytes_: int, earliest: float, kind: str) -> tuple[float, float]:
        return self.noc.transport(Transaction(name, source, target, bytes_, earliest, kind))

    def _memory_path(self, job: Job, earliest: float) -> tuple[float, float, float, int]:
        accel_tile = self.accel_tiles[job.accelerator]
        if job.mode == AccessMode.SPAD:
            if not self.spads:
                raise ValueError("SPAD mode requested but no SPAD tiles are enabled")
            tile = min(self.spads, key=lambda x: abs(x - accel_tile))
            t1, n1 = self._transport(job.name + ":in_to_spad", accel_tile, tile, job.input_bytes, earliest, "read")
            t2, m = self.spads[tile].service(t1, job.input_bytes)
            t3, n2 = self._transport(job.name + ":spad_to_accel", tile, accel_tile, job.input_bytes, t2, "read")
            return t3, n1 + n2, m, 0
        if job.mode == AccessMode.DIRECT and job.depends_on:
            producer = self.completed[job.depends_on]
            producer_tile = self.accel_tiles[producer.accelerator]
            t, n = self._transport(job.name + ":stream", producer_tile, accel_tile, job.input_bytes, earliest, "stream")
            return t, n, 0.0, 0
        if not self.llcs:
            raise ValueError("No LLC tile enabled; a memory path cannot be formed")
        llc_tile = min(self.llcs, key=lambda x: abs(x - accel_tile))
        t1, n1 = self._transport(job.name + ":in_to_llc", accel_tile, llc_tile, job.input_bytes, earliest, "read")
        t2, lm = self.llcs[llc_tile].service(t1, job.input_bytes)
        # Coherent mode is served by LLC; non-coherent and large traffic use DRAM too.
        dram_bytes = job.input_bytes if job.mode in (AccessMode.NON_COHERENT, AccessMode.COHERENT_FLUSH) else 0
        if dram_bytes:
            t2, dm = self.dram.service(t2, dram_bytes)
        else:
            dm = 0.0
        if job.mode == AccessMode.COHERENT_FLUSH:
            t2 += self.cfg["memory"]["l2_flush_ns"]
            lm += self.cfg["memory"]["l2_flush_ns"]
        t3, n2 = self._transport(job.name + ":llc_to_accel", llc_tile, accel_tile, job.input_bytes, t2, "read")
        return t3, n1 + n2, lm + dm, dram_bytes

    def _writeback(self, job: Job, earliest: float) -> tuple[float, float, float, int]:
        if job.mode == AccessMode.DIRECT and job.output_consumer:
            # The consuming job performs the actual stream transaction.
            return earliest, 0.0, 0.0, 0
        accel_tile = self.accel_tiles[job.accelerator]
        if job.mode == AccessMode.SPAD and self.spads:
            tile = min(self.spads, key=lambda x: abs(x - accel_tile))
            t1, n1 = self._transport(job.name + ":out_to_spad", accel_tile, tile, job.output_bytes, earliest, "write")
            t2, m = self.spads[tile].service(t1, job.output_bytes)
            return t2, n1, m, 0
        llc_tile = min(self.llcs, key=lambda x: abs(x - accel_tile))
        t1, n1 = self._transport(job.name + ":out_to_llc", accel_tile, llc_tile, job.output_bytes, earliest, "write")
        t2, lm = self.llcs[llc_tile].service(t1, job.output_bytes)
        dram_bytes = job.output_bytes if job.mode in (AccessMode.NON_COHERENT, AccessMode.COHERENT_FLUSH) else 0
        if dram_bytes:
            t2, dm = self.dram.service(t2, dram_bytes)
        else:
            dm = 0.0
        return t2, n1, lm + dm, dram_bytes

    def _active_demands(self, start_ns: float, candidate: Job) -> dict[str, int]:
        demands = {candidate.accelerator: candidate.active_power_tokens}
        for result in self.completed.values():
            if result.start_ns <= start_ns < result.end_ns:
                demands[result.accelerator] = self.cfg["accelerators"][result.accelerator]["power_tokens"]
        return demands

    def run(self, scenario: str, jobs: list[Job]) -> Report:
        report = Report(scenario=scenario)
        for job in sorted(jobs, key=lambda j: (j.release_ns, j.name)):
            if job.depends_on and job.depends_on not in self.completed:
                raise ValueError(f"{job.name} depends on missing/uncompleted job {job.depends_on}")
            dependency_done = self.completed[job.depends_on].end_ns if job.depends_on else 0.0
            tile_ready = self.accel_available[job.accelerator]
            start = max(job.release_ns, dependency_done, tile_ready)
            input_done, in_network, in_memory, dram_in = self._memory_path(job, start)
            demands = self._active_demands(input_done, job)
            tokens = self.dhpm.allocate(demands).get(job.accelerator, 0)
            freq = self.dhpm.frequency_ghz(tokens)
            accel = self.cfg["accelerators"][job.accelerator]
            compute_ns = job.ops / (accel["ops_per_cycle"] * freq)  # GHz = cycles/ns
            compute_done = input_done + compute_ns
            end, out_network, out_memory, dram_out = self._writeback(job, compute_done)
            self.accel_available[job.accelerator] = end
            # Dynamic-power proxy: P is normalized to the active token allocation.
            energy_nj = compute_ns * accel["power_nw_per_token"] * tokens / 1e9
            result = JobResult(
                name=job.name, accelerator=job.accelerator, mode=job.mode.value,
                start_ns=start, end_ns=end, input_done_ns=input_done,
                compute_done_ns=compute_done, frequency_ghz=freq, tokens=tokens,
                network_ns=in_network + out_network, memory_ns=in_memory + out_memory,
                compute_ns=compute_ns, dram_bytes=dram_in + dram_out, energy_nj=energy_nj,
            )
            self.completed[job.name] = result
            report.jobs.append(result)
            report.dram_bytes += dram_in + dram_out
        report.makespan_ns = max((j.end_ns for j in report.jobs), default=0.0)
        report.noc_packets = self.noc.packets
        report.noc_bytes = self.noc.bytes
        report.noc_busy_ns = self.noc.total_busy_ns
        report.max_link_wait_ns = self.noc.max_wait_ns
        report.assumption_ledger = self.cfg["assumption_ledger"]
        return report


def write_report(report: Report, out_dir: str | Path) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report_path = out / f"{report.scenario}.json"
    trace_path = out / f"{report.scenario}_trace.csv"
    report_path.write_text(json.dumps(report.to_dict(), indent=2) + "\n")
    fields = list(asdict(report.jobs[0]).keys()) if report.jobs else []
    with trace_path.open("w") as f:
        if fields:
            f.write(",".join(fields) + "\n")
            for job in report.jobs:
                row = asdict(job)
                f.write(",".join(str(row[x]) for x in fields) + "\n")
    return report_path, trace_path
