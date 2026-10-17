# User and administrator runbook

## User flow

The first owner opens `/start` through the private operator connection before public ingress
is enabled and must use the configured master email in production. The email is not a bootstrap
secret; follow the private initialization order in `docs/DEPLOYMENT.md`. Every
later user needs an email invitation. Invitation links expire after 2 hours and work once. The
new user chooses a password, currency, locale and timezone, then creates the first account.

Normal work remains: record income/expense/transfer, configure recurring entries or deposits,
review reconciled analytics, run deterministic forecasts, create goals, and optionally request
an LLM explanation. Advice is optional and never writes the ledger.

Manual acceptance paths (use a disposable local database):

1. `/start`: create the master, choose currency/timezone, create a bank account with opening
   balance `10000.00 RUB`; confirm the dashboard shows that exact amount.
2. **Операции**: create an expense category and spend `125.25 RUB`; confirm `9874.75 RUB` on the
   account, an expense posting in the journal, and the same change in reports/forecast.
3. **Регулярные**: preview a monthly subscription in the profile timezone, create it, inspect
   the next local/UTC occurrence and pause/resume. Reprocessing one occurrence must not duplicate it.
4. **Вклады**: create terms with month-end capitalization and a linked account, add a cashflow,
   inspect the daily schedule, projected maturity and actual/planned reconciliation.
5. **Прогноз**: select a date, save an income/expense scenario, compare with the baseline; verify
   that the current account balance and transaction journal did not change.
6. **Цели**: add a dated target, review required contribution, gap, shortfall and priority;
   verify that saving a goal did not post a transaction.
7. **Совет**: request an explanation, inspect evidence/confidence and compare the ledger before
   and after. With provider disabled, the page must show a usable optional-provider state.

The automated release walkthrough is `scripts/release_smoke.py`; it deliberately needs an
empty database because onboarding is single-use. Independent manual sign-off on the chosen
public host remains a deployment checklist item.

If a password is forgotten, open `/reset-password` and enter the email. The response is always
the same, including for an unknown or disabled account. A delivered reset link expires after 15
minutes and works once; success revokes all prior sessions. Email-verification links expire
after 30 minutes and also work once. Open the link and press **Подтвердить адрес**; merely
opening it does not consume the token. Invitation acceptance already proves email ownership.

## Access administration

Master and admin users open **Доступ** in the sidebar. Enter an email to add/reactivate its
allowlist record and issue an invitation. Only master can check the admin-role option. The UI
shows active/revoked allowlist entries and invitation state.

Revoking an allowlist entry blocks the matching non-master account, revokes its sessions and
unused links, and revokes outstanding invitations. It does not delete the user, audit events,
accounts, transactions, postings, forecasts, goals or other financial records. Re-adding the
same email reactivates the existing account; it does not create a second tenant.

Mail-catcher for local verification:

```text
docker compose --profile mail-catcher up --build --wait
```

Open <http://localhost:8025>. Do not use Mailpit on a public server. For real SMTP, monitor the
worker and the `email_delivery_jobs` pending/dead-letter counts in PostgreSQL without copying
recipient addresses or message bodies into tickets. A completed delivery clears the stored raw
message body; failed jobs store only a bounded exception class.
Final failure, expired links and consumed/revoked links clear the body as well. SMTP delivery
is at-least-once: a crash after relay acceptance may deliver the same one-time link twice.
Protect pending-job database backups as secrets and reissue a new invitation after dead-letter.

## Operational triage

- API not ready: inspect PostgreSQL and migration completion, then the API healthcheck. Optional
  SMTP/LLM failures do not block core readiness.
- Invitation not received: confirm allowlist is active, invitation is unexpired, worker is
  healthy and SMTP relay accepts the configured sender. Reissue a new invitation instead of
  extending or reusing a link.
- Suspected link theft/replay: revoke the allowlist entry or rotate the email-token secret using
  `docs/SECURITY.md`; preserve the append-only audit rows.
- User removed accidentally: re-add the exact normalized email. Financial data should still be
  present; verify account/transaction counts before restoring access.
- Recovery/rollback: use `docs/BACKUP_AND_RECOVERY.md` and `docs/DEPLOYMENT.md`; restore into a
  new database, never over the source.
