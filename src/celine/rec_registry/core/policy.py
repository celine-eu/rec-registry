from dataclasses import dataclass
from fastapi import Request


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str | None = None


class AccessPolicy:
    async def allow_admin(self, request: Request) -> Decision:
        return Decision(True)

    async def allow_write(self, request: Request) -> Decision:
        return Decision(True)
