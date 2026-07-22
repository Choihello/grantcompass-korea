from subprocess import CompletedProcess

import anyio
import pytest

from grantcompass.reports import pdf_runtime


@pytest.mark.parametrize(
    "diagnostic",
    [
        "OSError: cannot load library 'libgobject-2.0-0': error 0x7e",
        "libgobject-2.0.so.0: cannot open shared object file: No such file or directory",
        "OSError: cannot load library 'libpango-1.0-0': module could not be found",
    ],
)
def test_known_weasyprint_native_loader_errors_are_skippable(diagnostic: str) -> None:
    # Given: a recognized native-library loader diagnostic.
    # When/Then: the runtime classifier permits only this optional-host skip family.
    assert pdf_runtime.is_recognized_weasyprint_native_loader_error(diagnostic)


@pytest.mark.parametrize(
    "diagnostic",
    [
        "ModuleNotFoundError: No module named 'tinyhtml5'",
        "SyntaxError: invalid syntax in weasyprint/__init__.py",
        "process timed out after 30 seconds",
        "OSError: cannot load library 'unrelated-extension.dll'",
    ],
)
def test_unrelated_weasyprint_import_errors_are_not_skippable(diagnostic: str) -> None:
    # Given: packaging, syntax, timeout, or unrelated loader diagnostics.
    # When/Then: they remain release failures rather than optional-environment skips.
    assert not pdf_runtime.is_recognized_weasyprint_native_loader_error(diagnostic)


@pytest.mark.anyio
async def test_weasyprint_import_probe_timeout_is_a_hard_failure() -> None:
    # Given: an import subprocess runner that never completes.
    async def blocking_runner(argv: tuple[str, ...]) -> CompletedProcess[bytes]:
        del argv
        await anyio.sleep_forever()
        raise AssertionError

    # When/Then: the finite probe raises timeout instead of producing a skippable diagnostic.
    with pytest.raises(TimeoutError):
        _ = await pdf_runtime.probe_weasyprint_module(
            process_runner=blocking_runner,
            timeout_seconds=0.01,
        )


@pytest.mark.anyio
async def test_immediate_native_loader_diagnostic_remains_classifiable() -> None:
    # Given: an import runner returning a recognized native-loader diagnostic immediately.
    diagnostic = "cannot load library 'libgobject-2.0-0': error 0x7e"

    async def native_failure_runner(argv: tuple[str, ...]) -> CompletedProcess[bytes]:
        return CompletedProcess(argv, 1, b"", diagnostic.encode())

    # When: the finite probe records the completed process stderr.
    observed = await pdf_runtime.probe_weasyprint_module(
        process_runner=native_failure_runner,
        timeout_seconds=0.1,
    )

    # Then: only the immediate recognized output remains eligible for the optional skip.
    assert observed == diagnostic
    assert pdf_runtime.is_recognized_weasyprint_native_loader_error(observed)
