"""Fail-closed stage decisions; evidence must belong to the current revision."""
from dataclasses import dataclass
from enum import Enum


class Status(str, Enum):
    PASS = 'PASS'
    FAIL = 'FAIL'
    NEEDS_REVIEW = 'NEEDS_REVIEW'
    UNVERIFIED = 'UNVERIFIED'
    BLOCKED = 'BLOCKED'
    NOT_IMPLEMENTED = 'NOT_IMPLEMENTED'


@dataclass(frozen=True)
class Evidence:
    check_id: str
    revision: str
    status: Status
    reference: str


@dataclass(frozen=True)
class Stage:
    id: str
    required_checks: tuple[str, ...]


def can_advance(stage: Stage, revision: str, evidence: list[Evidence]) -> bool:
    """Only one current, passing result per required check permits advancement.

    Callers must supply results from trusted server-side validators, never client
    claims. This pure policy does not itself verify or persist evidence files.
    """
    if not revision.strip() or not stage.required_checks:
        return False
    if len(set(stage.required_checks)) != len(stage.required_checks):
        return False
    for check in stage.required_checks:
        current = [e for e in evidence if e.check_id == check and e.revision == revision]
        if len(current) != 1:
            return False
        result = current[0]
        if result.status != Status.PASS or not result.reference.strip():
            return False
    return True
