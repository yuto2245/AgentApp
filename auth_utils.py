"""Helpers for credential-based authentication in Chainlit."""
from __future__ import annotations

import os
from typing import Optional, Tuple


def get_expected_credentials() -> Tuple[Optional[str], Optional[str]]:
    """Return the username/password pair expected from environment variables."""
    return os.getenv("CHAINLIT_USERNAME"), os.getenv("CHAINLIT_PASSWORD")


def verify_credentials(
    username: str,
    password: str,
    expected: Optional[Tuple[Optional[str], Optional[str]]] = None,
) -> bool:
    """Compare the provided credentials with the expected ones."""
    expected_username: Optional[str]
    expected_password: Optional[str]

    if expected is None:
        expected_username, expected_password = get_expected_credentials()
    else:
        expected_username, expected_password = expected

    if not expected_username or not expected_password:
        return False
    return username == expected_username and password == expected_password
