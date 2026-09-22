from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AccessMode(str, Enum):
    NON_COHERENT = "non_coherent_dma"
    COHERENT = "coherent_dma"
    COHERENT_FLUSH = "coherent_dma_l2_flush"
    SPAD = "spad"
    DIRECT = "direct_stream"


@dataclass(frozen=True)
class Transaction:
    """TLM generic-payload analogue used by the model."""

    name: str
    source: int
    target: int
    bytes: int
    earliest_ns: float
    kind: str = "read"


@dataclass
class Job:
    name: str
    accelerator: str
    release_ns: float
    input_bytes: int
    output_bytes: int
    ops: float
    mode: AccessMode
    depends_on: str | None = None
    active_power_tokens: int = 8
    output_consumer: str | None = None
    tile: int = -1


def dependency_order(jobs: list[Job]) -> list[Job]:
    """Return a release-time-stable topological order for a workload DAG."""
    pending = {job.name: job for job in jobs}
    if len(pending) != len(jobs):
        raise ValueError("Workload jobs must have unique names")
    missing = [job.depends_on for job in jobs if job.depends_on and job.depends_on not in pending]
    if missing:
        raise ValueError(f"Workload depends on unknown job {missing[0]}")
    ordered: list[Job] = []
    completed: set[str] = set()
    while pending:
        ready = [job for job in pending.values() if not job.depends_on or job.depends_on in completed]
        if not ready:
            raise ValueError("Workload dependency graph contains a cycle")
        job = min(ready, key=lambda candidate: (candidate.release_ns, candidate.name))
        ordered.append(job)
        completed.add(job.name)
        del pending[job.name]
    return ordered


@dataclass
class JobResult:
    name: str
    accelerator: str
    mode: str
    start_ns: float
    end_ns: float
    input_done_ns: float
    compute_done_ns: float
    frequency_ghz: float
    tokens: int
    network_ns: float
    memory_ns: float
    compute_ns: float
    dram_bytes: int
    energy_nj: float


@dataclass
class Report:
    scenario: str
    makespan_ns: float = 0.0
    jobs: list[JobResult] = field(default_factory=list)
    noc_packets: int = 0
    noc_bytes: int = 0
    noc_busy_ns: float = 0.0
    max_link_wait_ns: float = 0.0
    dram_bytes: int = 0
    assumption_ledger: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        latency = self.makespan_ns
        total_energy = sum(job.energy_nj for job in self.jobs)
        return {
            "scenario": self.scenario,
            "makespan_ns": round(latency, 3),
            "throughput_jobs_per_ms": round(len(self.jobs) / max(latency / 1e6, 1e-12), 5),
            "jobs": [vars(job) for job in self.jobs],
            "noc": {
                "packets": self.noc_packets,
                "bytes": self.noc_bytes,
                "aggregate_link_busy_ns": round(self.noc_busy_ns, 3),
                "max_link_queue_wait_ns": round(self.max_link_wait_ns, 3),
            },
            "dram_bytes": self.dram_bytes,
            "estimated_compute_energy_nj": round(total_energy, 3),
            "assumption_ledger": self.assumption_ledger,
        }
