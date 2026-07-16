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
from grantcompass.sources.bizinfo import BizinfoAdapter
from grantcompass.sources.kstartup import KStartupAdapter

_KSTARTUP_KEY_ENV: Final = "GRANTCOMPASS_KSTARTUP_SERVICE_KEY"
_BIZINFO_KEY_ENV: Final = "GRANTCOMPASS_BIZINFO_SERVICE_KEY"
_SOURCE_MESSAGE: Final = "source must be kstartup or bizinfo"


async def _smoke_kstartup(service_key: SecretStr) -> None:
    async with create_async_client() as client:
        page = await KStartupAdapter(client, service_key).fetch_page(1, 1)
    typer.echo(f"OK kstartup: items={len(page.items)} hash={page.response_hash[:8]}")


async def _smoke_bizinfo(service_key: SecretStr) -> None:
    async with create_async_client() as client:
        page = await BizinfoAdapter(client, service_key).fetch_page(1, 1)
    typer.echo(f"OK bizinfo: items={len(page.items)} hash={page.response_hash[:8]}")


def main(
    source: Annotated[str, typer.Option(help="Official source to check.")] = "kstartup",
) -> None:
    """Run one selected source check with a bounded first-page request."""
    if source not in {"kstartup", "bizinfo"}:
        raise typer.BadParameter(_SOURCE_MESSAGE)
    key_env = _KSTARTUP_KEY_ENV if source == "kstartup" else _BIZINFO_KEY_ENV
    key = os.environ.get(key_env)
    if key is None or not key.strip():
        typer.echo(f"SKIP {source}: key missing")
        return
    smoke = _smoke_kstartup if source == "kstartup" else _smoke_bizinfo
    anyio.run(smoke, SecretStr(key.strip()))


if __name__ == "__main__":
    typer.run(main)
