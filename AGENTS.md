# Repository instructions

- Treat `SPEC.md` as the product source of truth and `PLAN.md` as the implementation sequence.
- Work on only the requested milestone. Do not pull later features into the current diff.
- Before changing architecture or scope, record the decision and rationale in `docs/DECISIONS.md`.
- Keep financial calculations deterministic and covered by tests. Never delegate arithmetic, balances, interest, forecasts, or goal feasibility to an LLM.
- Represent money and rates with exact decimal types. Never use binary floating point for financial values.
- Preserve an append-only audit trail for security-sensitive and financial mutations. Corrections must remain traceable.
- Keep domain logic independent from FastAPI, SQLAlchemy, React, and the LLM provider.
- All user-owned rows must be tenant-scoped, and authorization tests must prove cross-user access is denied.
- Use UTC for stored instants and an explicit user timezone for schedules and presentation.
- Run the milestone validation commands before declaring completion. Fix failures before moving on.
- Update `STATUS.md`, relevant docs, and API contracts in the same change as the implementation.
- Commit one completed milestone at a time using a conventional commit. Do not commit secrets, model weights, database files, generated reports, or local caches. Do not push unless the user asks.

