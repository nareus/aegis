"""Source protocol and result types for data fetchers."""

from dataclasses import dataclass
from typing import Protocol, Any


@dataclass
class SourceResult:
    """Result of a source fetch -- either data or an error."""

    source: str
    ok: bool
    data: Any | None = None
    error: str | None = None


class Source(Protocol):
    """Protocol that all source clients must implement."""

    name: str

    async def fetch(self) -> SourceResult: ...
