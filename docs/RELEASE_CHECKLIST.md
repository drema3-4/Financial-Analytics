# Release checklist — 0.2.0 proposal

Proposed semantic version and tag: `0.2.0` / `v0.2.0`. This is a pre-1.0 feature release adding
invite-only multi-user deployment. Operators must select an explicit Compose profile and provide
the new production settings; see `CHANGELOG.md`. Creating or pushing the tag is intentionally
outside this milestone and requires explicit authorization.

## Build and evidence

- [x] Working tree contains only the stage-13 change and no secrets, databases, model weights,
  reports, caches or local environment files.
- [x] Poetry lock, Ruff check/format, strict mypy, OpenAPI/client drift and full pytest coverage
  gate pass.
- [x] ESLint, Prettier, strict TypeScript, Vitest coverage and production web build pass.
- [x] Clean migration upgrade, current-head, metadata drift and downgrade drill pass on
  PostgreSQL 18.
- [x] `core`, `mail-catcher`, `local-llm`, and production overlay Compose models render.
- [x] Fresh-clone core walkthrough covers onboarding, operation, forecast, goal and optional
  advice; mail delivery and token replay are checked.
- [x] GPU-local vLLM starts and answers its healthcheck when compatible GPU capacity is
  available; a hardware limitation is recorded honestly rather than masking core success.
- [x] Production-like stack starts with safe settings, has no published ports, and rejects each
  unsafe production configuration in the settings test matrix.
- [x] Local backup/restore evidence is current at revision `20261016_0011`.
- [x] Backend/web runtime and repository scans found no High/Critical findings or secrets.

## Release and deploy

- [ ] Build backend and web images from the milestone commit; compile the real HTTPS API origin
  into the web image.
- [ ] Scan images and repository; record immutable image digests and SBOM.
- [ ] Scan selected upstream runtime images, including optional vLLM when enabled, before
  public deployment; the milestone runtime scan covers the two application images.
- [ ] Review `CHANGELOG.md`, `STATUS.md`, API contract, deployment guide and user/admin runbook.
- [ ] Create signed/annotated `v0.2.0` only after approval; do not move an existing tag.
- [ ] Push images/tag and deploy only after explicit approval, a selected domain/host, DNS and
  TLS ownership, SMTP credentials, tested backup, and a maintenance/rollback window.
- [ ] Record the backup/rollback operator and verify the off-host schedule and retention.
- [ ] Independently sign off all seven manual paths in `docs/RUNBOOK.md` on the chosen host.
- [ ] After deployment: verify HTTPS redirect, certificate chain, forwarded client IP handling,
  exact CORS, cookie attributes, master bootstrap, invitation delivery, replay rejection,
  readiness, metrics and a read-only financial reconciliation.
