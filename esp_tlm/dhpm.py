from __future__ import annotations


class TokenPowerManager:
    """Fair token allocation + piecewise V/F model inspired by the paper's DHPM."""

    def __init__(self, total_tokens: int, vf_points: list[list[float]]):
        self.total_tokens = total_tokens
        self.vf_points = sorted((int(t), float(f)) for t, f in vf_points)

    def allocate(self, demands: dict[str, int]) -> dict[str, int]:
        active = {name: max(0, value) for name, value in demands.items() if value > 0}
        if not active:
            return {}
        allocation = {name: 0 for name in active}
        budget = self.total_tokens
        # Round-robin allocation makes the fairness policy deterministic.
        while budget and any(allocation[n] < active[n] for n in active):
            for name in sorted(active):
                if budget == 0:
                    break
                if allocation[name] < active[name]:
                    allocation[name] += 1
                    budget -= 1
        return allocation

    def frequency_ghz(self, tokens: int) -> float:
        lower = self.vf_points[0]
        for point in self.vf_points:
            if point[0] > tokens:
                break
            lower = point
        return lower[1]
