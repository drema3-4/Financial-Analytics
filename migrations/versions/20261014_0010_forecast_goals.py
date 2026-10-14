"""Add owner-scoped forecast scenarios and financial goals.

Revision ID: 20261014_0010
Revises: 20261013_0009
Create Date: 2026-10-14 00:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261014_0010"
down_revision: str | None = "20261013_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "forecast_scenarios",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("horizon", sa.Date(), nullable=False),
        sa.Column("income_change", sa.Numeric(20, 12), nullable=False),
        sa.Column("expense_change", sa.Numeric(20, 12), nullable=False),
        sa.Column("annual_inflation", sa.Numeric(20, 12), nullable=False),
        sa.Column("annual_interest", sa.Numeric(20, 12), nullable=False),
        sa.Column(
            "one_time_cashflows",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("assumptions_version", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(btrim(name)) > 0", name="ck_forecast_scenarios_forecast_scenario_name"
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name="ck_forecast_scenarios_forecast_scenario_currency"
        ),
        sa.CheckConstraint(
            "income_change >= -1", name="ck_forecast_scenarios_forecast_scenario_income_change"
        ),
        sa.CheckConstraint(
            "expense_change >= -1", name="ck_forecast_scenarios_forecast_scenario_expense_change"
        ),
        sa.CheckConstraint(
            "annual_inflation >= 0", name="ck_forecast_scenarios_forecast_scenario_inflation"
        ),
        sa.CheckConstraint(
            "annual_interest >= 0", name="ck_forecast_scenarios_forecast_scenario_interest"
        ),
        sa.CheckConstraint(
            "assumptions_version = 'forecast-assumptions-v1'",
            name="ck_forecast_scenarios_forecast_scenario_assumptions_version",
        ),
        sa.CheckConstraint("version > 0", name="ck_forecast_scenarios_forecast_scenario_version"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "id", name="uq_forecast_scenarios_owner_id_id"),
    )
    op.create_index(
        "ix_forecast_scenarios_owner_id_currency",
        "forecast_scenarios",
        ["owner_id", "currency"],
    )
    op.create_table(
        "financial_goals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("target_amount", sa.Numeric(38, 9), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("saved_amount", sa.Numeric(38, 9), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("linked_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(btrim(name)) > 0", name="ck_financial_goals_financial_goal_name"
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name="ck_financial_goals_financial_goal_currency"
        ),
        sa.CheckConstraint("target_amount > 0", name="ck_financial_goals_financial_goal_target"),
        sa.CheckConstraint("saved_amount >= 0", name="ck_financial_goals_financial_goal_saved"),
        sa.CheckConstraint("priority > 0", name="ck_financial_goals_financial_goal_priority"),
        sa.CheckConstraint("version > 0", name="ck_financial_goals_financial_goal_version"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["owner_id", "linked_account_id", "currency"],
            ["accounts.owner_id", "accounts.id", "accounts.currency"],
            name="fk_financial_goals_owner_linked_account_currency_accounts",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "id", name="uq_financial_goals_owner_id_id"),
    )
    op.create_index(
        "ix_financial_goals_owner_id_priority",
        "financial_goals",
        ["owner_id", "priority", "target_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_financial_goals_owner_id_priority", table_name="financial_goals")
    op.drop_table("financial_goals")
    op.drop_index("ix_forecast_scenarios_owner_id_currency", table_name="forecast_scenarios")
    op.drop_table("forecast_scenarios")
