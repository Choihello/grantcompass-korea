# K-Startup source contract

- Confirmation date: 2026-07-15
- Official documentation: `https://www.data.go.kr/data/15125364/openapi.do`
- Provider: 창업진흥원 via 공공데이터포털
- Protocol: REST over HTTPS

## Contract scope

GrantCompass Korea 0.1 plans to collect K-Startup support-program announcements only. The source adapter will consume announcement identifiers, titles, summaries, application periods and methods, target descriptions, contact information, and official links or attachment metadata exposed by the documented announcement operation.

The statistical-report, content, and integrated-business operations published under the same service are outside the 0.1 K-Startup contract. They require a separate provenance review before use.

## Planned operation

- Base URL: `https://apis.data.go.kr/B552735/kisedKstartupService01`
- Method and operation: `GET /getAnnouncementInformation01`
- Full endpoint: `https://apis.data.go.kr/B552735/kisedKstartupService01/getAnnouncementInformation01`
- Authentication: 공공데이터포털 service key

The implementation must derive request parameters and response fields from the official specification confirmed above. Credentials and live responses containing sensitive values must not be committed as fixtures or logs.
