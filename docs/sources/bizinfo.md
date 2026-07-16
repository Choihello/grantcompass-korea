# 기업마당 source contract

- Confirmation date: 2026-07-15
- Official documentation: `https://www.bizinfo.go.kr/apiDetail.do?id=bizinfoApi`
- Official API catalogue: `https://www.bizinfo.go.kr/apiList.do`
- Provider: 기업마당
- Protocol: REST over HTTPS

## Contract scope

GrantCompass Korea 0.1 collects current support-program announcements from the 지원사업정보 API. The adapter consumes announcement identifiers, titles, summaries, application periods, responsible organizations, official announcement URLs, and attachment metadata exposed by that contract. JSON is the response representation.

The separate 행사정보 API and other 기업마당 services are outside the 0.1 contract. They require a separate provenance review before use.

## Planned operation

- Method: `GET`
- Endpoint: `https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do`
- Representation parameter: `dataType=json`
- Authentication: 기업마당 service key in `crtfcKey`
- Pagination contract: `pageUnit` and `pageIndex`

The official page was rechecked on 2026-07-16. It identifies the operation as GET,
shows a last-modified date of 2025-10-22, and documents `jsonArray.item` plus
`pblancId`, `pblancNm`, `jrsdInsttNm`, `bsnsSumryCn`, `reqstBeginEndDe`,
`pblancUrl`, `flpthNm`, `fileNm`, and `totCnt`. An item may be an array, a single
object, or `null`; the adapter handles all three without treating source errors as
empty results.

## Safety and verification

The credential is sent only to the exact HTTPS origin and path above. User info,
alternate ports, query strings, fragments, other hosts or paths are rejected before
transport, and redirects are never followed for the credential-bearing request.
Fixtures are fictional examples of the documented shape and contain neither service
keys nor copied live announcements. The complete item remains in the immutable raw
payload while promoted fields are validated separately.

A bounded live check runs only when `GRANTCOMPASS_BIZINFO_SERVICE_KEY` is present:

```bash
uv run python scripts/smoke_live_sources.py --source bizinfo
```

Without a key it prints only a skip status. With a key it prints only item count and
the first eight response-hash characters; credentials and notice payloads are never
printed.

The implementation must derive filters, pagination, and response fields from the official specification confirmed above. Credentials and live responses containing sensitive values must not be committed as fixtures or logs.
