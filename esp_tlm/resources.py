from __future__ import annotations

from dataclasses import dataclass


@dataclass
class QueuedResource:
    name: str
    bandwidth_bytes_ns: float
    latency_ns: float
    capacity_bytes: int | None = None
    available_ns: float = 0.0
    served_bytes: int = 0

    def service(self, earliest_ns: float, bytes_: int) -> tuple[float, float]:
        if self.capacity_bytes is not None and bytes_ > self.capacity_bytes:
            raise ValueError(
                f"{self.name}: {bytes_} B request exceeds configured capacity "
                f"{self.capacity_bytes} B"
            )
        start = max(earliest_ns, self.available_ns)
        finish = start + self.latency_ns + bytes_ / self.bandwidth_bytes_ns
        self.available_ns = finish
        self.served_bytes += bytes_
        return finish, finish - earliest_ns
