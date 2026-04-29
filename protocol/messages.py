from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum
from typing import Optional


class Decision(str, Enum):
    ALLOWED = "allowed"
    DENIED = "denied"
    UNKNOWN = "unknown"
    NON_HUMAN = "non_human"


class Role(str, Enum):
    ALLOWED = "allowed"
    RESTRICTED = "restricted"


@dataclass(frozen=True)
class AuthResult:
    decision: Decision
    name: Optional[str] = None
    similarity: Optional[float] = None
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["decision"] = self.decision.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "AuthResult":
        return cls(
            decision=Decision(d["decision"]),
            name=d.get("name"),
            similarity=d.get("similarity"),
            reason=d.get("reason"),
        )
