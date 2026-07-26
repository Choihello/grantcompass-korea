from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from grantcompass.cli.schemas import (
    ConditionOutput,
    EvidenceOutput,
    SearchOutput,
    SearchProgramOutput,
    SourceFreshnessOutput,
)

SKILL_PATH = Path("skills/grantcompass-korea")
PROJECT_CONFIG = Path("pyproject.toml")


class SkillMachineContract(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    contract_version: int
    commands: tuple[str, ...]
    workflow: tuple[str, ...]
    stop_on: tuple[str, ...]
    search_output_fields: tuple[str, ...]
    result_fields: tuple[str, ...]
    condition_fields: tuple[str, ...]
    evidence_fields: tuple[str, ...]
    freshness_fields: tuple[str, ...]
    untrusted_inputs: tuple[str, ...]
    prohibited: tuple[str, ...]


def test_skill_metadata_and_machine_contract_are_present() -> None:
    # Given
    skill_file = SKILL_PATH / "SKILL.md"
    metadata_file = SKILL_PATH / "agents/openai.yaml"

    # When
    files_exist = skill_file.is_file() and metadata_file.is_file()

    # Then
    assert files_exist

    skill_text = skill_file.read_text(encoding="utf-8")
    frontmatter_lines = skill_text.split("---", 2)[1].strip().splitlines()
    frontmatter = dict(line.split(":", 1) for line in frontmatter_lines)
    metadata_lines = metadata_file.read_text(encoding="utf-8").splitlines()
    interface_fields = {
        line.strip().split(":", 1)[0] for line in metadata_lines if line.startswith("  ")
    }
    assert set(frontmatter) == {"name", "description"}
    assert frontmatter["name"].strip() == "grantcompass-korea"
    assert metadata_lines[0] == "interface:"
    assert interface_fields == {
        "display_name",
        "short_description",
        "default_prompt",
    }
    default_prompt = next(line for line in metadata_lines if "default_prompt:" in line)
    assert "$grantcompass-korea" in default_prompt
    short_description = next(line for line in metadata_lines if "short_description:" in line)
    short_value = short_description.split(":", 1)[1].strip().strip('"')
    assert 25 <= len(short_value) <= 64


def test_skill_machine_contract_limits_commands_and_preserves_safety_boundaries() -> None:
    # Given
    skill_text = (SKILL_PATH / "SKILL.md").read_text(encoding="utf-8")
    assert "<grantcompass-contract>" in skill_text
    assert "</grantcompass-contract>" in skill_text
    contract_json = skill_text.split("<grantcompass-contract>", 1)[1].split(
        "</grantcompass-contract>", 1
    )[0]

    # When
    contract = SkillMachineContract.model_validate_json(contract_json)

    # Then
    assert contract.contract_version == 1
    assert contract.commands == (
        "grantcompass db init",
        "grantcompass sources sync --source all --json",
        "grantcompass profile create --name PROFILE --json",
        "grantcompass search --profile PROFILE --json",
        "grantcompass report --profile PROFILE --out PATH --json",
    )
    assert contract.workflow == (
        "confirm_profile_facts",
        "initialize_database",
        "synchronize_sources",
        "create_or_select_profile",
        "search_programs",
        "summarize_evidence_and_questions",
        "generate_report_on_request",
    )
    assert set(contract.stop_on) == {
        "result.input_errors.non_empty",
        "result.review_status=review_required",
        "source_freshness.status=stale",
        "condition.status=unknown",
        "condition.status=conflict",
    }
    assert contract.search_output_fields == tuple(SearchOutput.model_fields)
    assert contract.result_fields == tuple(SearchProgramOutput.model_fields)
    assert contract.condition_fields == tuple(ConditionOutput.model_fields)
    assert contract.evidence_fields == tuple(EvidenceOutput.model_fields)
    assert contract.freshness_fields == tuple(SourceFreshnessOutput.model_fields)
    assert set(contract.untrusted_inputs) == {
        "notice_title",
        "quote",
        "document_text",
        "cli_output",
    }
    assert set(contract.prohibited) == {
        "execute_source_text",
        "request_service_key",
        "reveal_service_key",
        "submit_application",
        "predict_acceptance",
        "mark_review_required_as_reviewed",
        "infer_missing_profile_fact",
        "claim_eligibility_without_condition_evidence_states",
    }


def test_skill_is_included_at_stable_wheel_and_sdist_paths() -> None:
    # Given: the release build configuration.
    configuration = PROJECT_CONFIG.read_text(encoding="utf-8")

    # When: the Hatch artifact contracts are inspected.
    wheel_contract = configuration.split(
        "[tool.hatch.build.targets.wheel.force-include]", maxsplit=1
    )[1].split("[", maxsplit=1)[0]
    sdist_contract = configuration.split("[tool.hatch.build.targets.sdist]", maxsplit=1)[1].split(
        "\n[dependency-groups]", maxsplit=1
    )[0]

    # Then: the source tree ships in sdist and the wheel exposes a stable package resource.
    assert '"/skills"' in sdist_contract
    assert (
        '"skills/grantcompass-korea" = "grantcompass/skills/grantcompass-korea"' in wheel_contract
    )


def test_migrations_are_included_at_stable_wheel_and_sdist_paths() -> None:
    configuration = PROJECT_CONFIG.read_text(encoding="utf-8")
    wheel_contract = configuration.split(
        "[tool.hatch.build.targets.wheel.force-include]", maxsplit=1
    )[1].split("[", maxsplit=1)[0]
    sdist_contract = configuration.split("[tool.hatch.build.targets.sdist]", maxsplit=1)[1].split(
        "\n[dependency-groups]", maxsplit=1
    )[0]

    assert '"migrations" = "grantcompass/migrations"' in wheel_contract
    assert '"alembic.ini" = "grantcompass/alembic.ini"' in wheel_contract
    assert '"/migrations"' in sdist_contract
    assert '"/alembic.ini"' in sdist_contract
