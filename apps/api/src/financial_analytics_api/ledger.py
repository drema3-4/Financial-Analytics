from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from financial_analytics_api.errors import ApplicationError, ProblemDetails
from financial_analytics_api.identity import Authenticated, CsrfHeader
from financial_analytics_app import (
    LedgerService,
    TransactionCursor,
    TransactionQuery,
)
from financial_analytics_app.identity import AuthenticatedSession
from financial_analytics_domain import (
    Account,
    AccountKind,
    Category,
    CategoryGroup,
    CategoryKind,
    Currency,
    Instant,
    Money,
    Posting,
    Tag,
    Transaction,
    TransactionKind,
)

router = APIRouter(prefix="/api/v1")


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MoneyInput(ApiModel):
    amount: str = Field(
        pattern=r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$",
        examples=["1250.00"],
    )
    currency: str = Field(pattern=r"^[A-Z]{3}$", examples=["RUB"])

    @field_validator("amount", mode="before")
    @classmethod
    def reject_non_string_amount(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("amount must be a decimal string")
        return value

    def to_domain(self) -> Money:
        return Money.of(self.amount, self.currency)


class MoneyResponse(ApiModel):
    amount: str
    currency: str


class CreateAccountRequest(ApiModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "name": "Основная карта",
                    "kind": "bank",
                    "currency": "RUB",
                    "opening_balance": {"amount": "15000.00", "currency": "RUB"},
                    "opening_balance_occurred_at": "2026-10-13T09:00:00+04:00",
                }
            ]
        },
    )

    name: str = Field(min_length=1, max_length=160)
    kind: Literal["cash", "bank", "savings", "deposit", "other_asset"]
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    opening_balance: MoneyInput | None = None
    opening_balance_occurred_at: datetime | None = None

    @model_validator(mode="after")
    def validate_opening_balance(self) -> CreateAccountRequest:
        if self.opening_balance is not None:
            if self.opening_balance.currency != self.currency:
                raise ValueError("opening balance currency must match account currency")
            if Decimal(self.opening_balance.amount) == 0:
                raise ValueError("opening balance must be non-zero when supplied")
        _require_aware(self.opening_balance_occurred_at, "opening_balance_occurred_at")
        return self


class UpdateAccountRequest(ApiModel):
    version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    archived: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> UpdateAccountRequest:
        if self.name is None and self.archived is None:
            raise ValueError("at least one mutable field is required")
        return self


class AccountResponse(ApiModel):
    id: UUID
    name: str
    kind: str
    currency: str
    balance: MoneyResponse
    archived: bool
    version: int


class CreateCategoryGroupRequest(ApiModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"name": "Дом", "parent_id": None}]},
    )

    name: str = Field(min_length=1, max_length=160)
    parent_id: UUID | None = None


class CategoryResponse(ApiModel):
    id: UUID
    name: str
    kind: CategoryKind
    group_id: UUID | None
    is_mandatory: bool
    version: int


class CategoryGroupResponse(ApiModel):
    id: UUID
    name: str
    parent_id: UUID | None
    version: int
    categories: list[CategoryResponse]


class CreateCategoryRequest(ApiModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "name": "Продукты",
                    "kind": "expense",
                    "group_id": None,
                    "is_mandatory": True,
                }
            ]
        },
    )

    name: str = Field(min_length=1, max_length=160)
    kind: CategoryKind
    group_id: UUID | None = None
    is_mandatory: bool = False


class CreateTagRequest(ApiModel):
    name: str = Field(min_length=1, max_length=80, examples=["отпуск"])


class TagResponse(ApiModel):
    id: UUID
    name: str
    version: int


class OperationRequest(ApiModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "account_id": "018f0000-0000-7000-8000-000000000001",
                    "category_id": "018f0000-0000-7000-8000-000000000002",
                    "money": {"amount": "1250.00", "currency": "RUB"},
                    "occurred_at": "2026-10-13T10:15:00+04:00",
                    "description": "Продукты, неделя",
                    "source": "manual",
                    "tag_ids": [],
                }
            ]
        },
    )

    account_id: UUID
    category_id: UUID
    money: MoneyInput
    occurred_at: datetime
    description: str = Field(default="", max_length=2000)
    source: Literal["manual", "import"] = "manual"
    tag_ids: list[UUID] = Field(default_factory=list, max_length=50)

    @field_validator("occurred_at")
    @classmethod
    def aware_occurred_at(cls, value: datetime) -> datetime:
        _require_aware(value, "occurred_at")
        return value


class TransferRequest(ApiModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "source_account_id": "018f0000-0000-7000-8000-000000000001",
                    "destination_account_id": "018f0000-0000-7000-8000-000000000002",
                    "money": {"amount": "5000.00", "currency": "RUB"},
                    "occurred_at": "2026-10-13T11:00:00+04:00",
                    "description": "В накопления",
                    "source": "manual",
                    "tag_ids": [],
                }
            ]
        },
    )

    source_account_id: UUID
    destination_account_id: UUID
    money: MoneyInput
    occurred_at: datetime
    description: str = Field(default="", max_length=2000)
    source: Literal["manual", "import"] = "manual"
    tag_ids: list[UUID] = Field(default_factory=list, max_length=50)

    @field_validator("occurred_at")
    @classmethod
    def aware_occurred_at(cls, value: datetime) -> datetime:
        _require_aware(value, "occurred_at")
        return value


class AdjustmentRequest(ApiModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "account_id": "018f0000-0000-7000-8000-000000000001",
                    "money": {"amount": "-50.00", "currency": "RUB"},
                    "occurred_at": "2026-10-13T12:00:00+04:00",
                    "description": "Сверка с банковской выпиской",
                    "source": "manual",
                    "tag_ids": [],
                }
            ]
        },
    )

    account_id: UUID
    money: MoneyInput
    occurred_at: datetime
    description: str = Field(min_length=1, max_length=2000)
    source: Literal["manual", "import"] = "manual"
    tag_ids: list[UUID] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_adjustment(self) -> AdjustmentRequest:
        _require_aware(self.occurred_at, "occurred_at")
        if Decimal(self.money.amount) == 0:
            raise ValueError("adjustment amount must be non-zero")
        return self


class ReversalRequest(ApiModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "occurred_at": "2026-10-13T13:00:00+04:00",
                    "reason": "Операция внесена дважды",
                }
            ]
        },
    )

    occurred_at: datetime
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("occurred_at")
    @classmethod
    def aware_occurred_at(cls, value: datetime) -> datetime:
        _require_aware(value, "occurred_at")
        return value


class PostingResponse(ApiModel):
    id: UUID
    account_id: UUID
    money: MoneyResponse
    reversal_of_id: UUID | None


class TransactionResponse(ApiModel):
    id: UUID
    kind: TransactionKind
    occurred_at: datetime
    description: str
    source: str
    category_id: UUID | None
    reversal_of_id: UUID | None
    deposit_id: UUID | None
    tag_ids: list[UUID]
    postings: list[PostingResponse]
    version: int


class TransactionPageResponse(ApiModel):
    items: list[TransactionResponse]
    next_cursor: str | None


IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=200,
        pattern=r"^[\x21-\x7E]+$",
        description="Caller-generated key unique to one logical create or reversal command.",
        examples=["account-20261013-001"],
    ),
]


def _service(request: Request) -> LedgerService:
    return request.app.state.ledger_service  # type: ignore[no-any-return]


def _mutation_authenticated(
    request: Request,
    authenticated: Authenticated,
    csrf_header: CsrfHeader,
) -> AuthenticatedSession:
    settings = request.app.state.settings
    request.app.state.auth_service.verify_csrf(
        authenticated,
        cookie_token=request.cookies.get(settings.csrf_cookie_name),
        header_token=csrf_header,
    )
    return authenticated


MutatingSession = Annotated[AuthenticatedSession, Depends(_mutation_authenticated)]


def _request_id(request: Request) -> UUID | None:
    try:
        return UUID(request.state.request_id)
    except (AttributeError, ValueError):
        return None


def _request_hash(payload: BaseModel, *, context: str = "") -> str:
    body = json.dumps(
        {"context": context, "payload": payload.model_dump(mode="json")},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _problem_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    return {
        status_code: {
            "model": ProblemDetails,
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ProblemDetails"}
                }
            },
        }
        for status_code in status_codes
    }


@router.post(
    "/accounts",
    tags=["accounts"],
    operation_id="createAccount",
    response_model=AccountResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_problem_responses(401, 403, 409, 422),
)
def create_account(
    payload: CreateAccountRequest,
    request: Request,
    authenticated: MutatingSession,
    idempotency_key: IdempotencyKey,
) -> AccountResponse:
    occurred_at = payload.opening_balance_occurred_at or request.app.state.clock().value
    account = _service(request).create_account(
        owner_id=authenticated.profile.id,
        actor_id=authenticated.profile.id,
        name=payload.name,
        kind=AccountKind(payload.kind),
        currency=Currency(payload.currency),
        opening_balance=(
            None if payload.opening_balance is None else payload.opening_balance.to_domain()
        ),
        occurred_at=Instant(occurred_at),
        idempotency_key=idempotency_key,
        request_hash=_request_hash(payload),
        request_id=_request_id(request),
    )
    snapshot = _service(request).get_account(authenticated.profile.id, account.id)
    return _account_response(snapshot.account, snapshot.balance)


@router.get(
    "/accounts",
    tags=["accounts"],
    operation_id="listAccounts",
    response_model=list[AccountResponse],
    responses=_problem_responses(401),
)
def list_accounts(
    request: Request,
    authenticated: Authenticated,
    include_archived: Annotated[bool, Query()] = False,
) -> list[AccountResponse]:
    return [
        _account_response(item.account, item.balance)
        for item in _service(request).list_accounts(
            authenticated.profile.id, include_archived=include_archived
        )
    ]


@router.get(
    "/accounts/{account_id}",
    tags=["accounts"],
    operation_id="getAccount",
    response_model=AccountResponse,
    responses=_problem_responses(401, 404),
)
def get_account(
    account_id: UUID, request: Request, authenticated: Authenticated
) -> AccountResponse:
    item = _service(request).get_account(authenticated.profile.id, account_id)
    return _account_response(item.account, item.balance)


@router.patch(
    "/accounts/{account_id}",
    tags=["accounts"],
    operation_id="updateAccount",
    response_model=AccountResponse,
    responses=_problem_responses(401, 403, 404, 409, 422),
)
def update_account(
    account_id: UUID,
    payload: UpdateAccountRequest,
    request: Request,
    authenticated: MutatingSession,
) -> AccountResponse:
    _service(request).update_account(
        owner_id=authenticated.profile.id,
        actor_id=authenticated.profile.id,
        account_id=account_id,
        version=payload.version,
        name=payload.name,
        archived=payload.archived,
        request_id=_request_id(request),
    )
    item = _service(request).get_account(authenticated.profile.id, account_id)
    return _account_response(item.account, item.balance)


@router.post(
    "/category-groups",
    tags=["categories"],
    operation_id="createCategoryGroup",
    response_model=CategoryGroupResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_problem_responses(401, 403, 404, 409, 422),
)
def create_category_group(
    payload: CreateCategoryGroupRequest,
    request: Request,
    authenticated: MutatingSession,
    idempotency_key: IdempotencyKey,
) -> CategoryGroupResponse:
    group = _service(request).create_category_group(
        owner_id=authenticated.profile.id,
        actor_id=authenticated.profile.id,
        name=payload.name,
        parent_id=payload.parent_id,
        idempotency_key=idempotency_key,
        request_hash=_request_hash(payload),
        request_id=_request_id(request),
    )
    return _group_response(group, ())


@router.get(
    "/category-groups",
    tags=["categories"],
    operation_id="listCategoryGroups",
    response_model=list[CategoryGroupResponse],
    responses=_problem_responses(401),
)
def list_category_groups(
    request: Request, authenticated: Authenticated
) -> list[CategoryGroupResponse]:
    service = _service(request)
    groups = service.list_category_groups(authenticated.profile.id)
    categories = service.list_categories(authenticated.profile.id)
    return [
        _group_response(group, tuple(item for item in categories if item.group_id == group.id))
        for group in groups
    ]


@router.post(
    "/categories",
    tags=["categories"],
    operation_id="createCategory",
    response_model=CategoryResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_problem_responses(401, 403, 404, 409, 422),
)
def create_category(
    payload: CreateCategoryRequest,
    request: Request,
    authenticated: MutatingSession,
    idempotency_key: IdempotencyKey,
) -> CategoryResponse:
    category = _service(request).create_category(
        owner_id=authenticated.profile.id,
        actor_id=authenticated.profile.id,
        name=payload.name,
        kind=payload.kind,
        group_id=payload.group_id,
        is_mandatory=payload.is_mandatory,
        idempotency_key=idempotency_key,
        request_hash=_request_hash(payload),
        request_id=_request_id(request),
    )
    return _category_response(category)


@router.get(
    "/categories",
    tags=["categories"],
    operation_id="listCategories",
    response_model=list[CategoryResponse],
    responses=_problem_responses(401),
)
def list_categories(request: Request, authenticated: Authenticated) -> list[CategoryResponse]:
    return [
        _category_response(category)
        for category in _service(request).list_categories(authenticated.profile.id)
    ]


@router.post(
    "/tags",
    tags=["categories"],
    operation_id="createTag",
    response_model=TagResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_problem_responses(401, 403, 409, 422),
)
def create_tag(
    payload: CreateTagRequest,
    request: Request,
    authenticated: MutatingSession,
    idempotency_key: IdempotencyKey,
) -> TagResponse:
    tag = _service(request).create_tag(
        owner_id=authenticated.profile.id,
        actor_id=authenticated.profile.id,
        name=payload.name,
        idempotency_key=idempotency_key,
        request_hash=_request_hash(payload),
        request_id=_request_id(request),
    )
    return _tag_response(tag)


@router.get(
    "/tags",
    tags=["categories"],
    operation_id="listTags",
    response_model=list[TagResponse],
    responses=_problem_responses(401),
)
def list_tags(request: Request, authenticated: Authenticated) -> list[TagResponse]:
    return [_tag_response(tag) for tag in _service(request).list_tags(authenticated.profile.id)]


@router.post(
    "/transactions/income",
    tags=["ledger"],
    operation_id="createIncome",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_problem_responses(401, 403, 404, 409, 422),
)
def create_income(
    payload: OperationRequest,
    request: Request,
    authenticated: MutatingSession,
    idempotency_key: IdempotencyKey,
) -> TransactionResponse:
    transaction = _service(request).record_income(
        owner_id=authenticated.profile.id,
        actor_id=authenticated.profile.id,
        account_id=payload.account_id,
        category_id=payload.category_id,
        amount=payload.money.to_domain(),
        occurred_at=Instant(payload.occurred_at),
        description=payload.description,
        source=payload.source,
        tag_ids=payload.tag_ids,
        idempotency_key=idempotency_key,
        request_hash=_request_hash(payload),
        request_id=_request_id(request),
    )
    return _transaction_response(transaction)


@router.post(
    "/transactions/expense",
    tags=["ledger"],
    operation_id="createExpense",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_problem_responses(401, 403, 404, 409, 422),
)
def create_expense(
    payload: OperationRequest,
    request: Request,
    authenticated: MutatingSession,
    idempotency_key: IdempotencyKey,
) -> TransactionResponse:
    transaction = _service(request).record_expense(
        owner_id=authenticated.profile.id,
        actor_id=authenticated.profile.id,
        account_id=payload.account_id,
        category_id=payload.category_id,
        amount=payload.money.to_domain(),
        occurred_at=Instant(payload.occurred_at),
        description=payload.description,
        source=payload.source,
        tag_ids=payload.tag_ids,
        idempotency_key=idempotency_key,
        request_hash=_request_hash(payload),
        request_id=_request_id(request),
    )
    return _transaction_response(transaction)


@router.post(
    "/transfers",
    tags=["ledger"],
    operation_id="createTransfer",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_problem_responses(401, 403, 404, 409, 422),
)
def create_transfer(
    payload: TransferRequest,
    request: Request,
    authenticated: MutatingSession,
    idempotency_key: IdempotencyKey,
) -> TransactionResponse:
    transaction = _service(request).record_transfer(
        owner_id=authenticated.profile.id,
        actor_id=authenticated.profile.id,
        source_account_id=payload.source_account_id,
        destination_account_id=payload.destination_account_id,
        amount=payload.money.to_domain(),
        occurred_at=Instant(payload.occurred_at),
        description=payload.description,
        source=payload.source,
        tag_ids=payload.tag_ids,
        idempotency_key=idempotency_key,
        request_hash=_request_hash(payload),
        request_id=_request_id(request),
    )
    return _transaction_response(transaction)


@router.post(
    "/adjustments",
    tags=["ledger"],
    operation_id="createAdjustment",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_problem_responses(401, 403, 404, 409, 422),
)
def create_adjustment(
    payload: AdjustmentRequest,
    request: Request,
    authenticated: MutatingSession,
    idempotency_key: IdempotencyKey,
) -> TransactionResponse:
    transaction = _service(request).record_adjustment(
        owner_id=authenticated.profile.id,
        actor_id=authenticated.profile.id,
        account_id=payload.account_id,
        amount=payload.money.to_domain(),
        occurred_at=Instant(payload.occurred_at),
        description=payload.description,
        source=payload.source,
        tag_ids=payload.tag_ids,
        idempotency_key=idempotency_key,
        request_hash=_request_hash(payload),
        request_id=_request_id(request),
    )
    return _transaction_response(transaction)


@router.get(
    "/transactions",
    tags=["ledger"],
    operation_id="listTransactions",
    response_model=TransactionPageResponse,
    responses=_problem_responses(401, 422),
)
def list_transactions(
    request: Request,
    authenticated: Authenticated,
    account_id: Annotated[UUID | None, Query()] = None,
    category_id: Annotated[UUID | None, Query()] = None,
    tag_id: Annotated[UUID | None, Query()] = None,
    kind: Annotated[TransactionKind | None, Query()] = None,
    occurred_from: Annotated[datetime | None, Query()] = None,
    occurred_to: Annotated[datetime | None, Query()] = None,
    search: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    cursor: Annotated[str | None, Query(min_length=1, max_length=500)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> TransactionPageResponse:
    query = _transaction_query(
        account_id, category_id, tag_id, kind, occurred_from, occurred_to, search
    )
    decoded_cursor = None if cursor is None else _decode_cursor(cursor)
    page = _service(request).list_transactions(
        authenticated.profile.id, query, cursor=decoded_cursor, limit=limit
    )
    next_cursor = (
        _encode_cursor(page.items[-1], page.snapshot_at) if page.has_more and page.items else None
    )
    return TransactionPageResponse(
        items=[_transaction_response(item) for item in page.items],
        next_cursor=next_cursor,
    )


@router.get(
    "/transactions/export.csv",
    tags=["ledger"],
    operation_id="exportTransactionsCsv",
    response_class=Response,
    responses={
        200: {
            "content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}},
            "description": "UTF-8 CSV with BOM and CRLF line endings.",
        },
        **_problem_responses(401, 422),
    },
)
def export_transactions_csv(
    request: Request,
    authenticated: Authenticated,
    account_id: Annotated[UUID | None, Query()] = None,
    category_id: Annotated[UUID | None, Query()] = None,
    tag_id: Annotated[UUID | None, Query()] = None,
    kind: Annotated[TransactionKind | None, Query()] = None,
    occurred_from: Annotated[datetime | None, Query()] = None,
    occurred_to: Annotated[datetime | None, Query()] = None,
    search: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
) -> Response:
    query = _transaction_query(
        account_id, category_id, tag_id, kind, occurred_from, occurred_to, search
    )
    transactions: list[Transaction] = []
    cursor: TransactionCursor | None = None
    while True:
        page = _service(request).list_transactions(
            authenticated.profile.id, query, cursor=cursor, limit=1000
        )
        transactions.extend(page.items)
        if not page.has_more or not page.items:
            break
        last = page.items[-1]
        cursor = TransactionCursor(last.occurred_at.value, last.id, page.snapshot_at)
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(
        [
            "id",
            "kind",
            "occurred_at",
            "amount",
            "currency",
            "description",
            "source",
            "category_id",
            "account_ids",
            "tag_ids",
            "reversal_of_id",
        ]
    )
    for transaction in transactions:
        amount = max(abs(posting.amount.amount) for posting in transaction.postings)
        writer.writerow(
            [
                str(transaction.id),
                transaction.kind.value,
                transaction.occurred_at.value.isoformat().replace("+00:00", "Z"),
                _decimal_string(amount, transaction.currency),
                transaction.currency.code,
                _csv_safe(transaction.description),
                transaction.source,
                "" if transaction.category_id is None else str(transaction.category_id),
                "|".join(str(posting.account_id) for posting in transaction.postings),
                "|".join(str(tag_id) for tag_id in transaction.tag_ids),
                "" if transaction.reversal_of_id is None else str(transaction.reversal_of_id),
            ]
        )
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="transactions.csv"'},
    )


@router.get(
    "/transactions/{transaction_id}",
    tags=["ledger"],
    operation_id="getTransaction",
    response_model=TransactionResponse,
    responses=_problem_responses(401, 404),
)
def get_transaction(
    transaction_id: UUID, request: Request, authenticated: Authenticated
) -> TransactionResponse:
    return _transaction_response(
        _service(request).get_transaction(authenticated.profile.id, transaction_id)
    )


@router.post(
    "/transactions/{transaction_id}/reversal",
    tags=["ledger"],
    operation_id="reverseTransaction",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_problem_responses(401, 403, 404, 409, 422),
)
def reverse_transaction(
    transaction_id: UUID,
    payload: ReversalRequest,
    request: Request,
    authenticated: MutatingSession,
    idempotency_key: IdempotencyKey,
) -> TransactionResponse:
    transaction = _service(request).reverse_transaction(
        owner_id=authenticated.profile.id,
        actor_id=authenticated.profile.id,
        transaction_id=transaction_id,
        occurred_at=Instant(payload.occurred_at),
        reason=payload.reason,
        idempotency_key=idempotency_key,
        request_hash=_request_hash(payload, context=str(transaction_id)),
        request_id=_request_id(request),
    )
    return _transaction_response(transaction)


def _account_response(account: Account, balance: Money) -> AccountResponse:
    return AccountResponse(
        id=account.id,
        name=account.name,
        kind=account.kind.value,
        currency=account.currency.code,
        balance=_money_response(balance),
        archived=account.archived,
        version=account.version,
    )


def _category_response(category: Category) -> CategoryResponse:
    return CategoryResponse(
        id=category.id,
        name=category.name,
        kind=category.kind,
        group_id=category.group_id,
        is_mandatory=category.is_mandatory,
        version=category.version,
    )


def _group_response(
    group: CategoryGroup, categories: tuple[Category, ...]
) -> CategoryGroupResponse:
    return CategoryGroupResponse(
        id=group.id,
        name=group.name,
        parent_id=group.parent_id,
        version=group.version,
        categories=[_category_response(item) for item in categories],
    )


def _tag_response(tag: Tag) -> TagResponse:
    return TagResponse(id=tag.id, name=tag.name, version=tag.version)


def _money_response(money: Money) -> MoneyResponse:
    return MoneyResponse(
        amount=_decimal_string(money.amount, money.currency),
        currency=money.currency.code,
    )


def _posting_response(posting: Posting) -> PostingResponse:
    return PostingResponse(
        id=posting.id,
        account_id=posting.account_id,
        money=_money_response(posting.amount),
        reversal_of_id=posting.reversal_of_id,
    )


def _transaction_response(transaction: Transaction) -> TransactionResponse:
    return TransactionResponse(
        id=transaction.id,
        kind=transaction.kind,
        occurred_at=transaction.occurred_at.value,
        description=transaction.description,
        source=transaction.source,
        category_id=transaction.category_id,
        reversal_of_id=transaction.reversal_of_id,
        deposit_id=transaction.deposit_id,
        tag_ids=list(transaction.tag_ids),
        postings=[_posting_response(posting) for posting in transaction.postings],
        version=transaction.version,
    )


def _decimal_string(value: Decimal, currency: Currency) -> str:
    return f"{value:.{currency.minor_units}f}"


def _encode_cursor(transaction: Transaction, snapshot_at: datetime) -> str:
    value = json.dumps(
        [
            transaction.occurred_at.value.isoformat(),
            str(transaction.id),
            snapshot_at.isoformat(),
        ],
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode_cursor(value: str) -> TransactionCursor:
    try:
        padding = "=" * (-len(value) % 4)
        raw = base64.urlsafe_b64decode(value + padding)
        occurred_at_raw, transaction_id_raw, snapshot_at_raw = json.loads(raw)
        occurred_at = datetime.fromisoformat(occurred_at_raw)
        snapshot_at = datetime.fromisoformat(snapshot_at_raw)
        _require_aware(occurred_at, "cursor occurred_at")
        _require_aware(snapshot_at, "cursor snapshot_at")
        return TransactionCursor(
            occurred_at.astimezone(UTC),
            UUID(transaction_id_raw),
            snapshot_at.astimezone(UTC),
        )
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise ApplicationError(
            status=422,
            code="invalid_cursor",
            title="Invalid cursor",
            detail="The pagination cursor is malformed or unsupported.",
        ) from error


def _transaction_query(
    account_id: UUID | None,
    category_id: UUID | None,
    tag_id: UUID | None,
    kind: TransactionKind | None,
    occurred_from: datetime | None,
    occurred_to: datetime | None,
    search: str | None,
) -> TransactionQuery:
    _require_aware(occurred_from, "occurred_from")
    _require_aware(occurred_to, "occurred_to")
    if occurred_from is not None and occurred_to is not None and occurred_from >= occurred_to:
        raise ApplicationError(
            status=422,
            code="invalid_date_range",
            title="Invalid date range",
            detail="occurred_to must be later than occurred_from.",
        )
    return TransactionQuery(
        account_id=account_id,
        category_id=category_id,
        tag_id=tag_id,
        kind=kind,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
        search=search,
    )


def _require_aware(value: datetime | None, field: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{field} must include an explicit UTC offset")


def _csv_safe(value: str) -> str:
    if value.lstrip(" \t\r\n\ufeff").startswith(("=", "+", "-", "@")):
        return "'" + value
    return value
