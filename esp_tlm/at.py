"""Approximately-timed (AT) transaction engine for the ESP-inspired SoC.

The engine uses the TLM-2.0 four-phase protocol vocabulary while keeping the
model dependency-free: BEGIN_REQ, END_REQ, BEGIN_RESP and END_RESP are emitted
for every MMIO, DMA, stream and writeback transaction.  Router/VC/queue timing
is explicitly annotated between phases.
"""
from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .dhpm import TokenPowerManager
from .modules import ExplicitSoCModules
from .resources import QueuedResource
from .types import AccessMode, Job, JobResult, dependency_order


@dataclass
class PhaseEvent:
    time_ns: float
    transaction: str
    phase: str
    location: str
    vc: int | None = None
    detail: str = ""


@dataclass
class ATTransactionResult:
    complete_ns: float
    network_ns: float
    service_ns: float
    queue_ns: float


class ATMeshNoC:
    """Packet-level AT mesh with per-direction virtual-channel availability.

    A packet represents a burst of flits.  The flits serialize on a selected
    virtual channel, while the trace remains compact by recording router events
    rather than one event per flit.
    """

    def __init__(self, noc_cfg: dict, at_cfg: dict):
        self.rows = noc_cfg["rows"]
        self.cols = noc_cfg["cols"]
        self.planes = noc_cfg["planes"]
        self.bytes_per_ns = noc_cfg["bytes_per_ns"]
        self.vcs = at_cfg["virtual_channels"]
        self.buffer_flits = at_cfg["vc_buffer_flits"]
        self.flit_bytes = at_cfg["flit_bytes"]
        self.router_req_ns = at_cfg["router_request_ns"]
        self.router_resp_ns = at_cfg["router_response_ns"]
        self.async_fifo_ns = at_cfg["async_fifo_ns"]
        self.tile_clock_ns = at_cfg["tile_clock_ns"]
        self.dma_desc_bytes = at_cfg["dma_desc_bytes"]
        self.ack_bytes = at_cfg["ack_bytes"]
        self.mmio_service_ns = at_cfg["mmio_service_ns"]
        self.l2_flush_ns = 0.0
        self.available: dict[tuple[int, int, int, int], float] = defaultdict(float)
        self.events: list[PhaseEvent] = []
        self.packet_count = self.flit_count = 0
        self.total_link_busy_ns = self.max_queue_ns = 0.0

    def _path(self, source: int, target: int) -> list[tuple[int, int]]:
        sr, sc = divmod(source, self.cols)
        tr, tc = divmod(target, self.cols)
        node, hops = source, []
        horizontal = 1 if tc >= sc else -1
        for _ in range(abs(tc - sc)):
            nxt = node + horizontal
            hops.append((node, nxt))
            node = nxt
        vertical = self.cols if tr >= sr else -self.cols
        for _ in range(abs(tr - sr)):
            nxt = node + vertical
            hops.append((node, nxt))
            node = nxt
        return hops

    def _cross_clock(self, now: float) -> float:
        aligned = math.ceil(now / self.tile_clock_ns) * self.tile_clock_ns
        return aligned + self.async_fifo_ns

    def route(self, name: str, phase: str, source: int, target: int, bytes_: int, earliest: float) -> tuple[float, float, float]:
        """Route one request/response packet, returning arrival, NoC, queue time."""
        hops = self._path(source, target)
        now, network, queued = self._cross_clock(earliest), self._cross_clock(earliest) - earliest, 0.0
        flits = max(1, math.ceil(bytes_ / self.flit_bytes))
        serial_ns = bytes_ / self.bytes_per_ns
        stage_ns = self.router_req_ns if phase == "REQ" else self.router_resp_ns
        if not hops:
            self.events.append(PhaseEvent(now, name, f"{phase}_LOCAL", f"tile{source}", detail=f"{bytes_} B"))
            return now, network, queued
        for hop_i, (src, dst) in enumerate(hops):
            candidates = [
                (self.available[(plane, vc, src, dst)], plane, vc)
                for plane in range(self.planes) for vc in range(self.vcs)
            ]
            free_at, plane, vc = min(candidates)
            start = max(now, free_at)
            q = start - now
            queued += q
            self.max_queue_ns = max(self.max_queue_ns, q)
            # Buffer capacity is a real AT parameter: a burst above its credit
            # window creates a credit-return boundary before the final flit.
            credit_rounds = max(0, math.ceil(flits / self.buffer_flits) - 1)
            credit_penalty = credit_rounds * self.router_req_ns
            finish = start + stage_ns + serial_ns + credit_penalty
            self.available[(plane, vc, src, dst)] = finish
            self.events.append(PhaseEvent(start, name, f"{phase}_ROUTER", f"tile{src}->tile{dst}", vc, f"plane={plane}; flits={flits}"))
            self.total_link_busy_ns += serial_ns
            network += finish - now
            now = finish
            if hop_i != len(hops) - 1:
                crossed = self._cross_clock(now)
                network += crossed - now
                now = crossed
        self.packet_count += 1
        self.flit_count += flits
        return now, network, queued

    def nb_transport(self, name: str, source: int, target: int, request_bytes: int, response_bytes: int,
                     earliest: float, service: QueuedResource | "CascadedResource" | None, kind: str, extra_service_ns: float = 0.0,
                     service_bytes: int | None = None) -> ATTransactionResult:
        """Model one complete four-phase non-blocking transaction."""
        self.events.append(PhaseEvent(earliest, name, "BEGIN_REQ", f"tile{source}", detail=kind))
        req_done, req_net, req_q = self.route(name, "REQ", source, target, request_bytes, earliest)
        self.events.append(PhaseEvent(req_done, name, "END_REQ", f"tile{target}", detail=kind))
        if service is None:
            service_done, service_ns = req_done + extra_service_ns, extra_service_ns
        else:
            service_done, service_ns = service.service(req_done, service_bytes if service_bytes is not None else request_bytes)
            service_done += extra_service_ns
            service_ns += extra_service_ns
        self.events.append(PhaseEvent(service_done, name, "BEGIN_RESP", f"tile{target}", detail=kind))
        resp_done, resp_net, resp_q = self.route(name, "RESP", target, source, response_bytes, service_done)
        self.events.append(PhaseEvent(resp_done, name, "END_RESP", f"tile{source}", detail=kind))
        return ATTransactionResult(resp_done, req_net + resp_net, service_ns, req_q + resp_q)


class CascadedResource:
    """A target path such as LLC followed by its off-chip DRAM interface."""

    def __init__(self, *resources: QueuedResource):
        self.resources = resources

    def service(self, earliest_ns: float, bytes_: int) -> tuple[float, float]:
        now, total = earliest_ns, 0.0
        for resource in self.resources:
            now, delay = resource.service(now, bytes_)
            total += delay
        return now, total


@dataclass
class ATReport:
    scenario: str
    makespan_ns: float = 0.0
    jobs: list[JobResult] = field(default_factory=list)
    events: list[PhaseEvent] = field(default_factory=list)
    packets: int = 0
    flits: int = 0
    link_busy_ns: float = 0.0
    max_vc_queue_ns: float = 0.0
    dram_bytes: int = 0
    assumptions: list[str] = field(default_factory=list)
    explicit_modules: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "model_fidelity": "approximately_timed",
            "protocol": ["BEGIN_REQ", "END_REQ", "BEGIN_RESP", "END_RESP"],
            "scenario": self.scenario,
            "makespan_ns": round(self.makespan_ns, 3),
            "throughput_jobs_per_ms": round(len(self.jobs) / max(self.makespan_ns / 1e6, 1e-12), 5),
            "jobs": [asdict(x) for x in self.jobs],
            "at_noc": {
                "packets": self.packets,
                "flits": self.flits,
                "aggregate_link_busy_ns": round(self.link_busy_ns, 3),
                "max_virtual_channel_queue_ns": round(self.max_vc_queue_ns, 3),
                "phase_events": len(self.events),
            },
            "dram_bytes": self.dram_bytes,
            "explicit_modules": self.explicit_modules,
            "assumption_ledger": self.assumptions,
        }


class ATSoCSimulator:
    """AT virtual platform for runtime memory-orchestration and DHPM studies."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.cpu_tile = cfg["tiles"]["cpu_tiles"][0]
        self.accel_tiles = cfg["tiles"]["accelerator_tiles"]
        self.llc_tiles = cfg["tiles"]["llc_tiles"]
        self.spad_tiles = cfg["tiles"]["spad_tiles"]
        self.noc = ATMeshNoC(cfg["noc"], cfg["at"])
        self.noc.l2_flush_ns = cfg["memory"]["l2_flush_ns"]
        mem = cfg["memory"]
        self.dram = QueuedResource("dram", **mem["dram"])
        self.llcs = {tile: QueuedResource(f"llc{tile}", **mem["llc"]) for tile in self.llc_tiles}
        self.spads = {tile: QueuedResource(f"spad{tile}", **mem["spad"]) for tile in self.spad_tiles}
        self.dhpm = TokenPowerManager(**cfg["dhpm"])
        self.accel_available = {name: 0.0 for name in self.accel_tiles}
        self.completed: dict[str, JobResult] = {}
        self.modules = ExplicitSoCModules(cfg, self.noc, self.cpu_tile)

    def _active_demands(self, start_ns: float, candidate: Job) -> dict[str, int]:
        demands = {candidate.accelerator: candidate.active_power_tokens}
        for result in self.completed.values():
            if result.start_ns <= start_ns < result.end_ns:
                demands[result.accelerator] = self.cfg["accelerators"][result.accelerator]["power_tokens"]
        return demands

    def _mmio(self, job: Job, earliest: float) -> ATTransactionResult:
        job.tile = self.accel_tiles[job.accelerator]
        return self.modules.program_accelerator(job, earliest)

    @staticmethod
    def _combine(*parts: ATTransactionResult) -> ATTransactionResult:
        return ATTransactionResult(
            parts[-1].complete_ns,
            sum(part.network_ns for part in parts),
            sum(part.service_ns for part in parts),
            sum(part.queue_ns for part in parts),
        )

    def _input(self, job: Job, earliest: float) -> tuple[ATTransactionResult, int]:
        accel_tile = self.accel_tiles[job.accelerator]
        job.tile = accel_tile
        if job.mode == AccessMode.DIRECT and job.depends_on:
            producer = self.completed[job.depends_on]
            src = self.accel_tiles[producer.accelerator]
            return self.noc.nb_transport(f"{job.name}:stream", src, accel_tile, job.input_bytes, self.cfg["at"]["ack_bytes"], earliest, None, "DIRECT_STREAM"), 0
        translation = self.modules.translate_dma(job, earliest, "read")
        coherence = None
        if job.mode in (AccessMode.COHERENT, AccessMode.COHERENT_FLUSH):
            coherence = self.modules.coherence_probe(job, translation.complete_ns)
        transaction_start = coherence.complete_ns if coherence else translation.complete_ns
        if job.mode == AccessMode.SPAD:
            if not self.spads:
                raise ValueError("SPAD mode requested without an enabled SPAD tile")
            target = min(self.spads, key=lambda x: abs(x - accel_tile))
            result = self.noc.nb_transport(f"{job.name}:dma_read", accel_tile, target, self.cfg["at"]["dma_desc_bytes"], job.input_bytes,
                                           transaction_start, self.spads[target], "DMA_READ", service_bytes=job.input_bytes)
            return self._combine(translation, *([coherence] if coherence else []), result), 0
        if not self.llcs:
            raise ValueError("No LLC tile enabled")
        target = min(self.llcs, key=lambda x: abs(x - accel_tile))
        extra = self.cfg["memory"]["l2_flush_ns"] if job.mode == AccessMode.COHERENT_FLUSH else 0.0
        uses_dram = job.mode in (AccessMode.NON_COHERENT, AccessMode.COHERENT_FLUSH)
        resource = CascadedResource(self.llcs[target], self.dram) if uses_dram else self.llcs[target]
        at_result = self.noc.nb_transport(f"{job.name}:dma_read", accel_tile, target, self.cfg["at"]["dma_desc_bytes"], job.input_bytes,
                                          transaction_start, resource, "DMA_READ", extra, job.input_bytes)
        return self._combine(translation, *([coherence] if coherence else []), at_result), job.input_bytes if uses_dram else 0

    def _output(self, job: Job, earliest: float) -> tuple[ATTransactionResult, int]:
        accel_tile = self.accel_tiles[job.accelerator]
        job.tile = accel_tile
        if job.mode == AccessMode.DIRECT and job.output_consumer:
            return ATTransactionResult(earliest, 0.0, 0.0, 0.0), 0
        translation = self.modules.translate_dma(job, earliest, "write")
        coherence = None
        if job.mode in (AccessMode.COHERENT, AccessMode.COHERENT_FLUSH):
            coherence = self.modules.coherence_probe(job, translation.complete_ns)
        transaction_start = coherence.complete_ns if coherence else translation.complete_ns
        if job.mode == AccessMode.SPAD and self.spads:
            target = min(self.spads, key=lambda x: abs(x - accel_tile))
            result = self.noc.nb_transport(f"{job.name}:dma_write", accel_tile, target, job.output_bytes, self.cfg["at"]["ack_bytes"],
                                           transaction_start, self.spads[target], "DMA_WRITE")
            return self._combine(translation, *([coherence] if coherence else []), result), 0
        target = min(self.llcs, key=lambda x: abs(x - accel_tile))
        uses_dram = job.mode in (AccessMode.NON_COHERENT, AccessMode.COHERENT_FLUSH)
        resource = CascadedResource(self.llcs[target], self.dram) if uses_dram else self.llcs[target]
        result = self.noc.nb_transport(f"{job.name}:dma_write", accel_tile, target, job.output_bytes, self.cfg["at"]["ack_bytes"],
                                       transaction_start, resource, "DMA_WRITE")
        return self._combine(translation, *([coherence] if coherence else []), result), job.output_bytes if uses_dram else 0

    def run(self, scenario: str, jobs: list[Job]) -> ATReport:
        report = ATReport(scenario=scenario)
        for job in dependency_order(jobs):
            if job.depends_on and job.depends_on not in self.completed:
                raise ValueError(f"{job.name} depends on unavailable job {job.depends_on}")
            dependency = self.completed[job.depends_on].end_ns if job.depends_on else 0.0
            start = max(job.release_ns, dependency, self.accel_available[job.accelerator])
            mmio = self._mmio(job, start)
            read, dram_in = self._input(job, mmio.complete_ns)
            demands = self._active_demands(read.complete_ns, job)
            tokens = self.dhpm.allocate(demands).get(job.accelerator, 0)
            freq = self.dhpm.frequency_ghz(tokens)
            accel = self.cfg["accelerators"][job.accelerator]
            compute_ns = job.ops / (accel["ops_per_cycle"] * freq)
            compute_done = read.complete_ns + compute_ns
            write, dram_out = self._output(job, compute_done)
            irq = self.modules.interrupt_complete(job, write.complete_ns)
            end = irq.complete_ns
            self.accel_available[job.accelerator] = end
            result = JobResult(
                job.name, job.accelerator, job.mode.value, start, end, read.complete_ns, compute_done,
                freq, tokens, mmio.network_ns + read.network_ns + write.network_ns,
                mmio.service_ns + read.service_ns + write.service_ns + irq.service_ns, compute_ns, dram_in + dram_out,
                compute_ns * accel["power_nw_per_token"] * tokens / 1e9,
            )
            self.completed[job.name] = result
            report.jobs.append(result)
            report.dram_bytes += dram_in + dram_out
        report.makespan_ns = max((job.end_ns for job in report.jobs), default=0.0)
        report.events = sorted(self.noc.events, key=lambda x: (x.time_ns, x.transaction, x.phase))
        report.packets = self.noc.packet_count
        report.flits = self.noc.flit_count
        report.link_busy_ns = self.noc.total_link_busy_ns
        report.max_vc_queue_ns = self.noc.max_queue_ns
        report.explicit_modules = self.modules.module_report()
        report.assumptions = self.cfg["assumption_ledger"] + [
            "AT extension: each transaction records the four TLM non-blocking protocol phases and packet-level router/VC arbitration.",
            "AT extension: flits are serialized analytically within each packet; this is not a flit-by-flit RTL NoC simulation.",
            "AT extension: asynchronous tile boundaries add a programmable FIFO delay and align to a configurable tile clock period.",
            "Explicit-module extension: CPU cluster, IOMMU, coherence manager, PLIC, memory subsystem, DHPM and accelerator tiles are named transaction-level components with per-module transaction accounting."
        ]
        return report


def write_at_report(report: ATReport, out_dir: str | Path) -> tuple[Path, Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report_path = out / f"{report.scenario}_at.json"
    job_trace = out / f"{report.scenario}_at_jobs.csv"
    phase_trace = out / f"{report.scenario}_at_phases.csv"
    report_path.write_text(json.dumps(report.to_dict(), indent=2) + "\n")
    with job_trace.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(report.jobs[0]).keys()) if report.jobs else ["name"])
        writer.writeheader()
        writer.writerows(asdict(job) for job in report.jobs)
    with phase_trace.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["time_ns", "transaction", "phase", "location", "vc", "detail"])
        writer.writeheader()
        writer.writerows(asdict(event) for event in report.events)
    return report_path, job_trace, phase_trace
