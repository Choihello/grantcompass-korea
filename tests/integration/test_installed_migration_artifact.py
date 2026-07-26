import os
import shutil
import sys
from pathlib import Path
from typing import ClassVar

import anyio
import pytest

ROOT = Path(__file__).parents[2]


class _UvExecutableRequiredError(RuntimeError):
    _MESSAGE: ClassVar[str] = "uv executable is required for installed-artifact verification"

    def __init__(self) -> None:
        super().__init__(self._MESSAGE)


def _uv_executable() -> str:
    discovered = shutil.which("uv")
    if discovered is not None:
        return discovered
    bundled = ROOT / ".tools" / "uv-dist" / "uv.exe"
    if bundled.is_file():
        return str(bundled)
    raise _UvExecutableRequiredError


async def _run(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str] | None = None,
) -> str:
    completed = await anyio.run_process(
        command,
        cwd=cwd,
        env=environment,
        check=True,
    )
    return completed.stdout.decode("utf-8").strip()


@pytest.mark.anyio
async def test_wheel_only_install_can_upgrade_and_check_packaged_migrations(
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "artifacts"
    install_dir = tmp_path / "installed"
    run_dir = tmp_path / "runtime"
    artifact_dir.mkdir()
    install_dir.mkdir()
    run_dir.mkdir()
    uv = _uv_executable()

    _ = await _run([uv, "build", "--wheel", "--out-dir", str(artifact_dir)], cwd=ROOT)
    wheel = next(artifact_dir.glob("*.whl"))
    _ = await _run(
        [
            uv,
            "pip",
            "install",
            "--python",
            sys.executable,
            "--target",
            str(install_dir),
            "--no-deps",
            str(wheel),
        ],
        cwd=run_dir,
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(install_dir)
    config_path = await _run(
        [
            sys.executable,
            "-c",
            (
                "from grantcompass.migration_resources import packaged_alembic_config;"
                "print(packaged_alembic_config())"
            ),
        ],
        cwd=run_dir,
        environment=environment,
    )
    assert Path(config_path).is_relative_to(install_dir)

    _ = await _run(
        [sys.executable, "-m", "alembic", "-c", config_path, "upgrade", "head"],
        cwd=run_dir,
        environment=environment,
    )
    output = await _run(
        [sys.executable, "-m", "alembic", "-c", config_path, "check"],
        cwd=run_dir,
        environment=environment,
    )

    assert output == "No new upgrade operations detected."
    assert (run_dir / "grantcompass.db").is_file()
