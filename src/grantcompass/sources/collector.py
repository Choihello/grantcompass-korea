"""Failure-isolated source pagination and persistence."""

from hashlib import sha256
from typing import Final, final

from grantcompass.clock import Clock
from grantcompass.domain.enums import FreshnessStatus, SourceName
from grantcompass.domain.source_runs import SourceRunFailure, SourceRunSuccess
from grantcompass.sources.base import (
    CollectionResult,
    SourceAdapter,
    SourceContractError,
    SourcePage,
    SourceTransportError,
)
from grantcompass.storage.repositories import ProgramRepository

_UNEXPECTED_PAGE_CODE: Final = "unexpected_page"
_SOURCE_MISMATCH_CODE: Final = "source_mismatch"
_INVALID_PAGE_SIZE_CODE: Final = "invalid_page_size"
_PAGE_LIMIT_CODE: Final = "page_limit_exceeded"
_INTERNAL_ERROR_CODE: Final = "internal_collection_error"
_MAX_SOURCE_PAGES: Final = 100
_UNEXPECTED_COLLECTION_ERRORS: Final[tuple[type[Exception], ...]] = (Exception,)


@final
class Collector:
    """Collect one adapter without converting upstream failure into an empty result."""

    def __init__(self, repository: ProgramRepository, clock: Clock) -> None:
        """Bind the isolated collector to persistence and a deterministic clock."""
        self._repository: ProgramRepository = repository
        self._clock: Clock = clock

    async def collect(
        self,
        adapter: SourceAdapter,
        page_size: int = 100,
    ) -> CollectionResult:
        """Persist pages item-by-item and return a source freshness outcome."""
        run_id = await self._repository.start_source_run(adapter.name, self._clock.now())
        page_number = 1
        stored = 0
        unchanged = 0
        response_hashes: list[str] = []
        try:
            while True:
                _validate_collection_request(page_number, page_size)
                page = await adapter.fetch_page(page_number, page_size)
                _validate_page(page, page_number, adapter.name)
                response_hashes.append(page.response_hash)
                for notice in page.items:
                    result = await self._repository.upsert_notice(notice, self._clock.now())
                    if result.notice_version_created:
                        stored += 1
                    else:
                        unchanged += 1
                if not page.has_next:
                    break
                page_number += 1
        except (SourceContractError, SourceTransportError) as error:
            response_hash = _combined_response_hash(response_hashes)
            await self._repository.fail_source_run(
                run_id,
                SourceRunFailure(
                    finished_at=self._clock.now(),
                    item_count=stored + unchanged,
                    response_hash=response_hash,
                    error_code=error.code,
                    error_message=error.message,
                ),
            )
            return CollectionResult(
                source=adapter.name,
                stored=stored,
                unchanged=unchanged,
                failed=1,
                freshness=FreshnessStatus.STALE,
                error_code=error.code,
                error_message=error.message,
            )
        except _UNEXPECTED_COLLECTION_ERRORS as error:
            response_hash = _combined_response_hash(response_hashes)
            try:
                await self._repository.fail_source_run(
                    run_id,
                    SourceRunFailure(
                        finished_at=self._clock.now(),
                        item_count=stored + unchanged,
                        response_hash=response_hash,
                        error_code=_INTERNAL_ERROR_CODE,
                        error_message="unexpected collection failure",
                    ),
                )
            finally:
                raise error

        response_hash = _combined_response_hash(response_hashes)
        await self._repository.complete_source_run(
            run_id,
            SourceRunSuccess(
                finished_at=self._clock.now(),
                item_count=stored + unchanged,
                response_hash=response_hash,
            ),
        )
        return CollectionResult(
            source=adapter.name,
            stored=stored,
            unchanged=unchanged,
            failed=0,
            freshness=FreshnessStatus.FRESH,
        )


def _combined_response_hash(response_hashes: list[str]) -> str | None:
    if not response_hashes:
        return None
    return sha256("\x1f".join(response_hashes).encode()).hexdigest()


def _validate_page(page: SourcePage, expected_page: int, source: SourceName) -> None:
    if page.page != expected_page:
        raise SourceContractError(
            code=_UNEXPECTED_PAGE_CODE,
            message=f"expected page {expected_page}, received {page.page}",
        )
    if any(notice.source is not source for notice in page.items):
        raise SourceContractError(
            code=_SOURCE_MISMATCH_CODE,
            message="notice source differs from adapter source",
        )


def _validate_collection_request(page_number: int, page_size: int) -> None:
    if page_size <= 0:
        raise SourceContractError(
            code=_INVALID_PAGE_SIZE_CODE,
            message="page size must be positive",
        )
    if page_number > _MAX_SOURCE_PAGES:
        raise SourceContractError(
            code=_PAGE_LIMIT_CODE,
            message=f"source exceeded {_MAX_SOURCE_PAGES} pages",
        )
