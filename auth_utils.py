"""Helpers for credential-based authentication in Chainlit."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional, Tuple, Union

AllowedUsers = Dict[str, str]
CredentialInput = Optional[
    Union[
        Tuple[Optional[str], Optional[str]],
        Mapping[str, str],
        Iterable[Tuple[str, str]],
    ]
]


def _normalise_key(key: str) -> str:
    return key.strip()


def _normalise_value(value: str) -> str:
    return value.strip()


def parse_users_string(raw: str) -> AllowedUsers:
    """Parse a delimited username/password string into a mapping."""

    users: AllowedUsers = {}
    for entry in filter(None, re.split(r"[\n;,]+", raw)):
        if "=" in entry:
            username, password = entry.split("=", 1)
        elif ":" in entry:
            username, password = entry.split(":", 1)
        else:
            continue

        username = _normalise_key(username)
        password = _normalise_value(password)
        if username and password:
            users[username] = password
    return users


def parse_users_file(path: Path) -> AllowedUsers:
    """Load allowed users from a JSON or delimited text file."""

    if not path.exists():
        return {}

    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return parse_users_string(text)

    if isinstance(data, Mapping):
        return {
            _normalise_key(str(username)): _normalise_value(str(password))
            for username, password in data.items()
            if str(username).strip() and str(password).strip()
        }

    if isinstance(data, Iterable):
        parsed: AllowedUsers = {}
        for item in data:
            if (
                isinstance(item, Mapping)
                and "username" in item
                and "password" in item
            ):
                username = _normalise_key(str(item["username"]))
                password = _normalise_value(str(item["password"]))
            elif (
                isinstance(item, Iterable)
                and not isinstance(item, (str, bytes))
            ):
                try:
                    username, password = list(item)[:2]
                except ValueError:
                    continue
                username = _normalise_key(str(username))
                password = _normalise_value(str(password))
            elif isinstance(item, str):
                parsed.update(parse_users_string(item))
                continue
            else:
                continue

            if username and password:
                parsed[username] = password
        return parsed

    return {}


def _merge_users(base: AllowedUsers, new_users: AllowedUsers) -> None:
    for username, password in new_users.items():
        if username and password:
            base[username] = password


def get_allowed_users() -> AllowedUsers:
    """Resolve all configured username/password pairs."""

    users: AllowedUsers = {}

    # Highest priority: explicit JSON payload
    raw_json = os.getenv("CHAINLIT_USERS_JSON")
    if raw_json:
        try:
            parsed_json = json.loads(raw_json)
        except json.JSONDecodeError:
            parsed_json = None
        if isinstance(parsed_json, Mapping):
            _merge_users(
                users,
                {
                    _normalise_key(str(username)): _normalise_value(str(password))
                    for username, password in parsed_json.items()
                    if str(username).strip() and str(password).strip()
                },
            )
        elif isinstance(parsed_json, Iterable):
            for item in parsed_json:
                if (
                    isinstance(item, Mapping)
                    and "username" in item
                    and "password" in item
                ):
                    username = _normalise_key(str(item["username"]))
                    password = _normalise_value(str(item["password"]))
                    if username and password:
                        users[username] = password
                elif isinstance(item, str):
                    _merge_users(users, parse_users_string(item))

    # Next priority: delimited string variable
    raw_users = os.getenv("CHAINLIT_USERS")
    if raw_users:
        _merge_users(users, parse_users_string(raw_users))

    # Optional file override
    users_file = os.getenv("CHAINLIT_USERS_FILE")
    if users_file:
        file_users = parse_users_file(Path(users_file).expanduser())
        _merge_users(users, file_users)

    # Backwards compatibility with single username/password env vars
    username = os.getenv("CHAINLIT_USERNAME")
    password = os.getenv("CHAINLIT_PASSWORD")
    if username and password:
        users[_normalise_key(username)] = _normalise_value(password)

    return users


def get_expected_credentials() -> Tuple[Optional[str], Optional[str]]:
    """Return the first configured credential pair for compatibility uses."""

    allowed = get_allowed_users()
    if not allowed:
        return None, None

    username, password = next(iter(allowed.items()))
    return username, password


def _coerce_expected(expected: CredentialInput) -> AllowedUsers:
    if expected is None:
        return get_allowed_users()

    if isinstance(expected, Mapping):
        return {
            _normalise_key(str(username)): _normalise_value(str(password))
            for username, password in expected.items()
            if str(username).strip() and str(password).strip()
        }

    if isinstance(expected, tuple):
        try:
            username, password = expected
        except ValueError:
            return {}
        if username and password:
            return {_normalise_key(str(username)): _normalise_value(str(password))}
        return {}

    mapping: AllowedUsers = {}
    for item in expected:
        if isinstance(item, tuple) and len(item) >= 2:
            username, password = item[:2]
        elif isinstance(item, Mapping) and {"username", "password"} <= set(item):
            username = item["username"]
            password = item["password"]
        else:
            continue

        username = _normalise_key(str(username))
        password = _normalise_value(str(password))
        if username and password:
            mapping[username] = password

    return mapping


def verify_credentials(
    username: str,
    password: str,
    expected: CredentialInput = None,
) -> bool:
    """Compare the provided credentials with any configured credential set."""

    allowed = _coerce_expected(expected)
    if not allowed:
        return False

    expected_password = allowed.get(_normalise_key(username))
    if expected_password is None:
        return False

    return expected_password == _normalise_value(password)
