"""Shared configuration and request boundaries for the public Flask service."""

from __future__ import annotations

import json
import os
from ipaddress import ip_address
from urllib.parse import quote, urlsplit

from flask import Request

MAX_JSON_BODY_BYTES = 16 * 1024
MAX_CHAT_MESSAGE_CHARS = 4_000
MAX_CHAT_SESSION_BYTES = 64 * 1024
MAX_SYSTEM_PROMPT_CHARS = 8_000
CHAT_RATE_LIMIT_PER_MINUTE = 10
MODEL_TIMEOUT_SECONDS = 60
MODEL_MAX_RETRIES = 1

DEFAULT_TRUSTED_HOSTS = (
    "www.rendazhang.com",
    "rendazhang.com",
    "localhost",
    "127.0.0.1",
    "::1",
)

_RATE_LIMIT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""


class RequestValidationError(ValueError):
    """Raised when a public request does not match its bounded JSON contract."""


def required_env(
    name: str,
    *,
    min_length: int = 1,
    forbidden_values: tuple[str, ...] = (),
) -> str:
    value = os.getenv(name)
    normalized = value.strip() if value is not None else ""
    forbidden = {item.casefold() for item in forbidden_values}
    if len(normalized) < min_length or normalized.casefold() in forbidden:
        raise RuntimeError(f"{name} must be configured")
    return value


def bounded_env(name: str, default: str, *, max_length: int) -> str:
    value = os.getenv(name, default)
    if len(value) > max_length:
        raise RuntimeError(f"{name} exceeds its configured limit")
    return value


def positive_int_env(
    name: str,
    default: int,
    *,
    minimum: int = 1,
    maximum: int,
) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise RuntimeError(f"{name} is outside its supported range")
    return value


def required_https_origin(name: str) -> str:
    value = required_env(name).strip()
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise RuntimeError(f"{name} must be an absolute HTTPS origin")
    return value.rstrip("/")


def trusted_hosts_from_env(name: str = "TRUSTED_HOSTS") -> list[str]:
    raw_value = os.getenv(name, "")
    if not raw_value.strip():
        return list(DEFAULT_TRUSTED_HOSTS)

    hosts = [host.strip() for host in raw_value.split(",") if host.strip()]
    if not hosts:
        raise RuntimeError(f"{name} must contain at least one host")
    for host in hosts:
        if (
            len(host) > 253
            or "/" in host
            or "@" in host
            or any(ch.isspace() for ch in host)
        ):
            raise RuntimeError(f"{name} contains an invalid host")
    return hosts


def require_json_object(req: Request) -> dict[str, object]:
    if not req.is_json:
        raise RequestValidationError("JSON object required")
    value = req.get_json(silent=True)
    if not isinstance(value, dict):
        raise RequestValidationError("JSON object required")
    return value


def string_field(
    data: dict[str, object],
    name: str,
    *,
    max_length: int,
    strip: bool = False,
) -> str | None:
    value = data.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RequestValidationError(f"{name} must be a string")
    normalized = value.strip() if strip else value
    if len(normalized) > max_length:
        raise RequestValidationError(f"{name} is too long")
    return normalized


def trusted_client_ip(remote_addr: str | None, forwarded_for: str | None) -> str:
    try:
        peer = ip_address(remote_addr or "")
    except ValueError:
        return "unknown"

    if peer.is_loopback and forwarded_for and "," not in forwarded_for:
        try:
            return str(ip_address(forwarded_for.strip()))
        except ValueError:
            pass
    return str(peer)


def rate_limit_allowed(redis_client, key: str, limit: int, window_seconds: int) -> bool:
    count = redis_client.eval(_RATE_LIMIT_SCRIPT, 1, key, window_seconds)
    return int(count) <= limit


def chat_history_bytes(messages: list[dict[str, str]]) -> int:
    return len(
        json.dumps(messages, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


def trim_chat_history(
    messages: list[dict[str, str]],
    *,
    max_rounds: int,
    max_bytes: int,
) -> list[dict[str, str]]:
    if not messages:
        return []

    first = messages[0]
    if first.get("role") != "system" or not isinstance(first.get("content"), str):
        return []

    turns: list[list[dict[str, str]]] = []
    current_turn: list[dict[str, str]] = []
    for message in messages[1:]:
        role = message.get("role")
        content = message.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        normalized = {"role": role, "content": content}
        if role == "user":
            if current_turn:
                turns.append(current_turn)
            current_turn = [normalized]
        elif current_turn:
            current_turn.append(normalized)
            turns.append(current_turn)
            current_turn = []
    if current_turn:
        turns.append(current_turn)

    turns = turns[-max_rounds:]

    def flatten() -> list[dict[str, str]]:
        return [first, *(message for turn in turns for message in turn)]

    while len(turns) > 1 and chat_history_bytes(flatten()) > max_bytes:
        turns.pop(0)

    if turns and chat_history_bytes(flatten()) > max_bytes and len(turns[0]) > 1:
        turns[0] = turns[0][:1]
    if turns and chat_history_bytes(flatten()) > max_bytes:
        turns.clear()

    return flatten()


def build_reset_link(frontend_origin: str, token: str) -> str:
    return f"{frontend_origin}/reset_password#token={quote(token, safe='')}"
