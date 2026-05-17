"""MAGI agent implementations."""

from magi_spec.agents.balthasar import BalthasarAgent
from magi_spec.agents.casper import CasperAgent
from magi_spec.agents.conflict_resolver import ConflictResolver
from magi_spec.agents.critical_reporter import CriticalReporter
from magi_spec.agents.melchior import MelchiorAgent
from magi_spec.agents.spec_composer import SpecComposer

__all__ = [
    "BalthasarAgent",
    "CasperAgent",
    "ConflictResolver",
    "CriticalReporter",
    "MelchiorAgent",
    "SpecComposer",
]
