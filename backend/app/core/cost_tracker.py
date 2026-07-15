from decimal import Decimal

COST_CEILING = Decimal("0.05")


class CostTracker:
    def __init__(self, ceiling: Decimal | float = COST_CEILING):
        self.cumulative_cost = Decimal("0.00")
        self.ceiling = Decimal(ceiling) if not isinstance(ceiling, Decimal) else ceiling
        self.forced_cheap = False

    def add_cost(self, cost: Decimal | float | str):
        self.cumulative_cost += Decimal(cost)
        if self.cumulative_cost > self.ceiling:
            self.forced_cheap = True

    def within_budget(self) -> bool:
        return self.cumulative_cost <= self.ceiling

    def remaining_budget(self) -> Decimal:
        remaining = self.ceiling - self.cumulative_cost
        return max(remaining, Decimal("0.00"))
