"""Transaction ownership boundary for repository read methods."""

from types import TracebackType
from typing import Literal, final

from sqlalchemy.ext.asyncio import AsyncSession


@final
class RepositoryReadScope:
    """Close only an implicit transaction opened by this repository read."""

    def __init__(self, session: AsyncSession) -> None:
        """Capture whether the session has a caller-owned transaction."""
        self._session = session
        self._repository_owned = not session.in_transaction()

    async def __aenter__(self) -> None:
        """Enter without mutating a caller-owned transaction."""

    async def __aexit__(
        self,
        _exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: TracebackType | None,
    ) -> Literal[False]:
        """Roll back only the implicit transaction opened within this scope."""
        if self._repository_owned and self._session.in_transaction():
            await self._session.rollback()
        return False
