# Changelog

## [Unreleased]

### Fixed — core finance workflows (stage 14)

- Standalone deposits with opening amounts, exact percentage display, editable terms and
  automatic, idempotent compound-interest ledger postings; ordinary accounts earn no interest.
- Unified account/deposit operations; inline new/existing categories in operations and rules.
- Full operation corrections and deletion by reversal; account/deposit/goal editing and archival.
- Aligned analytics date ranges, refreshed balances, unique dialog accessibility IDs and
  timezone-correct operation dates; access to all sections on mobile.
- Tenant-scoped CRUD, concurrency, migration and real-browser regression coverage. Existing
  deposit balances are preserved; legacy automatic accrual requires owner review and opt-in.

## [0.2.0] — proposed 2026-10-17

### Added

- Invite-only multi-user access with master/admin authorization, soft-revoked allowlist,
  invitation acceptance, email verification and non-disclosing password reset.
- Durable SMTP delivery jobs with bounded retry/dead-letter behavior and local Mailpit profile.
- Explicit `core`, `mail-catcher` and `local-llm` Compose profiles plus a production overlay with
  versioned/pinned images, resource limits, restart policies and healthchecks.
- Production startup validation for HTTPS assumptions, trusted proxies, cookies, CORS, SMTP,
  bootstrap email and independent non-default secrets.
- Deployment, release, recovery, fresh-machine and user/admin operating procedures.

### Security

- One-time email links use 2-hour invitation, 30-minute verification and 15-minute reset TTLs.
- Known token replay is rejected and appended to the audit trail; successful password reset
  revokes existing sessions.
- Allowlist removal preserves all financial and audit data while disabling access.

### Changed

- Application version advanced from `0.1.0` to proposed release `0.2.0`.
- OpenAPI and the generated TypeScript client include access administration and recovery APIs.
- Compose startup now requires an explicit profile (for example `--profile core`); an old bare
  `docker compose up` command must be updated. Production adds required email/proxy/SMTP/HTTPS
  settings and rejects development defaults.
