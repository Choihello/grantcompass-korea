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

## Supported versions

Until the first stable release, security fixes are provided only on the latest 0.1 development line.
