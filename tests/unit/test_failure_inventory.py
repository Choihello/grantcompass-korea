import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.web.failures import load_failure_snapshot

pytestmark = pytest.mark.anyio


async def test_clean_persisted_state_has_no_failure_candidates(
    db_session: AsyncSession,
) -> None:
    # Given: a real empty database with no persisted failure-bearing rows.
    # When: the production inventory audits the database.
    snapshot = await load_failure_snapshot(db_session)

    # Then: both externally reported collections are empty by derivation.
    assert snapshot.visible_failure_ids == ()
    assert snapshot.hidden_failures == ()
