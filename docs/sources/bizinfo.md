# 기업마당 source contract

- Confirmation date: 2026-07-15
- Official documentation: `https://www.bizinfo.go.kr/apiDetail.do?id=bizinfoApi`
- Official API catalogue: `https://www.bizinfo.go.kr/apiList.do`
- Provider: 기업마당
- Protocol: REST over HTTPS

## Contract scope

GrantCompass Korea 0.1 plans to collect current support-program announcements from the 지원사업정보 API. The source adapter will consume announcement identifiers, titles, summaries, application periods, target descriptions, responsible organizations, official announcement URLs, and attachment metadata exposed by that contract. JSON is the planned response representation.

The separate 행사정보 API and other 기업마당 services are outside the 0.1 contract. They require a separate provenance review before use.

## Planned operation

- Method: `GET`
- Endpoint: `https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do`
- Planned representation parameter: `dataType=json`
- Authentication: 기업마당 service key in `crtfcKey`
- Pagination contract: `pageUnit` and `pageIndex`

The implementation must derive filters, pagination, and response fields from the official specification confirmed above. Credentials and live responses containing sensitive values must not be committed as fixtures or logs.
