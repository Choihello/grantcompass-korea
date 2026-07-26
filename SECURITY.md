# Security policy

## Reporting a vulnerability

Do not disclose vulnerabilities, credentials, personal information, or private business data in a public issue. Use the repository host's private vulnerability-reporting channel when available. If it is unavailable, contact a maintainer privately through the contact method published on the repository profile and request a secure reporting channel.

Include the affected version or commit, reproduction steps, impact, and a minimal proof of concept. Redact API keys, authentication headers, cookies, personal information, and private source documents. Maintainers will acknowledge the report, coordinate remediation, and arrange public disclosure after affected users have a reasonable opportunity to update.

## Exposed API keys

If an API key may have been exposed:

1. Revoke or rotate it immediately with the issuing service.
2. Remove it from local files, logs, fixtures, screenshots, and build artifacts.
3. Report the exposure privately using the process above; do not paste the key into the report.
4. Review access logs and limit the replacement key to the minimum required scope.

`.env` is ignored by Git. `.env.example` contains variable names only and must never contain working credentials.

## Personal information

Report suspected personal-information exposure privately and identify the affected file, field, or endpoint without repeating the sensitive value. Maintainers will restrict access, preserve only non-sensitive diagnostic evidence, remove the data from distributed artifacts, and assess required notifications under applicable policy and law.

Applicant profiles are a business-fact whitelist. Resident registration numbers, bank accounts,
phone numbers, personal email fields, and all other undeclared fields are rejected. Do not place
personal or secret values inside generic performance/history data, institution notes, filenames,
screenshots, source fixtures, or reports. Distributed demo values must be conspicuously synthetic.

## Trust boundaries

Official-source responses, announcement text, HWPX/PDF content, OCR output, upload filenames, and
URLs are untrusted data. They never authorize tools, imports, shell commands, URL visits, or prompt
instructions. The application blocks XML DTD/entity expansion, unsafe archive paths, report HTML
resource references, credential-bearing redirects, unsupported uploads, oversized content, and
unbounded OCR/PDF work. Supported deterministic rule syntax may be recognized, but the surrounding
text remains data.

K-Startup `serviceKey` and 기업마당 `crtfcKey` query values are centrally redacted from standard
HTTP request logs. Redaction is defense in depth: keep INFO request logs access-controlled and
never intentionally log or paste credentials.

## Deployment boundary

Version 0.1 is self-hosted and has no built-in user authentication, authorization, TLS termination,
backup service, or secret manager. Bind the web server to loopback by default. Any networked use
must add an authenticated reverse proxy, TLS, host firewall rules, least-privilege file access, and
tested SQLite/report/upload backup and recovery. Consultation reports and audit logs may reveal
private business facts even when profiles contain no direct personal fields.

The application defaults to loopback-only host and origin allowlists, rejects mutation origins
outside the configured exact-origin set, and requires a signed per-browser-session CSRF token on
every POST. Non-loopback deployments must explicitly configure exact public hosts and origins,
share a random `GRANTCOMPASS_CSRF_SIGNING_SECRET` of at least 32 characters across workers, preserve
`Host` and `Origin` through the proxy, and restrict trusted proxy-header senders to the proxy
address. Wildcard hosts or origins defeat this boundary and are unsupported.

`/health/failures` is an operator diagnostic endpoint. Do not expose it publicly; monitor that its
`hidden_failures` list remains empty and investigate every visible stable error ID.

## Supported versions

Security fixes are provided only on the latest 0.1.x release line.
