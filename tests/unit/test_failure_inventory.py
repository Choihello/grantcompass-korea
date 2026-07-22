from grantcompass.web.failures import FailureEntry, FailureSnapshot


def test_failure_inventory_derives_hidden_recognized_candidates() -> None:
    # Given: two recognized persisted candidates but guidance for only one.
    visible = FailureEntry("visible_failure", "Visible", "Review it")

    # When: the complete candidate inventory is resolved into a snapshot.
    snapshot = FailureSnapshot.from_inventory(
        candidate_ids=("visible_failure", "recognized_without_mapping"),
        visible_entries=(visible,),
    )

    # Then: the deliberately omitted mapping is explicit rather than silently discarded.
    assert snapshot.entries == (visible,)
    assert snapshot.visible_failure_ids == ("visible_failure",)
    assert snapshot.hidden_failures == ("recognized_without_mapping",)


def test_empty_failure_inventory_has_no_visible_or_hidden_failures() -> None:
    # Given: no recognized persisted failure candidates.
    # When: the inventory is resolved.
    snapshot = FailureSnapshot.from_inventory(candidate_ids=(), visible_entries=())

    # Then: both externally reported collections are empty by derivation.
    assert snapshot.visible_failure_ids == ()
    assert snapshot.hidden_failures == ()
