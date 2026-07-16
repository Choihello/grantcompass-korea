"""Credential-safe official Bizinfo source boundary."""

from hashlib import sha256
from typing import Final, final

import httpx2
from pydantic import HttpUrl, SecretStr, TypeAdapter, ValidationError

from grantcompass.domain.enums import SourceName
from grantcompass.sources.base import SourceContractError, SourcePage, SourceTransportError
from grantcompass.sources.bizinfo_contract import parse_bizinfo_page

_OFFICIAL_HOST: Final = "www.bizinfo.go.kr"
_OFFICIAL_PATH: Final = "/uss/rss/bizinfoApi.do"
_ENDPOINT: Final = f"https://{_OFFICIAL_HOST}{_OFFICIAL_PATH}"
_MAX_PAGE_SIZE: Final = 100
_HTTPS_PORT: Final = 443


@final
class BizinfoAdapter:
    """Fetch support-program notices from the pinned official Bizinfo API."""

    name = SourceName.BIZINFO

    def __init__(
        self,
        client: httpx2.AsyncClient,
        service_key: SecretStr,
        base_url: str = _ENDPOINT,
    ) -> None:
        """Bind a caller-owned client after validating the credential destination."""
        _validate_official_base(base_url)
        self._client = client
        self._service_key = service_key

    async def fetch_page(self, page: int, page_size: int) -> SourcePage:
        """Fetch and validate one bounded official JSON page."""
        if page < 1 or page_size < 1 or page_size > _MAX_PAGE_SIZE:
            raise SourceContractError(
                code="bizinfo_invalid_pagination",
                message="Bizinfo pagination must use page >= 1 and page size 1..100",
            )
        try:
            response = await self._client.get(
                _ENDPOINT,
                params={
                    "crtfcKey": self._service_key.get_secret_value(),
                    "dataType": "json",
                    "pageIndex": page,
                    "pageUnit": page_size,
                },
                follow_redirects=False,
            )
        except httpx2.TransportError:
            raise SourceTransportError(
                code="bizinfo_transport_error",
                message="Bizinfo transport failed",
            ) from None
        if not response.is_success:
            raise SourceTransportError(
                code="bizinfo_http_status",
                message=f"Bizinfo returned HTTP {response.status_code}",
            )
        parsed = parse_bizinfo_page(response.content)
        return SourcePage(
            items=parsed.notices,
            page=page,
            has_next=page * page_size < parsed.total_count,
            response_hash=sha256(response.content).hexdigest(),
        )


def _validate_official_base(base_url: str) -> None:
    try:
        value = TypeAdapter(HttpUrl).validate_python(base_url)
    except ValidationError:
        raise _invalid_base_url() from None
    valid_destination = (
        value.scheme == "https"
        and value.host == _OFFICIAL_HOST
        and value.port == _HTTPS_PORT
        and value.username is None
        and value.password is None
        and value.query is None
        and value.fragment is None
        and value.path == _OFFICIAL_PATH
    )
    if not valid_destination:
        raise _invalid_base_url()


def _invalid_base_url() -> SourceContractError:
    return SourceContractError(
        code="bizinfo_invalid_base_url",
        message="Bizinfo base URL must be the pinned official HTTPS endpoint",
    )
