import os
import bcrypt
import re
import uuid
import secrets
import datetime
import smtplib
from email.message import EmailMessage
from typing import Optional

import asyncpg

from chainlit.user import User

from data_layer import AppDataLayer

EMAIL_REGEX = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
FROM_EMAIL = os.getenv("FROM_EMAIL", SMTP_USER)
APP_BASE_URL = os.getenv("APP_BASE_URL", "https://agent-app-ea2ada95ebce.herokuapp.com").rstrip("/")
EMAIL_VERIFICATION_REQUIRED = os.getenv("EMAIL_VERIFICATION_REQUIRED", "true").lower() in {"1", "true", "yes", "on"}


def _now_utc() -> datetime.datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.datetime.now(datetime.timezone.utc)


def build_verification_url(token: str) -> str:
    return f"{APP_BASE_URL}/verify?token={token}"


def send_verification_email(
    display_name: Optional[str],
    to_email: str,
    auth_url: str,
    token_expiry: datetime.datetime,
) -> None:
    """Send a simple verification mail if SMTP credentials are configured."""
    if not (SMTP_HOST and SMTP_USER and SMTP_PASSWORD and FROM_EMAIL):
        print("メール送信設定が未構成のため、認証メールは送信されませんでした。")
        return

    subject = "AgentApp メール認証のお願い"
    body = (
        f"{display_name or to_email} さん\n\n"
        f"以下のリンクを {token_expiry:%Y-%m-%d %H:%M} までにクリックして認証を完了してください。\n\n"
        f"{auth_url}\n\n"
        "もし心当たりがなければ、本メールを破棄してください。"
    )

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = FROM_EMAIL
    message["To"] = to_email
    message.set_content(body)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.send_message(message)
    except Exception as exc:
        print(f"メール送信エラー: {exc}")
        raise


def normalize_email(value: str) -> Optional[str]:
    if not value:
        return None
    email = value.strip().lower()
    if not EMAIL_REGEX.fullmatch(email):
        return None
    return email

'''パスワードチェック→フロント側のチェックと同等の認証を実施する'''
def is_password_valid(password: str) -> bool:
    if not password or len(password) < 8:
        return False
    if not re.search(r"[a-z]",password):
        return False
    if not re.search(r"[A-Z]",password):
        return False
    if not re.search(r"[0-9]",password):
        return False
    if not re.search(r"[!@#$%^&*]", password):
        return False
    
    return True


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
    status: str = "pending",
    email_token: Optional[str] = None,
    token_expiry: Optional[datetime.datetime] = None,
    role: str = "member",
) -> asyncpg.Record:
    require_verification = EMAIL_VERIFICATION_REQUIRED
    token: Optional[str]
    expiry: Optional[datetime.datetime]

    if require_verification:
        token = email_token or secrets.token_urlsafe(48)
        expiry = token_expiry or (_now_utc() + datetime.timedelta(days=1))
        status_value = status or "pending"
    else:
        token = None
        expiry = None
        status_value = status or "active"

    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    display = display_name or email.split("@")[0]
    row = await connection.fetchrow(
        '''
        INSERT INTO "AppUser" (id, email, password_hash, display_name, role, status, email_token, token_expiry)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING id, email, password_hash, display_name, role, status, email_token, token_expiry
        ''',
        str(uuid.uuid4()),
        email,
        password_hash,
        display,
        sanitize_role(role),
        status_value,
        token,
        expiry,
    )
    if require_verification and token:
        auth_url = build_verification_url(token)
        if expiry is None:
            expiry = _now_utc() + datetime.timedelta(days=1)
        send_verification_email(display, email, auth_url, expiry)
    return row


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
            SELECT id, email, password_hash, display_name, role, status, token_expiry
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
    if EMAIL_VERIFICATION_REQUIRED and row.get("status") != "active":
        return None
    if row.get("token_expiry") and row["token_expiry"] < _now_utc():
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
