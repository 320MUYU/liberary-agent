from dataclasses import dataclass, field
from typing import Callable
import time


class BudgetExceeded(Exception):
    pass


@dataclass
class RunBudget:
    max_tools: int = 8
    max_models: int = 4
    seconds: float = 60
    tools: int = 0
    models: int = 0
    started: float = field(default_factory=time.monotonic)

    def remaining(self):
        value = self.seconds - (time.monotonic() - self.started)
        if value <= 0:
            raise BudgetExceeded()
        return value

    def consume(self, kind):
        self.remaining()
        if kind == "tool":
            if self.tools >= self.max_tools:
                raise BudgetExceeded()
            self.tools += 1
        else:
            if self.models >= self.max_models:
                raise BudgetExceeded()
            self.models += 1


@dataclass
class WorkflowBudget(RunBudget):
    """Reserve a durable parent allowance before making an external call."""
    reserve: Callable[[str], None] = field(default=lambda _: None)

    def consume(self, kind):
        super().consume(kind)
        self.reserve(kind)
