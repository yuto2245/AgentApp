import bcrypt
import re
import uuid
from typing import Optional

import asyncpg
from asyncpg.exceptions import UniqueViolationError

from chainlit.user import User

from data_layer import AppDataLayer

EMAIL_REGEX = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)


def normalize_email(value: str) -> Optional[str]:
    if not value:
        return None
    email = value.strip().lower()
    if not EMAIL_REGEX.fullmatch(email):
        return None
    return email


def is_password_valid(password: str) -> bool:
    return bool(password) and len(password) >= 8


def sanitize_role(role: Optional[str]) -> str:
    allowed = {"member", "admin"}
    if not role:
        return "member"
    normalized = role.strip().lower()
    return normalized if normalized in allowed else "member"


async def create_app_user(
    connection: asyncpg.Connection,
    *,
    email: str,
    password: str,
    display_name: Optional[str] = None,
    role: str = "member",
) -> asyncpg.Record:
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    display = display_name or email.split("@")[0]
    return await connection.fetchrow(
        '''
        INSERT INTO "AppUser" (id, email, password_hash, display_name, role)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id, email, password_hash, display_name, role
        ''',
        str(uuid.uuid4()),
        email,
        password_hash,
        display,
        sanitize_role(role),
    )


async def authenticate_email_password(
    username: str,
    password: str,
    data_layer: AppDataLayer,
) -> Optional[User]:
    """メールアドレスとパスワードで AppUser を検証し、Chainlit User を返す。"""
    email = normalize_email(username)
    if not email or not password:
        return None

    # ChainlitDataLayer は lazy connect なので、明示的に接続を確立しておく
    await data_layer.connect()

    # AppUser テーブルから対象ユーザーを取得（メールアドレスはユニーク想定）
    async with data_layer.pool.acquire() as connection:  # type: ignore[attr-defined]
        row: Optional[asyncpg.Record] = await connection.fetchrow(
        """
            SELECT id, email, password_hash, display_name, role
            FROM "AppUser"
            WHERE email = $1
            """,
            email,
        )

        if not row:
            return None

    # ハッシュ化されたパスワードを bcrypt で照合
    if not row:
        return None

    password_hash = row["password_hash"]
    if not password_hash or not bcrypt.checkpw(
        password.encode("utf-8"), password_hash.encode("utf-8")
    ):
        return None

    # Chainlit 側で利用するユーザー情報を組み立てる
    chainlit_user = User(
        identifier=row["email"],
        display_name=row["display_name"] or row["email"],
        metadata={
            "app_user_id": str(row["id"]),
            "role": row.get("role"),
        },
    )

    # Chainlit の User テーブルにも永続化（ON CONFLICT で更新される）
    await data_layer.create_user(chainlit_user)
    return chainlit_user
