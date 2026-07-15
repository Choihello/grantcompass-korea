# K-Startup source contract

- Confirmation date: 2026-07-15
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

## Planned operation

- Base URL: `https://apis.data.go.kr/B552735/kisedKstartupService01`
- Method and operation: `GET /getAnnouncementInformation01`
- Full endpoint: `https://apis.data.go.kr/B552735/kisedKstartupService01/getAnnouncementInformation01`
- Authentication: 공공데이터포털 service key
- Request parameters: `serviceKey`, `pageNo`, `numOfRows`, `returnType=json`

The response result code is checked before `items`. Successful `items` may be an array, a
single object, or `null`. The adapter promotes `pbanc_sn`, `biz_pbanc_nm`,
`pbanc_ntrp_nm`, `pbanc_rcpt_bgng_dt`, `pbanc_rcpt_end_dt`, `detl_pg_url`,
`atch_file_url`, and `file_nm`; every item field remains in the immutable raw payload.

## Retired predecessor

The former `창업진흥원_창업지원공고(K-Startup)` API is prohibited. The official
[retirement notice](https://www.data.go.kr/bbs/ntc/selectNotice.do?atchFileId=&nttApiYn=Y&originId=NOTICE_0000000003509&pageIndex=1&searchCondition2=2&searchKeyword1=)
was published on 2024-03-08 and directs users to reapply for the current dataset above.
No retired host, route, parameter, or response model may be added to the adapter.

## Verification fixtures

The repository stores synthetic examples of the documented response shapes rather than
credentials or copied live payloads. Normal, API-error, single-item, empty, and malformed
responses are exercised at the caller-supplied HTTP transport boundary. A live smoke check
runs only when `GRANTCOMPASS_KSTARTUP_SERVICE_KEY` is present and prints only the item count
and the first eight response-hash characters.

The implementation must derive request parameters and response fields from the official specification confirmed above. Credentials and live responses containing sensitive values must not be committed as fixtures or logs.
