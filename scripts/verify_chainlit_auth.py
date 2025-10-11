"""Utility to verify that Chainlit password authentication is correctly configured."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, Optional

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from auth_utils import (
    get_allowed_users,
    parse_users_file,
    parse_users_string,
    verify_credentials,
)


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
            "Deprecated in favour of --allowed-users. Provide alongside "
            "--expected-password to test a single credential pair."
        ),
    )
    parser.add_argument(
        "--expected-password",
        help=(
            "Deprecated in favour of --allowed-users. Provide alongside "
            "--expected-username to test a single credential pair."
        ),
    )
    parser.add_argument(
        "--allowed-users",
        help=(
            "Override allowed users with a delimited string of username=password "
            "pairs. Accepts comma, semicolon, or newline separators."
        ),
    )
    parser.add_argument(
        "--allowed-users-file",
        help=(
            "Path to a JSON or newline-delimited file describing allowed users. "
            "Each entry should be a username/password pair."
        ),
    )
    parser.add_argument(
        "--list-allowed",
        action="store_true",
        help="List the resolved usernames and exit without performing verification.",
    )
    parser.add_argument(
        "--no-dotenv",
        action="store_true",
        help="Skip loading variables from a .env file in the project root.",
    )
    return parser.parse_args()


def resolve_allowed_users(args: argparse.Namespace) -> Dict[str, str]:
    if args.expected_username is not None or args.expected_password is not None:
        if args.expected_username is None or args.expected_password is None:
            raise ValueError(
                "Provide both --expected-username and --expected-password or omit both."
            )
        return {args.expected_username: args.expected_password}

    users: Dict[str, str] = {}

    if args.allowed_users:
        users.update(parse_users_string(args.allowed_users))

    if args.allowed_users_file:
        users.update(parse_users_file(Path(args.allowed_users_file).expanduser()))

    if users:
        return users

    return get_allowed_users()


def main() -> int:
    args = parse_args()

    if not args.no_dotenv:
        load_dotenv()

    username = args.username or os.getenv("CHAINLIT_USERNAME")
    password = args.password or os.getenv("CHAINLIT_PASSWORD")

    if not username or not password:
        print(
            "[verify_chainlit_auth] Missing credentials. Provide --username/--password "
            "or set CHAINLIT_USERNAME/CHAINLIT_PASSWORD. When using CHAINLIT_USERS* "
            "environment variables, pass the credentials with --username/--password."
        )
        return 2

    try:
        allowed_users = resolve_allowed_users(args)
    except ValueError as exc:
        print(f"[verify_chainlit_auth] {exc}")
        return 2

    if args.list_allowed:
        if not allowed_users:
            print("[verify_chainlit_auth] No allowed users are configured.")
            return 1

        print("[verify_chainlit_auth] Allowed usernames:")
        for allowed_username in sorted(allowed_users):
            print(f"  - {allowed_username}")
        return 0

    if not allowed_users:
        print(
            "[verify_chainlit_auth] No allowed users were resolved. Set CHAINLIT_USERS, "
            "CHAINLIT_USERS_JSON, CHAINLIT_USERS_FILE, or CHAINLIT_USERNAME/CHAINLIT_PASSWORD."
        )
        return 2

    if not verify_credentials(username, password, allowed_users):
        print("[verify_chainlit_auth] Authentication failed.")
        return 1

    print(f"[verify_chainlit_auth] Authentication succeeded for user '{username}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
