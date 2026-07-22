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
