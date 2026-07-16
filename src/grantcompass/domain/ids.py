"""Branded persistence identifiers shared across domain modules."""

from typing import NewType

ProgramId = NewType("ProgramId", int)
NoticeVersionId = NewType("NoticeVersionId", int)
AttachmentId = NewType("AttachmentId", int)
AssessmentId = NewType("AssessmentId", int)
ChangeSetId = NewType("ChangeSetId", int)
