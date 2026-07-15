"""Official K-Startup announcement source adapter."""

from hashlib import sha256
from typing import Final, final

import httpx2
from pydantic import HttpUrl, SecretStr, TypeAdapter, ValidationError

from grantcompass.domain.enums import SourceName
from grantcompass.sources.base import SourceContractError, SourcePage, SourceTransportError
from grantcompass.sources.kstartup_contract import parse_kstartup_page

_OFFICIAL_HOST: Final = "apis.data.go.kr"
_OFFICIAL_PATH: Final = "/B552735/kisedKstartupService01"
_DEFAULT_BASE_URL: Final = f"https://{_OFFICIAL_HOST}{_OFFICIAL_PATH}"
_OPERATION: Final = "getAnnouncementInformation01"
_ENDPOINT: Final = f"{_DEFAULT_BASE_URL}/{_OPERATION}"
_MAX_PAGE_SIZE: Final = 100
_HTTPS_PORT: Final = 443


@final
class KStartupAdapter:
    """Fetch announcements from the current official K-Startup API."""

    name = SourceName.KSTARTUP

    def __init__(
        self,
        client: httpx2.AsyncClient,
        service_key: SecretStr,
        base_url: str = _DEFAULT_BASE_URL,
    ) -> None:
        """Bind a caller-owned client after pinning its credential destination."""
        _validate_official_base(base_url)
        self._client = client
        self._service_key = service_key

    async def fetch_page(self, page: int, page_size: int) -> SourcePage:
        """Fetch one page of official announcements without following redirects."""
        if page < 1 or page_size < 1 or page_size > _MAX_PAGE_SIZE:
            raise SourceContractError(
                code="kstartup_invalid_pagination",
                message="K-Startup pagination must use page >= 1 and page size 1..100",
            )
        try:
            response = await self._client.get(
                _ENDPOINT,
                params={
                    "serviceKey": self._service_key.get_secret_value(),
                    "page": page,
                    "perPage": page_size,
                    "returnType": "json",
                },
                follow_redirects=False,
            )
        except httpx2.TransportError:
            raise SourceTransportError(
                code="kstartup_transport_error",
                message="K-Startup transport failed",
            ) from None
        if not response.is_success:
            raise SourceTransportError(
                code="kstartup_http_status",
                message=f"K-Startup returned HTTP {response.status_code}",
            )
        parsed = parse_kstartup_page(response.content)
        if parsed.page != page or parsed.per_page != page_size:
            raise SourceContractError(
                code="kstartup_pagination_mismatch",
                message="K-Startup response pagination differs from the request",
            )
        return SourcePage(
            items=parsed.notices,
            page=parsed.page,
            has_next=parsed.page * parsed.per_page < parsed.total_count,
            response_hash=sha256(response.content).hexdigest(),
        )


def _validate_official_base(base_url: str) -> None:
    try:
        value = TypeAdapter(HttpUrl).validate_python(base_url)
    except ValidationError:
        raise _invalid_base_url() from None
    path = (value.path or "").rstrip("/")
    valid_destination = (
        value.scheme == "https"
        and value.host == _OFFICIAL_HOST
        and value.port == _HTTPS_PORT
        and value.username is None
        and value.password is None
        and value.query is None
        and value.fragment is None
        and path == _OFFICIAL_PATH
    )
    if not valid_destination:
        raise _invalid_base_url()


def _invalid_base_url() -> SourceContractError:
    return SourceContractError(
        code="kstartup_invalid_base_url",
        message="K-Startup base URL must be the pinned official HTTPS service",
    )
