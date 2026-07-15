# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
# How to run: uv run python scripts/smoke_live_sources.py --source kstartup
"""Run bounded live-source checks without printing credentials or notice payloads."""

import os
from typing import Annotated, Final

import anyio
import typer
from pydantic import SecretStr

from grantcompass.http import create_async_client
from grantcompass.sources.kstartup import KStartupAdapter

_KEY_ENV: Final = "GRANTCOMPASS_KSTARTUP_SERVICE_KEY"
_SOURCE_MESSAGE: Final = "only kstartup is available"


async def _smoke_kstartup(service_key: SecretStr) -> None:
    async with create_async_client() as client:
        page = await KStartupAdapter(client, service_key).fetch_page(1, 1)
    typer.echo(f"OK kstartup: items={len(page.items)} hash={page.response_hash[:8]}")


def main(
    source: Annotated[str, typer.Option(help="Official source to check.")] = "kstartup",
) -> None:
    """Run one selected source check with a bounded first-page request."""
    if source != "kstartup":
        raise typer.BadParameter(_SOURCE_MESSAGE)
    key = os.environ.get(_KEY_ENV)
    if key is None:
        typer.echo("SKIP kstartup: key missing")
        return
    anyio.run(_smoke_kstartup, SecretStr(key))


if __name__ == "__main__":
    typer.run(main)
