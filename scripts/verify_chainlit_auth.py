"""Utility to verify that Chainlit password authentication is correctly configured."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional, Tuple

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from auth_utils import get_expected_credentials, verify_credentials


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check whether the current CHAINLIT_USERNAME and CHAINLIT_PASSWORD can "
            "authenticate against the Chainlit password callback."
        )
    )
    parser.add_argument(
        "--username",
        help=(
            "Username to test. Defaults to the value of the CHAINLIT_USERNAME "
            "environment variable."
        ),
    )
    parser.add_argument(
        "--password",
        help=(
            "Password to test. Defaults to the value of the CHAINLIT_PASSWORD "
            "environment variable."
        ),
    )
    parser.add_argument(
        "--expected-username",
        help=(
            "Expected username to validate against. Defaults to CHAINLIT_USERNAME "
            "from the environment."
        ),
    )
    parser.add_argument(
        "--expected-password",
        help=(
            "Expected password to validate against. Defaults to CHAINLIT_PASSWORD "
            "from the environment."
        ),
    )
    parser.add_argument(
        "--no-dotenv",
        action="store_true",
        help="Skip loading variables from a .env file in the project root.",
    )
    return parser.parse_args()


def resolve_expected_credentials(
    expected_username_arg: Optional[str], expected_password_arg: Optional[str]
) -> Tuple[Optional[str], Optional[str]]:
    if expected_username_arg is not None or expected_password_arg is not None:
        if expected_username_arg is None or expected_password_arg is None:
            raise ValueError("Provide both --expected-username and --expected-password.")
        return expected_username_arg, expected_password_arg
    return get_expected_credentials()


def main() -> int:
    args = parse_args()

    if not args.no_dotenv:
        load_dotenv()

    username = args.username or os.getenv("CHAINLIT_USERNAME")
    password = args.password or os.getenv("CHAINLIT_PASSWORD")

    if not username or not password:
        print(
            "[verify_chainlit_auth] Missing credentials. Provide --username/--password "
            "or set CHAINLIT_USERNAME/CHAINLIT_PASSWORD."
        )
        return 2

    try:
        expected = resolve_expected_credentials(
            args.expected_username, args.expected_password
        )
    except ValueError as exc:
        print(f"[verify_chainlit_auth] {exc}")
        return 2

    if not all(expected):
        print(
            "[verify_chainlit_auth] CHAINLIT_USERNAME/CHAINLIT_PASSWORD are not set in the environment."
        )
        return 2

    if not verify_credentials(username, password, expected):
        print("[verify_chainlit_auth] Authentication failed.")
        return 1

    print(f"[verify_chainlit_auth] Authentication succeeded for user '{username}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
