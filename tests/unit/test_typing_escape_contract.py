import ast
import io
import tokenize
from pathlib import Path

ROOT = Path(__file__).parents[2]
PYTHON_ROOTS = (ROOT / "src", ROOT / "tests")
PROHIBITED_NAMES = frozenset({"Any", "object", "cast"})
PROHIBITED_COMMENT_MARKERS = ("type: ignore", "pyright: ignore", "noqa")


def test_tracked_python_has_no_typing_escape_hatches() -> None:
    violations: list[str] = []
    for python_root in PYTHON_ROOTS:
        for path in sorted(python_root.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id in PROHIBITED_NAMES:
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}:{node.id}")
                if (
                    isinstance(node, ast.Attribute)
                    and node.attr in PROHIBITED_NAMES
                    and isinstance(node.value, ast.Name)
                    and node.value.id in {"typing", "builtins"}
                ):
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}:{node.attr}")
            tokens = tokenize.generate_tokens(io.StringIO(source).readline)
            violations.extend(
                f"{path.relative_to(ROOT)}:{token.start[0]}:{token.string.strip()}"
                for token in tokens
                if token.type == tokenize.COMMENT
                and any(marker in token.string.casefold() for marker in PROHIBITED_COMMENT_MARKERS)
            )

    assert violations == []
