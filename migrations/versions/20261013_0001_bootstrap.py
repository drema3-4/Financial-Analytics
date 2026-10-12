"""Establish an empty schema baseline.

Revision ID: 20261013_0001
Revises:
Create Date: 2026-10-13 00:00:00
"""

from collections.abc import Sequence

revision: str = "20261013_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create no domain tables during the bootstrap milestone."""


def downgrade() -> None:
    """Remove the empty bootstrap baseline."""
