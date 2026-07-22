from pathlib import Path


def test_cron_example_creates_log_directory_before_redirection() -> None:
    # Given: the release README cron example.
    readme = Path("README.md").read_text(encoding="utf-8")

    # When: its executable cron line is selected.
    cron_line = next(line for line in readme.splitlines() if "var/sync.log" in line)

    # Then: the log parent exists before the shell opens the redirect target.
    assert "mkdir -p var &&" in cron_line
    assert cron_line.index("mkdir -p var") < cron_line.index(">> var/sync.log")
