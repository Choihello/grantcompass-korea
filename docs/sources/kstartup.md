# K-Startup source contract

- Confirmation date: 2026-07-15
- Official metadata modified: 2025-06-19
- Public Data Portal dataset ID: `15125364`
- Official documentation: `https://www.data.go.kr/data/15125364/openapi.do`
- Provider: 창업진흥원 via 공공데이터포털
- Protocol: REST over HTTPS
- Representation used by GrantCompass: JSON (`returnType=json`)
- Access: 활용신청 required; development and production applications are auto-approved
- Authentication: issued 공공데이터포털 service key required

## Contract scope

GrantCompass Korea 0.1 plans to collect K-Startup support-program announcements only. The source adapter will consume announcement identifiers, titles, summaries, application periods and methods, target descriptions, contact information, and official links or attachment metadata exposed by the documented announcement operation.

The statistical-report, content, and integrated-business operations published under the same service are outside the 0.1 K-Startup contract. They require a separate provenance review before use.

## Verified operation

- Base URL: `https://apis.data.go.kr/B552735/kisedKstartupService01`
- Method and operation: `GET /getAnnouncementInformation01`
- Full endpoint: `https://apis.data.go.kr/B552735/kisedKstartupService01/getAnnouncementInformation01`
- Authentication: 공공데이터포털 service key
- Required query: `serviceKey`
- Pagination queries: `page`, `perPage`
- Representation query: `returnType=json`

The current Swagger success root contains `currentCount`, `data`, `matchCount`, `page`,
`perPage`, and `totalCount`; announcement items are the array at `data.data[]`. Documented
error responses use HTTP 401 and 500. This contract has no legacy
`response.header/body/resultCode` wrapper.

The adapter promotes `pbanc_sn`, `biz_pbanc_nm`, `pbanc_ntrp_nm`, `pbanc_ctnt`,
`pbanc_rcpt_bgng_dt`, `pbanc_rcpt_end_dt`, and `biz_aply_url`. In the current official
semantics, `biz_aply_url` is the announcement detail URL used by `RawNotice.detail_url`;
`detl_pg_url` is an application URL and remains only in the immutable raw payload until the
domain has a distinct application-URL field. `aply_trgt_ctnt` is target information, not the
summary. The operation does not document `atch_file_url` or `file_nm`, so K-Startup notices
do not invent attachment records.

The credential destination is pinned to the exact HTTPS host and service path above. The
adapter rejects userinfo, non-default ports, query, fragment, other hosts, and other paths
before storing the client or key. Redirect following is disabled for each request and every
3xx response is a stable source failure.

The official API requires `serviceKey` in the query. A centralized, stateless httpx2 log filter
redacts `serviceKey` and 기업마당 `crtfcKey` values without temporarily changing the process-wide
logger level. Concurrent credential-bearing request logs are covered by a regression test.
Deployments must still restrict log access and never intentionally record credentials.

## Retired predecessor

The former `창업진흥원_창업지원공고(K-Startup)` API is prohibited. The official
[retirement notice](https://www.data.go.kr/bbs/ntc/selectNotice.do?atchFileId=&nttApiYn=Y&originId=NOTICE_0000000003509&pageIndex=1&searchCondition2=2&searchKeyword1=)
was published on 2024-03-08 and directs users to reapply for the current dataset above.
No retired host, route, parameter, or response model may be added to the adapter.

## Verification fixtures

The repository stores fictional examples using the exact documented field names and response
shape rather than credentials or copied live payloads. List, empty-list, malformed root/data,
invalid JSON, HTTP 401/500, timeout, redirect, and total-count pagination behavior are
exercised at the caller-supplied HTTP transport boundary. A live smoke check runs only when
`GRANTCOMPASS_KSTARTUP_SERVICE_KEY` contains a non-whitespace key and prints only the item
count and the first eight response-hash characters.

The implementation must derive request parameters and response fields from the official specification confirmed above. Credentials and live responses containing sensitive values must not be committed as fixtures or logs.
