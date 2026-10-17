from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Header, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from financial_analytics_api.errors import ProblemDetails
from financial_analytics_app.identity import (
    AllowlistEntry,
    AuthenticatedSession,
    AuthService,
    InvalidSessionError,
    InvitationService,
    SessionTokens,
    validate_password,
)
from financial_analytics_app.ledger import ResourceNotFoundError
from financial_analytics_domain import EmailAddress, Invitation, UserProfile
from financial_analytics_infra.settings import Settings

router = APIRouter(prefix="/api/v1", tags=["identity"])


class BootstrapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    password: SecretStr
    base_currency: str = Field(pattern=r"^[A-Z]{3}$")
    locale: str = Field(default="ru-RU", pattern=r"^[a-z]{2,3}(?:-[A-Z]{2})?$")
    timezone: str = Field(min_length=1, max_length=100)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return EmailAddress(value).value

    @field_validator("password")
    @classmethod
    def enforce_password_policy(cls, value: SecretStr) -> SecretStr:
        validate_password(value.get_secret_value())
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("timezone must be an IANA timezone") from error
        return value


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    password: SecretStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return EmailAddress(value).value

    @field_validator("password")
    @classmethod
    def limit_password_size(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) > 1024:
            raise ValueError("password is too long")
        return value


class ProfileResponse(BaseModel):
    id: UUID
    email: str
    base_currency: str
    locale: str
    timezone: str
    status: str
    is_master: bool
    is_admin: bool
    email_verified: bool
    created_at: datetime


class AllowlistRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return EmailAddress(value).value


class AllowlistResponse(BaseModel):
    id: UUID
    email: str
    added_by: UUID
    created_at: datetime
    revoked_at: datetime | None


class InvitationRequest(AllowlistRequest):
    is_admin: bool = False


class InvitationResponse(BaseModel):
    id: UUID
    email: str
    invited_by: UUID
    created_at: datetime
    expires_at: datetime
    is_admin: bool
    accepted_at: datetime | None
    revoked_at: datetime | None


class InvitationAcceptanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: SecretStr
    password: SecretStr
    base_currency: str = Field(pattern=r"^[A-Z]{3}$")
    locale: str = Field(default="ru-RU", pattern=r"^[a-z]{2,3}(?:-[A-Z]{2})?$")
    timezone: str = Field(min_length=1, max_length=100)

    @field_validator("password")
    @classmethod
    def enforce_password_policy(cls, value: SecretStr) -> SecretStr:
        validate_password(value.get_secret_value())
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("timezone must be an IANA timezone") from error
        return value


class EmailTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: SecretStr


class PasswordResetRequest(AllowlistRequest):
    pass


class PasswordResetConfirmationRequest(EmailTokenRequest):
    new_password: SecretStr

    @field_validator("new_password")
    @classmethod
    def enforce_password_policy(cls, value: SecretStr) -> SecretStr:
        validate_password(value.get_secret_value())
        return value


def _service(request: Request) -> AuthService:
    return request.app.state.auth_service  # type: ignore[no-any-return]


def _invitation_service(request: Request) -> InvitationService:
    service = request.app.state.invitation_service
    if service is None:
        raise RuntimeError("invitation service is not configured")
    return service  # type: ignore[no-any-return]


def _settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def _request_id(request: Request) -> UUID | None:
    try:
        return UUID(request.state.request_id)
    except (AttributeError, ValueError):
        return None


def _rate_limit_key(request: Request) -> str:
    return "unknown" if request.client is None else request.client.host


def _authenticated(request: Request) -> AuthenticatedSession:
    settings = _settings(request)
    raw_access = request.cookies.get(settings.access_cookie_name)
    if raw_access is None:
        raise InvalidSessionError("access session is required")
    return _service(request).authenticate_access(raw_access)


Authenticated = Annotated[AuthenticatedSession, Depends(_authenticated)]
CsrfHeader = Annotated[str | None, Header(alias="X-CSRF-Token")]


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
    "/auth/bootstrap",
    response_model=ProfileResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_problem_responses(409),
)
def bootstrap_master(
    payload: BootstrapRequest, request: Request, response: Response
) -> ProfileResponse:
    tokens = _service(request).bootstrap_master(
        email=payload.email,
        password=payload.password.get_secret_value(),
        base_currency=payload.base_currency,
        locale=payload.locale,
        timezone=payload.timezone,
        request_id=_request_id(request),
    )
    _set_session_cookies(response, tokens, _settings(request))
    return _profile_response(tokens.profile)


@router.post(
    "/auth/login",
    response_model=ProfileResponse,
    responses=_problem_responses(401, 429),
)
def login(payload: LoginRequest, request: Request, response: Response) -> ProfileResponse:
    tokens = _service(request).login(
        payload.email,
        payload.password.get_secret_value(),
        rate_limit_key=_rate_limit_key(request),
        request_id=_request_id(request),
    )
    _set_session_cookies(response, tokens, _settings(request))
    return _profile_response(tokens.profile)


@router.post(
    "/auth/refresh",
    response_model=ProfileResponse,
    responses=_problem_responses(401, 403, 429),
)
def refresh(
    request: Request,
    response: Response,
    csrf_header: CsrfHeader = None,
) -> ProfileResponse:
    settings = _settings(request)
    raw_refresh = request.cookies.get(settings.refresh_cookie_name)
    if raw_refresh is None:
        raise InvalidSessionError("refresh session is required")
    tokens = _service(request).refresh(
        raw_refresh,
        csrf_cookie=request.cookies.get(settings.csrf_cookie_name),
        csrf_header=csrf_header,
        rate_limit_key=_rate_limit_key(request),
        request_id=_request_id(request),
    )
    _set_session_cookies(response, tokens, settings)
    return _profile_response(tokens.profile)


@router.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_problem_responses(401, 403),
)
def logout_current(
    request: Request,
    response: Response,
    authenticated: Authenticated,
    csrf_header: CsrfHeader = None,
) -> None:
    settings = _settings(request)
    _service(request).logout_current(
        authenticated,
        csrf_cookie=request.cookies.get(settings.csrf_cookie_name),
        csrf_header=csrf_header,
        request_id=_request_id(request),
    )
    _clear_session_cookies(response, settings)


@router.post(
    "/auth/logout-all",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_problem_responses(401, 403),
)
def logout_all(
    request: Request,
    response: Response,
    authenticated: Authenticated,
    csrf_header: CsrfHeader = None,
) -> None:
    settings = _settings(request)
    _service(request).logout_all(
        authenticated,
        csrf_cookie=request.cookies.get(settings.csrf_cookie_name),
        csrf_header=csrf_header,
        request_id=_request_id(request),
    )
    _clear_session_cookies(response, settings)


@router.post(
    "/auth/invitations/accept",
    response_model=ProfileResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_problem_responses(400, 409),
)
def accept_invitation(
    payload: InvitationAcceptanceRequest,
    request: Request,
    response: Response,
) -> ProfileResponse:
    profile = _invitation_service(request).accept_invitation(
        payload.token.get_secret_value(),
        password=payload.password.get_secret_value(),
        base_currency=payload.base_currency,
        locale=payload.locale,
        timezone=payload.timezone,
        request_id=_request_id(request),
    )
    tokens = _service(request).login(
        profile.email.value,
        payload.password.get_secret_value(),
        rate_limit_key=_rate_limit_key(request),
        request_id=_request_id(request),
    )
    _set_session_cookies(response, tokens, _settings(request))
    return _profile_response(profile)


@router.post(
    "/auth/email-verification/request",
    status_code=status.HTTP_202_ACCEPTED,
    responses=_problem_responses(401, 403),
)
def request_email_verification(
    request: Request,
    authenticated: Authenticated,
    csrf_header: CsrfHeader = None,
) -> None:
    _service(request).verify_csrf(
        authenticated,
        cookie_token=request.cookies.get(_settings(request).csrf_cookie_name),
        header_token=csrf_header,
    )
    _invitation_service(request).request_email_verification(
        authenticated.profile.id,
        request_id=_request_id(request),
    )


@router.post(
    "/auth/email-verification/confirm",
    response_model=ProfileResponse,
    responses=_problem_responses(400),
)
def confirm_email_verification(payload: EmailTokenRequest, request: Request) -> ProfileResponse:
    profile = _invitation_service(request).verify_email(
        payload.token.get_secret_value(),
        request_id=_request_id(request),
    )
    return _profile_response(profile)


@router.post("/auth/password-reset/request", status_code=status.HTTP_202_ACCEPTED)
def request_password_reset(payload: PasswordResetRequest, request: Request) -> None:
    _invitation_service(request).request_password_reset(
        payload.email,
        request_id=_request_id(request),
    )


@router.post(
    "/auth/password-reset/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_problem_responses(400),
)
def confirm_password_reset(payload: PasswordResetConfirmationRequest, request: Request) -> None:
    _invitation_service(request).reset_password(
        payload.token.get_secret_value(),
        new_password=payload.new_password.get_secret_value(),
        request_id=_request_id(request),
    )


@router.get(
    "/admin/allowlist",
    response_model=list[AllowlistResponse],
    responses=_problem_responses(401, 403),
)
def list_allowlist(request: Request, authenticated: Authenticated) -> list[AllowlistResponse]:
    entries = _invitation_service(request).list_allowlist(actor_id=authenticated.profile.id)
    return [_allowlist_response(entry) for entry in entries]


@router.post(
    "/admin/allowlist",
    response_model=AllowlistResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_problem_responses(401, 403, 409),
)
def add_allowlist(
    payload: AllowlistRequest,
    request: Request,
    authenticated: Authenticated,
    csrf_header: CsrfHeader = None,
) -> AllowlistResponse:
    _service(request).verify_csrf(
        authenticated,
        cookie_token=request.cookies.get(_settings(request).csrf_cookie_name),
        header_token=csrf_header,
    )
    entry = _invitation_service(request).allow_email(
        payload.email,
        actor_id=authenticated.profile.id,
        request_id=_request_id(request),
    )
    return _allowlist_response(entry)


@router.delete(
    "/admin/allowlist/{entry_id}",
    response_model=AllowlistResponse,
    responses=_problem_responses(401, 403, 404),
)
def revoke_allowlist(
    entry_id: UUID,
    request: Request,
    authenticated: Authenticated,
    csrf_header: CsrfHeader = None,
) -> AllowlistResponse:
    _service(request).verify_csrf(
        authenticated,
        cookie_token=request.cookies.get(_settings(request).csrf_cookie_name),
        header_token=csrf_header,
    )
    entry = _invitation_service(request).revoke_allowlist(
        entry_id,
        actor_id=authenticated.profile.id,
        request_id=_request_id(request),
    )
    if entry is None:
        raise ResourceNotFoundError("allowlist entry was not found")
    return _allowlist_response(entry)


@router.get(
    "/admin/invitations",
    response_model=list[InvitationResponse],
    responses=_problem_responses(401, 403),
)
def list_invitations(request: Request, authenticated: Authenticated) -> list[InvitationResponse]:
    invitations = _invitation_service(request).list_invitations(actor_id=authenticated.profile.id)
    return [_invitation_response(invitation) for invitation in invitations]


@router.post(
    "/admin/invitations",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_problem_responses(401, 403),
)
def create_invitation(
    payload: InvitationRequest,
    request: Request,
    authenticated: Authenticated,
    csrf_header: CsrfHeader = None,
) -> InvitationResponse:
    _service(request).verify_csrf(
        authenticated,
        cookie_token=request.cookies.get(_settings(request).csrf_cookie_name),
        header_token=csrf_header,
    )
    invitation, _ = _invitation_service(request).issue_invitation(
        payload.email,
        actor_id=authenticated.profile.id,
        is_admin=payload.is_admin,
        request_id=_request_id(request),
    )
    return _invitation_response(invitation)


@router.get(
    "/profile",
    response_model=ProfileResponse,
    responses=_problem_responses(401, 403),
)
def current_profile(authenticated: Authenticated) -> ProfileResponse:
    return _profile_response(authenticated.profile)


def _profile_response(profile: UserProfile) -> ProfileResponse:
    return ProfileResponse(
        id=profile.id,
        email=profile.email.value,
        base_currency=profile.base_currency.code,
        locale=profile.locale,
        timezone=profile.timezone,
        status=profile.status.value,
        is_master=profile.is_master,
        is_admin=profile.is_admin,
        email_verified=profile.email_verified_at is not None,
        created_at=profile.created_at.value,
    )


def _allowlist_response(entry: AllowlistEntry) -> AllowlistResponse:
    return AllowlistResponse(
        id=entry.id,
        email=entry.email.value,
        added_by=entry.added_by,
        created_at=entry.created_at.value,
        revoked_at=None if entry.revoked_at is None else entry.revoked_at.value,
    )


def _invitation_response(invitation: Invitation) -> InvitationResponse:
    return InvitationResponse(
        id=invitation.id,
        email=invitation.email.value,
        invited_by=invitation.invited_by,
        created_at=invitation.created_at.value,
        expires_at=invitation.expires_at.value,
        is_admin=invitation.is_admin,
        accepted_at=(None if invitation.accepted_at is None else invitation.accepted_at.value),
        revoked_at=None if invitation.revoked_at is None else invitation.revoked_at.value,
    )


def _set_session_cookies(response: Response, tokens: SessionTokens, settings: Settings) -> None:
    response.set_cookie(
        settings.access_cookie_name,
        tokens.access_token,
        httponly=True,
        expires=tokens.access_expires_at.value,
        path="/",
        secure=settings.session_cookie_secure,
        samesite="strict",
        domain=settings.session_cookie_domain,
    )
    response.set_cookie(
        settings.refresh_cookie_name,
        tokens.refresh_token,
        httponly=True,
        expires=tokens.refresh_expires_at.value,
        path="/api/v1/auth",
        secure=settings.session_cookie_secure,
        samesite="strict",
        domain=settings.session_cookie_domain,
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        tokens.csrf_token,
        httponly=False,
        expires=tokens.refresh_expires_at.value,
        path="/",
        secure=settings.session_cookie_secure,
        samesite="strict",
        domain=settings.session_cookie_domain,
    )


def _clear_session_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        settings.access_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="strict",
        domain=settings.session_cookie_domain,
    )
    response.delete_cookie(
        settings.refresh_cookie_name,
        path="/api/v1/auth",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="strict",
        domain=settings.session_cookie_domain,
    )
    response.delete_cookie(
        settings.csrf_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=False,
        samesite="strict",
        domain=settings.session_cookie_domain,
    )
