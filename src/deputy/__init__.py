"""deputy: an agent runtime where autonomy is a permission, not a default.

Three things the runtime treats as first class:

  authority   Every action an agent wants to take is checked against a
              declarative policy before it runs. The engine fails closed.
              See deputy.policy.

  provenance  Every autonomous write is recorded in an append-only log that
              merges rather than conflicts, so concurrent agents cannot
              silently drop each other's history. See deputy.store.

  calibration Rubric scores produced by an agent are treated as predictions
              and measured against outcomes, so "the model rated this 87"
              can be checked rather than believed. See deputy.evals.
"""

__version__ = "0.3.0"

from deputy.policy.engine import Decision, PolicyEngine, Verdict
from deputy.runtime.agent import Agent, AgentResult
from deputy.runtime.budget import Budget, BudgetExceeded
from deputy.store.vault import Vault

__all__ = [
    "Agent",
    "AgentResult",
    "Budget",
    "BudgetExceeded",
    "Decision",
    "PolicyEngine",
    "Vault",
    "Verdict",
    "__version__",
]
