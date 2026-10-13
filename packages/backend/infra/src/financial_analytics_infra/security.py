from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
from collections import deque
from datetime import timedelta
from math import ceil

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type

from financial_analytics_domain import Instant


class Argon2idPasswordHashes:
    """Argon2id adapter with parameters embedded in every encoded hash."""

    def __init__(self) -> None:
        self._hasher = PasswordHasher(
            time_cost=3,
            memory_cost=65_536,
            parallelism=4,
            hash_len=32,
            salt_len=16,
            type=Type.ID,
        )

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except (InvalidHashError, VerificationError, VerifyMismatchError):
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(password_hash)
        except InvalidHashError:
            return True


class HmacSecretProvider:
    """Generate bearer secrets and persist only keyed SHA-256 digests."""

    def __init__(self, key: str) -> None:
        encoded = key.encode("utf-8")
        if len(encoded) < 32:
            raise ValueError("secret key must contain at least 32 UTF-8 bytes")
        self._key = encoded

    def generate(self) -> str:
        return secrets.token_urlsafe(32)

    def digest(self, secret: str) -> str:
        return hmac.new(self._key, secret.encode("utf-8"), hashlib.sha256).hexdigest()


class InMemorySlidingWindowRateLimiter:
    """Thread-safe per-process limiter suitable for one local API process."""

    def __init__(self, *, max_keys: int = 10_000) -> None:
        if max_keys <= 0:
            raise ValueError("max_keys must be positive")
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._max_keys = max_keys

    def consume(self, key: str, *, limit: int, window: timedelta, now: Instant) -> int | None:
        if limit <= 0 or window.total_seconds() <= 0:
            raise ValueError("rate limit and window must be positive")
        current = now.value.timestamp()
        threshold = current - window.total_seconds()
        with self._lock:
            events = self._events.get(key)
            if events is None:
                if len(self._events) >= self._max_keys:
                    self._events = {
                        item_key: item_events
                        for item_key, item_events in self._events.items()
                        if item_events and item_events[-1] > threshold
                    }
                if len(self._events) >= self._max_keys:
                    return max(1, ceil(window.total_seconds()))
                events = deque()
                self._events[key] = events
            while events and events[0] <= threshold:
                events.popleft()
            if len(events) >= limit:
                return max(1, ceil(events[0] + window.total_seconds() - current))
            events.append(current)
        return None
