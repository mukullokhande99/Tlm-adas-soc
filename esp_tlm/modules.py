"""Explicit AT-level modules that compose the ESP-inspired SoC platform.

These are transaction-level components, not RTL replicas. They make control,
translation, coherence and completion paths explicit for every workload trace.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .resources import QueuedResource


@dataclass(frozen=True)
class ModuleDescriptor:
    name: str
    kind: str
    tile: int | str
    purpose: str


class ExplicitSoCModules:
    """Composable control-plane modules used by the AT SoC simulator."""

    def __init__(self, cfg: dict, noc, cpu_tile: int):
        module_cfg = cfg.get("modules", {})
        self.noc = noc
        self.cpu_tile = cpu_tile
        self.iommu_tile = module_cfg.get("iommu", {}).get("tile", cfg["tiles"]["llc_tiles"][0])
        self.plic_tile = module_cfg.get("plic", {}).get("tile", cpu_tile)
        self.coherence_tile = module_cfg.get("coherence_manager", {}).get("tile", cfg["tiles"]["llc_tiles"][0])
        self.iommu = QueuedResource("iommu", **module_cfg.get("iommu", {}).get(
            "service", {"bandwidth_bytes_ns": 32.0, "latency_ns": 8.0, "capacity_bytes": None}
        ))
        self.coherence = QueuedResource("coherence", **module_cfg.get("coherence_manager", {}).get(
            "service", {"bandwidth_bytes_ns": 32.0, "latency_ns": 6.0, "capacity_bytes": None}
        ))
        self.plic = QueuedResource("plic", **module_cfg.get("plic", {}).get(
            "service", {"bandwidth_bytes_ns": 16.0, "latency_ns": 3.0, "capacity_bytes": None}
        ))
        self.activity: Counter[str] = Counter()
        self.descriptors = [
            ModuleDescriptor("riscv_smp_cluster", "CPU cluster", cpu_tile, "MMIO programming and interrupt consumption"),
            ModuleDescriptor("mesh_noc", "interconnect", "6x6", "request/response planes, VC arbitration and async crossings"),
            ModuleDescriptor("iommu", "DMA address translation", self.iommu_tile, "descriptor translation before DMA reads and writes"),
            ModuleDescriptor("coherence_manager", "coherence directory", self.coherence_tile, "coherent DMA probe and flush ordering"),
            ModuleDescriptor("plic", "interrupt controller", self.plic_tile, "accelerator completion interrupt aggregation"),
            ModuleDescriptor("llc_bank_group", "shared cache", "configured tiles", "queued LLC access path"),
            ModuleDescriptor("scratchpad_group", "local memory", "configured tiles", "explicit SPAD access path"),
            ModuleDescriptor("dram_controller", "memory controller", "off-chip", "queued external-memory service"),
            ModuleDescriptor("dhpm", "power manager", "global", "token allocation and V/F selection"),
        ]
        self.descriptors.extend(
            ModuleDescriptor(name, "accelerator tile", tile, "MMIO-configured DMA/compute/interrupt endpoint")
            for name, tile in cfg["tiles"]["accelerator_tiles"].items()
        )

    @staticmethod
    def _combine(*parts):
        from .at import ATTransactionResult
        return ATTransactionResult(
            complete_ns=parts[-1].complete_ns,
            network_ns=sum(part.network_ns for part in parts),
            service_ns=sum(part.service_ns for part in parts),
            queue_ns=sum(part.queue_ns for part in parts),
        )

    def program_accelerator(self, job, earliest: float):
        self.activity["riscv_smp_cluster"] += 1
        self.activity[job.accelerator] += 1
        return self.noc.nb_transport(
            f"{job.name}:mmio", self.cpu_tile, job.tile, 16, 16, earliest, None,
            "MMIO_PROGRAM", self.noc.mmio_service_ns,
        )

    def translate_dma(self, job, earliest: float, direction: str):
        self.activity["iommu"] += 1
        return self.noc.nb_transport(
            f"{job.name}:iommu_{direction}", job.tile, self.iommu_tile, self.noc.dma_desc_bytes, self.noc.ack_bytes,
            earliest, self.iommu, "IOMMU_TRANSLATE",
        )

    def coherence_probe(self, job, earliest: float):
        self.activity["coherence_manager"] += 1
        extra = self.noc.l2_flush_ns if job.mode.value == "coherent_dma_l2_flush" else 0.0
        return self.noc.nb_transport(
            f"{job.name}:coherence", job.tile, self.coherence_tile, self.noc.dma_desc_bytes, self.noc.ack_bytes,
            earliest, self.coherence, "COHERENCE_PROBE", extra,
        )

    def interrupt_complete(self, job, earliest: float):
        self.activity["plic"] += 1
        self.activity["riscv_smp_cluster"] += 1
        raise_irq = self.noc.nb_transport(
            f"{job.name}:irq_raise", job.tile, self.plic_tile, 16, 16, earliest, self.plic, "IRQ_RAISE",
        )
        deliver = self.noc.nb_transport(
            f"{job.name}:irq_deliver", self.plic_tile, self.cpu_tile, 16, 16, raise_irq.complete_ns, None, "IRQ_DELIVER",
        )
        return self._combine(raise_irq, deliver)

    def module_report(self) -> list[dict]:
        return [
            {
                "name": descriptor.name,
                "kind": descriptor.kind,
                "tile": descriptor.tile,
                "purpose": descriptor.purpose,
                "transactions": self.activity[descriptor.name],
            }
            for descriptor in self.descriptors
        ]
