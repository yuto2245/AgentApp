import os
import re
import json
import asyncio
import time
import base64
from pathlib import Path
import chainlit as cl
from chainlit.input_widget import Select, Switch
from chainlit.types import ThreadDict
from typing import Optional, Dict, Any, List

from chainlit.user import User

from data_layer import AppDataLayer
from auth import (
    authenticate_email_password,
    create_app_user,
    is_password_valid,
    normalize_email,
    sanitize_role,
    _now_utc,
    EMAIL_VERIFICATION_REQUIRED,
)
from chainlit.server import app as chainlit_server_app
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, constr, validator


# --- Provider SDKs ---
from openai import OpenAI, AsyncOpenAI
from anthropic import AsyncAnthropic
from xai_sdk import Client
from xai_sdk.chat import user, system,assistant
from xai_sdk.search import SearchParameters
from google import genai
from google.genai.types import Tool, GenerateContentConfig, GoogleSearch, UrlContext

# --- Langchain Core ---
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

# --- Environment Loading ---
from dotenv import load_dotenv
load_dotenv()

# ---日付の取得 ---
from datetime import datetime
now = datetime.now()
print("日付と時刻",now)

# --- APIキーの読み込みとクライアントの初期化 ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
XAI_API_KEY = os.getenv("XAI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

# クライアントはグローバルに初期化しておくと効率的
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
openai_async_client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
anthropic_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None
xai_client = Client(api_key=XAI_API_KEY) if XAI_API_KEY else None
gemini_client = genai.Client(api_key=GOOGLE_API_KEY) if GOOGLE_API_KEY else None

# Chainlitのトレース機能
cl.instrument_openai()

# --- Authentication & Persistence ---
def _normalize_database_url(raw_url: Optional[str]) -> str:
    """Herokuなどの`postgres://`形式をasyncpg互換に揃える。"""
    if not raw_url:
        raise RuntimeError("DATABASE_URL is not set. Configure your Postgres connection string.")
    if raw_url.startswith("postgres://"):
        return raw_url.replace("postgres://", "postgresql://", 1)
    return raw_url


_DATA_LAYER: Optional[AppDataLayer] = None


def _get_data_layer() -> AppDataLayer:
    """データレイヤーをシングルトン的に生成・共有するヘルパー。"""
    global _DATA_LAYER
    if _DATA_LAYER is None:
        normalized_url = _normalize_database_url(DATABASE_URL)
        _DATA_LAYER = AppDataLayer(database_url=normalized_url)
    return _DATA_LAYER


def _model_index_by_label(label: Optional[str]) -> int:
    if not label:
        return DEFAULT_MODEL_INDEX
    for idx, model in enumerate(AVAILABLE_MODELS):
        if model.get("label") == label:
            return idx
    return DEFAULT_MODEL_INDEX


def _prompt_index_by_label(label: Optional[str]) -> int:
    if not label:
        return DEFAULT_PROMPT_INDEX
    for idx, prompt in enumerate(SYSTEM_PROMPT_CHOICES):
        if prompt.get("label") == label:
            return idx
    return DEFAULT_PROMPT_INDEX


def _prompt_label_from_content(content: Optional[str]) -> Optional[str]:
    if not content:
        return None
    for prompt in SYSTEM_PROMPT_CHOICES:
        if prompt.get("content") == content:
            return prompt.get("label")
    return None


def _normalize_display_text(text: str) -> str:
    if not text:
        return ""
    normalized = (
        text.replace("\\r\\n", "\n")
        .replace("\\n", "\n")
        .replace("\\r", "\n")
        .replace("\\t", "\t")
    )
    return normalized


def _extract_text_from_payload(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, dict):
        for key in ("text", "message", "content", "value", "prompt"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return _normalize_display_text(value)
            if isinstance(value, (dict, list)):
                nested = _extract_text_from_payload(value)
                if nested:
                    return nested
        for value in payload.values():
            if isinstance(value, str) and value.strip():
                return _normalize_display_text(value)
            if isinstance(value, (dict, list)):
                nested = _extract_text_from_payload(value)
                if nested:
                    return nested
        return ""
    if isinstance(payload, list):
        for item in payload:
            nested = _extract_text_from_payload(item)
            if nested:
                return nested
        return ""
    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            return ""
        try:
            data = json.loads(text)
            return _extract_text_from_payload(data)
        except Exception:
            return _normalize_display_text(text)
    return _normalize_display_text(str(payload))


def _rebuild_conversation_history(thread: ThreadDict) -> List[HumanMessage | AIMessage]:
    history: List[HumanMessage | AIMessage] = []
    steps = thread.get("steps") or []
    sorted_steps = sorted(
        steps,
        key=lambda step: step.get("createdAt") or "",
    )
    for step in sorted_steps:
        step_type = step.get("type")
        if step_type in ("assistant_message",):
            text = _extract_text_from_payload(step.get("output") or step.get("input"))
            if text:
                history.append(AIMessage(content=text))
        elif step_type in ("user_message", "run"):
            text = _extract_text_from_payload(step.get("input") or step.get("output"))
            if text:
                history.append(HumanMessage(content=text))
    return history


async def _send_chat_settings(
    initial_model_index: int,
    initial_prompt_index: int,
    tools_enabled: bool,
):
    return await cl.ChatSettings([
        Select(
            id="model",
            label="モデル",
            values=[m["label"] for m in AVAILABLE_MODELS],
            initial_index=initial_model_index,
        ),
        Select(
            id="system_prompt",
            label="システムプロンプト（AIの性格・役割）",
            values=[p["label"] for p in SYSTEM_PROMPT_CHOICES],
            initial_index=initial_prompt_index,
        ),
        Switch(
            id="tools_enabled",
            label="Tools（Web検索/実行/MCP）",
            initial=tools_enabled,
        ),
    ]).send()


async def _persist_thread_metadata() -> None:
    try:
        thread_id = getattr(cl.context.session, "thread_id", None)
    except Exception:
        return

    if not thread_id:
        return

    try:
        model_info = cl.user_session.get("model")
        system_prompt = cl.user_session.get("system_prompt")
        tools_enabled = bool(cl.user_session.get("tools_enabled", False))
    except Exception:
        return

    data_layer = _get_data_layer()

    model_label = model_info.get("label") if isinstance(model_info, dict) else None
    prompt_label = _prompt_label_from_content(system_prompt if isinstance(system_prompt, str) else None)

    metadata: Dict[str, Any] = {
        "settings": {
            "model_label": model_label,
            "system_prompt_label": prompt_label,
            "tools_enabled": tools_enabled,
        }
    }

    try:
        await data_layer.update_thread(thread_id=thread_id, metadata=metadata)
    except Exception as exc:
        print(f"Failed to persist thread metadata: {exc}")


SIGNUP_HTML_PATH = Path(__file__).parent / "public" / "auth" / "signup.html"


class RegisterRequest(BaseModel):
    email: constr(min_length=5, strip_whitespace=True)
    password: constr(min_length=8)
    display_name: constr(min_length=1, strip_whitespace=True)
    role: Optional[str] = None

    @validator("email")
    def validate_email(cls, value: str) -> str:
        email = normalize_email(value or "")
        if not email:
            raise ValueError("有効なメールアドレスを入力してください。")
        return email


class RegisterResponse(BaseModel):
    id: str
    email: str
    display_name: str
    role: str


router = APIRouter(prefix="/api")


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register_user(payload: RegisterRequest):
    data_layer = _get_data_layer()
    await data_layer.connect()

    email = payload.email
    display_name = payload.display_name.strip()
    role = sanitize_role(payload.role)

    if not is_password_valid(payload.password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="パスワードは8文字以上で入力してください。")

    async with data_layer.pool.acquire() as connection:  # type: ignore[attr-defined]
        existing = await connection.fetchval('SELECT 1 FROM "AppUser" WHERE email = $1', email)
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="このメールアドレスは既に登録されています。")

        row = await create_app_user(
            connection,
            email=email,
            password=payload.password,
            display_name=display_name,
            role=role,
        )

    return RegisterResponse(
        id=str(row["id"]),
        email=row["email"],
        display_name=row["display_name"],
        role=row["role"],
    )

@router.get("/users/count")
async def users_count():
    data_layer = _get_data_layer()
    # Ensure connection (ChainlitDataLayer is lazy)
    await data_layer.connect()
    async with data_layer.pool.acquire() as conn:  # type: ignore[attr-defined]
        app_user_count = await conn.fetchval('SELECT COUNT(*) FROM "AppUser"')
        chainlit_user_count = await conn.fetchval('SELECT COUNT(*) FROM "User"')
        mau = await conn.fetchval("SELECT COUNT(DISTINCT \"userId\") FROM \"Thread\" WHERE \"createdAt\" >= NOW() - INTERVAL '30 days'")
        wau = await conn.fetchval("SELECT COUNT(DISTINCT \"userId\") FROM \"Thread\" WHERE \"createdAt\" >= NOW() - INTERVAL '7 days'")
        dau = await conn.fetchval("SELECT COUNT(DISTINCT \"userId\") FROM \"Thread\" WHERE \"createdAt\" >= NOW() - INTERVAL '1 day'")
    return {
        "app_user_count": int(app_user_count or 0),
        "chainlit_user_count": int(chainlit_user_count or 0),
        "active": {"MAU": int(mau or 0), "WAU": int(wau or 0), "DAU": int(dau or 0)},
    }

@chainlit_server_app.get("/verify")
async def verify_email(token: str):
    if not EMAIL_VERIFICATION_REQUIRED:
        return RedirectResponse(url="/public/auth/index.html?verified=disabled")
    data_layer = _get_data_layer()
    await data_layer.connect()
    async with data_layer.pool.acquire() as conn:
        row = await conn.fetchrow(
            '''
            SELECT id, token_expiry
            FROM "AppUser"
            WHERE email_token = $1
            ''',
            token,
        )
        if not row:
            raise HTTPException(status_code=404, detail="無効なトークンです。")
        if row["token_expiry"] and row["token_expiry"] < _now_utc():
            raise HTTPException(status_code=400, detail="トークンの有効期限が切れています。")
        await conn.execute(
            '''
            UPDATE "AppUser"
            SET status = 'active', email_token = NULL, token_expiry = NULL, "updatedAt" = NOW()
            WHERE id = $1
            ''',
            row["id"],
        )
        #ユーザー登録の完了後、ログイン画面にリダイレクト
        return RedirectResponse(url="/public/auth/index.html?verified=success")

@chainlit_server_app.get("/register")
async def register_page():
    if not SIGNUP_HTML_PATH.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="登録ページが存在しません")
    return RedirectResponse(url="/public/auth/signup.html")


@chainlit_server_app.get("/", include_in_schema=False)
async def root_redirect():
    """アプリ起動時に認証トップへ誘導する。"""
    return RedirectResponse(url="/public/auth/index.html")


chainlit_server_app.include_router(router)


@cl.password_auth_callback
async def password_auth(username: str, password: str) -> Optional[User]:
    """アプリ側のユーザーテーブルで認証し、Chainlit に返す。"""
    data_layer = _get_data_layer()
    user = await authenticate_email_password(username, password, data_layer)
    if user:
        return user
    return None


@cl.data_layer
def configure_data_layer() -> AppDataLayer:
    """Chainlit に利用させるデータレイヤーを返す。"""
    return _get_data_layer()

# --- モデルリストの定義 ---
AVAILABLE_MODELS = [
    { "label": "GPT-5 Chat", "value": "gpt-5-chat-latest", "type": "openai"},
    { "label": "GPT-5 Pro", "value": "gpt-5-pro-2025-10-06", "type": "openai"},
    { "label": "GPT-5.1", "value": "gpt-5.1-2025-11-13", "type": "openai"},
    { "label": "GPT-5.1-Codex", "value": "gpt-5.1-codex", "type": "openai" },
    { "label": "GPT-5.1-Codex-mini", "value": "gpt-5.1-codex-mini", "type": "openai" },
    { "label": "Gemini 2.5 Flash-Lite", "value": "gemini-2.5-flash-lite", "type": "gemini" },
    { "label": "Gemini 2.5 Flash", "value": "gemini-2.5-flash", "type": "gemini" },
    { "label": "Gemini 2.5 Pro", "value": "gemini-2.5-pro", "type": "gemini" },
    { "label": "Gemini flash latest", "value": "gemini-flash-latest", "type": "gemini" },
    { "label": "Gemini 3.0 Pro-Preview", "value": "gemini-3-pro-preview", "type": "gemini" },
    { "label": "Claude Opus4.5", "value": "claude-opus-4-5-20251101", "type": "claude" },
    { "label": "Claude Sonnet 4.5", "value": "claude-sonnet-4-5-20250929", "type": "claude" },
    { "label": "Claude Haiku 4.5", "value": "claude-haiku-4-5-20251001", "type": "claude" },
    { "label": "Grok4", "value": "grok-4-0709", "type": "grok" },
    { "label": "Grok4.1 fast non-reasoning", "value": "grok-4-1-fast-non-reasoning-latest", "type": "grok" },
    { "label": "Grok4.1 fast reasoning", "value": "grok-4-1-fast-reasoning-latest", "type": "grok" },
    { "label": "Grok Code Fast 1", "value": "grok-code-fast-1", "type": "grok" },
]
DEFAULT_MODEL_INDEX = 0
#darkモード、lightモードでimg_colorを切り替える
ICON_IMG = {
    "openai": "/public/img/openai.png",
    "claude": "/public/img/claude.png",
    "gemini": "/public/img/gemini.png",
    "grok": "/public/img/grok.png",
    }   

# --- Profile Setting ---
@cl.set_chat_profiles

async def chat_profile():
    return [
        cl.ChatProfile(
            name=p["label"],
            markdown_description=p["value"],
            # LobeHub CDNを利用
            #icon=f"https://unpkg.com/@lobehub/icons-static-png@latest/dark/{p['type']}.png",
            icon = ICON_IMG[p['type']],
        )
        for p in AVAILABLE_MODELS
    ]


# --- システムプロンプトの定義 ---
current_time = now.strftime("%Y-%m-%d %H:%M")
SYSTEM_PROMPT_CHOICES = [
    { "label": "標準アシスタント", "content": "Current time: {current_time}\nYou are a helpful assistant." },
    { "label": "丁寧な説明", "content": "Current time: {current_time}\nUse a formal tone, providing clear, well-structured sentences and precise language." },
    { "label": "簡潔な回答", "content": "Current time: {current_time}\nRespond briefly and directly, using as few words as possible." },
    { "label": "ソクラテス式", "content": "Current time: {current_time}\nRespond as a Socratic teacher, guiding the user through questions and reasoning to foster deep understanding." },
    { "label": "学習モード", "content": "Current time: {current_time}\nYou are act as a personal learning coach for the user.\n\nGoals:\n- Help the user deeply understand concepts (especially programming, computer science, math, English, and software engineering).\n- Always show your reasoning step by step and use concrete, realistic examples.\n- Default output language is Japanese, but include important technical terms and code comments in English when helpful.\n\nBehavior:\n1. At the beginning of a new topic, briefly confirm the user's goal and current level in 1–3 short questions, unless it is already clear.\n2. Then propose a short learning plan (bullet list of steps) and follow it during the conversation.\n3. Explain in small chunks rather than long lectures. After each key idea, ask a simple check question or give a tiny exercise, and wait for the user's answer before continuing.\n4. Use a mix of explanation and Socratic questioning: guide the user to think on their own, but do not refuse to explain. If the user seems stuck, clearly explain the answer and why.\n5. When writing code, prefer TypeScript/JavaScript or Python unless the user requests another language. Keep examples minimal but realistic and runnable.\n6. When the user makes a mistake or has a misunderstanding, correct it直接かつ丁寧に: clearly say what is wrong, why it is wrong, and how to fix the mental model.\n7. Regularly relate abstract ideas to具体的なイメージ, analogies, or everyday examples to strengthen intuition.\n8. At natural breakpoints, summarize the key points and suggest 1–3具体的な次のアクション (practice tasks, mini-projects, or review items).\n\nConstraints:\n- Be honest when you do not know something or when information is uncertain. Do not invent library APIs, specs, or facts.\n- Avoid曖昧なアドバイス; always anchor explanations in具体的な手順, examples, or scenarios.\n- Use clear Markdown formatting (headings, bullet lists, code blocks) to make the content easy to read.\n- Keep a calm, direct, and supportive tone; do not flatter the user, but respect their努力 and treat them as a serious learner." }

]
DEFAULT_PROMPT_INDEX = 0

# --- Command Setting ---
COMMANDS_BASE = [
    { "id": "Picture",   "label": "Picture",   "icon": "image",  "description": "Use gpt4.1-mini to generate an image" },
    { "id": "Code", "label": "Code", "icon": "code", "description": "Open the coding workbench (editor/preview)" },
    { "id": "slide", "label": "Slide", "icon": "presentation", "description": "Generate a slide presentation from text" },
]

# コマンドは画像系のみ表示（Toolsトグルは設定パネルのスイッチで管理）

# OpenAI用のツール定義（有効時のみ付与）
OPENAI_ALL_TOOLS = [
    {"type": "web_search"},
    {"type": "code_interpreter", "container": {"type": "auto"}},
    {"type": "image_generation"},
    {
        "type": "mcp",
        "server_label": "deepwiki",
        "server_url": "https://mcp.deepwiki.com/mcp",
        "require_approval": "never",
    },
]

# --- Chainlit App Logic ---
@cl.on_chat_start
async def start():
    html = """
    <style>
      /* 背景を透過寄りにしたい場合に調整。不要なら削除可 */
      body { background: transparent !important; }
    </style>
    <script src="/public/custom.js"></script>
    """
    await cl.Html(html)
    await cl.Message(content="WebGL 背景を適用しました。").send()
    
async def open_code_workbench(
    code: Optional[str] = None,
    title: str = "Code Workbench",
    filename: str = "index.html",
    language: str = "html",
    read_only: bool = False,
    auto_preview: bool = True,
):
    version = cl.user_session.get("workbench_version", 0) + 1
    cl.user_session.set("workbench_version", version)
    props = {
        "code": code,
        "title": title,
        "filename": filename,
        "language": language,
        "readOnly": read_only,
        "autoPreview": auto_preview,
        "key": f"workbench-{version}",
    }
    element = cl.CustomElement(name="CodeWorkbench", props=props, display="inline")
    await cl.ElementSidebar.set_title("Code Workbench")
    await cl.ElementSidebar.set_elements([element])


async def open_slide_preview(slides_json: str, title: str = "Slide Preview"):
    version = cl.user_session.get("slide_preview_version", 0) + 1
    cl.user_session.set("slide_preview_version", version)
    # Debug to terminal: always log a short preview
    try:
        preview = (slides_json or "")[:800]
        length_info = 0
        try:
            data = json.loads(slides_json)
            if isinstance(data, list):
                length_info = len(data)
        except Exception:
            pass
        print("[SlideDebug] open_slide_preview: length=", length_info)
        print("[SlideDebug] open_slide_preview preview:\n", preview)
    except Exception:
        pass
    props = {"slides_json": slides_json, "title": title, "key": f"slide-preview-{version}"}
    element = cl.CustomElement(name="SlidePreview", props=props, display="inline")
    await cl.ElementSidebar.set_title(title)
    await cl.ElementSidebar.set_elements([element])

# より柔軟なフェンス検出: 言語指定/オプション/改行の有無を許容
FENCE_ANY_RE = re.compile(r"^\s*```(.*?)$\n(.*?)^\s*```\s*$", re.MULTILINE | re.DOTALL)

SLIDE_GENERATION_PROMPT_TEMPLATE = """
あなたはプロのプレゼンテーション作成アシスタントです。
以下のユーザーの要望に基づいて、Marpit風のMarkdownを本文に含むスライド構成をJSONで出力してください。

# JSONスキーマ
- ルートはスライドオブジェクトの配列です（例: `[ {...}, {...} ]`）。
- 各スライドオブジェクトは以下のキーを持つことができます:
  - `title` (string, optional): スライドのタイトル（Markdownの`#`相当）。
  - `content` (string, optional): スライド本文（Markdown）。箇条書きや太字、表など可。改行は`\\n`。
  - `directives` (object, optional): `header`, `footer`, `class`, `backgroundColor`などの表示指示。
  - `notes` (string, optional): スピーカーノート。

# 出力例（そのままJSON配列として返す。コードフェンス禁止）
[
  {"title": "タイトル", "content": "発表者: あなたの名前\\n\\nこれは開始スライドです。"},
  {"title": "アジェンダ", "content": "- 項目1\\n- 項目2\\n- 項目3"}
]

# 厳守事項
- 返答はJSON配列のみ。前後に説明文やコードフェンス（```）を含めない。
- Markdownの改行は必ず`\\n`を使用。

---
ユーザーの要望:
{user_input}
"""

def extract_fenced_code(text: str) -> Optional[str]:
    """マークダウンから最初のフェンスコードブロックを抽出する。"""
    if not text:
        return None
    # finditer を使ってすべてのコードブロックを試し、最初に見つかったものを返す
    for m in FENCE_ANY_RE.finditer(text):
        code = (m.group(2) or "").strip()
        if code:
            return code
    return None

def extract_json_array(text: str) -> Optional[str]:
    """LLM応答からJSON配列を安全に取り出し、妥当なら文字列として返す。
    1) そのままJSONとしてロード
    2) 角括弧で囲まれた最初のブロックを抽出してロード
    3) フェンスコードから抽出してロード
    失敗したらNone。
    """
    if not text:
        return None
    t = text.strip()
    # 1) 直接ロード
    try:
        data = json.loads(t)
        if isinstance(data, list):
            return json.dumps(data, ensure_ascii=False)
        if isinstance(data, dict) and isinstance(data.get("slides"), list):
            return json.dumps(data["slides"], ensure_ascii=False)
    except Exception:
        pass
    # 2) [ ... ] ブロックを抽出（まず最初の [ から最後の ] までを貪欲に）
    try:
        first = t.find('[')
        last = t.rfind(']')
        if first != -1 and last != -1 and last > first:
            candidate = t[first:last+1]
            data = json.loads(candidate)
            if isinstance(data, list):
                return json.dumps(data, ensure_ascii=False)
            if isinstance(data, dict) and isinstance(data.get("slides"), list):
                return json.dumps(data["slides"], ensure_ascii=False)
    except Exception:
        pass
    # 2b) 非貪欲（保険）
    m = re.search(r"\[([\s\S]*?)\]", t)
    if m:
        candidate = "[" + m.group(1) + "]"
        try:
            data = json.loads(candidate)
            if isinstance(data, list):
                return json.dumps(data, ensure_ascii=False)
        except Exception:
            pass
    # 3) フェンスから抽出
    fenced = extract_fenced_code(t)
    if fenced:
        try:
            data = json.loads(fenced)
            if isinstance(data, list):
                return json.dumps(data, ensure_ascii=False)
            if isinstance(data, dict) and isinstance(data.get("slides"), list):
                return json.dumps(data["slides"], ensure_ascii=False)
        except Exception:
            pass
    return None


HTML_TAG_HINTS = ("<html", "<head", "<body", "<header", "<section", "<div", "<main", "<footer", "<h1", "<p", "<nav", "<ul", "<li")

def extract_html_code(text: str) -> Optional[str]:
    if not text:
        return None
    t = text.strip()

    # 1) 完全な <html>...</html> を最優先
    full = re.search(r"<html[\s\S]*?</html>", t, re.IGNORECASE)
    if full:
        code = full.group(0).strip()
        return code

    # 2) フェンスコードをすべて列挙し、HTMLっぽいものを優先選択
    candidates: list[tuple[str, str]] = []  # (lang, code)
    for m in FENCE_ANY_RE.finditer(t):
        lang = (m.group(1) or "").strip().lower()
        code = (m.group(2) or "").strip()
        candidates.append((lang, code))

    # 言語がhtml/htm/xml/markup の候補を優先
    for lang, code in candidates:
        if lang in ("html", "htm", "xml", "markup") and code:
            return code
    # タグヒントを含む候補を次点で採用
    for _, code in candidates:
        if code and any(h in code.lower() for h in HTML_TAG_HINTS):
            return code
    # 何もないがとにかく最初の候補があるなら返す
    if candidates:
        return candidates[0][1]

    # 3) フェンスが無くても、本文中にHTMLタグ断片があれば採用
    if any(h in t.lower() for h in HTML_TAG_HINTS):
        return t

    # デバッグ用の簡易ログ（本番でも安全）
    try:
        preview = t[:200].replace("\n", " ⏎ ")
        print(f"[extract_html_code] no match. preview='{preview}'")
    except Exception:
        pass
    return None

def extract_js_code(text: str) -> Optional[str]:
    """LLM応答からJavaScript/TypeScriptのコードブロックを抽出。"""
    if not text:
        return None
    t = text.strip()
    # 優先: 言語指定ありのフェンス
    for m in FENCE_ANY_RE.finditer(t):
        lang = (m.group(1) or "").strip().lower()
        code = (m.group(2) or "").strip()
        if lang in ("javascript", "js", "typescript", "ts") and code:
            return code
    # 次点: 最初のフェンス
    m = FENCE_ANY_RE.search(t)
    return (m.group(2).strip() if m else None)


@cl.on_chat_start
async def start_chat():
    """チャット開始時に呼び出され、設定UIを初期化します。"""
    # Toolsトグルの初期状態をセッションに保存（デフォルト: OFF）
    tools_enabled = cl.user_session.get("tools_enabled")
    if tools_enabled is None:
        tools_enabled = False
        cl.user_session.set("tools_enabled", tools_enabled)

    # メッセージバーのコマンドボタンを登録（画像系のみ）
    try:
        await cl.context.emitter.set_commands(COMMANDS_BASE)
    except Exception as e:
        print(f"Failed to set commands: {e}")
    # プロファイル選択（name=プロンプトのlabel）から初期プロンプトのインデックスを決定
    profile_name = cl.user_session.get("chat_profile")
    initial_model_index = DEFAULT_MODEL_INDEX
    if isinstance(profile_name, str):
        for i, p in enumerate(AVAILABLE_MODELS):
            if p["label"] == profile_name:
                initial_model_index = i
                break
    #プロファイル選択
    profile_name = cl.user_session.get("chat_profile")
    initial_prompt_index = DEFAULT_PROMPT_INDEX
    if isinstance(profile_name, str):
        for i, p in enumerate(SYSTEM_PROMPT_CHOICES):
            if p["label"] == profile_name:
                initial_prompt_index = i
                break
    
    # 設定UI（モデルは設定パネルで切替。プロフィールはプロンプトのみ反映）
    settings = await _send_chat_settings(
        initial_model_index=initial_model_index,
        initial_prompt_index=initial_prompt_index,
        tools_enabled=tools_enabled,
    )
    
    # 初期設定を設定（UIの初期値に合わせる）
    initial_model = AVAILABLE_MODELS[DEFAULT_MODEL_INDEX]
    initial_prompt = SYSTEM_PROMPT_CHOICES[initial_prompt_index]["content"]
    
    cl.user_session.set("model", initial_model)
    cl.user_session.set("system_prompt", initial_prompt)
    cl.user_session.set("conversation_history", [])
    
    print(f"Initial setup: Model={initial_model['label']}, Prompt={SYSTEM_PROMPT_CHOICES[DEFAULT_PROMPT_INDEX]['label']}")
    
    await setup_agent(settings)


@cl.on_chat_resume
async def resume_chat(thread: ThreadDict):
    """既存スレッドを再開する際にセッション状態を復元する。"""
    metadata = thread.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    stored_settings = metadata.get("settings")
    if not isinstance(stored_settings, dict):
        stored_settings = {}

    model_label = stored_settings.get("model_label")
    prompt_label = stored_settings.get("system_prompt_label")
    tools_enabled = bool(stored_settings.get("tools_enabled", False))

    model_index = _model_index_by_label(model_label)
    prompt_index = _prompt_index_by_label(prompt_label)
    selected_model = AVAILABLE_MODELS[model_index]
    selected_prompt = SYSTEM_PROMPT_CHOICES[prompt_index]["content"]

    cl.user_session.set("model", selected_model)
    cl.user_session.set("system_prompt", selected_prompt)
    cl.user_session.set("tools_enabled", tools_enabled)
    cl.user_session.set("conversation_history", _rebuild_conversation_history(thread))
    cl.user_session.set("previous_response_id", None)

    try:
        await cl.context.emitter.set_commands(COMMANDS_BASE)
    except Exception as e:
        print(f"Failed to set commands on resume: {e}")

    settings = await _send_chat_settings(
        initial_model_index=model_index,
        initial_prompt_index=prompt_index,
        tools_enabled=tools_enabled,
    )

    if settings:
        await setup_agent(settings)
    else:
        await setup_agent(
            {
                "model": selected_model["label"],
                "system_prompt": SYSTEM_PROMPT_CHOICES[prompt_index]["label"],
                "tools_enabled": tools_enabled,
            }
        )

@cl.on_settings_update
async def setup_agent(settings: dict):
    """設定が更新されたときに呼び出されます。"""
    model_label = settings["model"]
    selected_model = next((m for m in AVAILABLE_MODELS if m["label"] == model_label), AVAILABLE_MODELS[DEFAULT_MODEL_INDEX])
    
    cl.user_session.set("model", selected_model)

    prompt_label = settings["system_prompt"]
    selected_prompt = next((p["content"] for p in SYSTEM_PROMPT_CHOICES if p["label"] == prompt_label), SYSTEM_PROMPT_CHOICES[DEFAULT_PROMPT_INDEX]["content"])
    cl.user_session.set("system_prompt", selected_prompt)

    # Tools ON/OFF の反映（設定パネルのスイッチ）
    if "tools_enabled" in settings:
        tools_enabled = bool(settings["tools_enabled"])
        cl.user_session.set("tools_enabled", tools_enabled)
        # コマンドは固定（画像+Canvas）。設定変更時も再設定しておく。
        try:
            await cl.context.emitter.set_commands(COMMANDS_BASE)
        except Exception as e:
            print(f"Failed to update commands on settings change: {e}")

    print(f"Settings updated: Model={selected_model['label']}, Prompt={prompt_label}")

    await _persist_thread_metadata()

@cl.on_message
async def on_message(message: cl.Message):
    """ユーザーからのメッセージ受信時に呼び出されます。"""
    # まずはコマンド押下を検出して通常フローを止める
    if getattr(message, "command", None):
        cmd = message.command
        if cmd == "Picture":
            # 画像生成（今後gpt-image-1-miniモデルも利用できるようにする）
            if not openai_async_client:
                await cl.Message("エラー: OPENAI_API_KEYが設定されていないため画像生成を実行できません。", author="system").send()
                return
            try:
                response = await openai_async_client.responses.create(
                    model="gpt-4.1-mini",
                    input=message.content,
                    tools=[{"type":"image_generation"}],
                    #stream=True,
                )
                # 生成された画像（base64）を取り出す
                image_data = [
                    output.result
                    for output in response.output
                    if getattr(output, "type", None) == "image_generation_call"
                ]

                if not image_data:
                    await cl.Message("画像データを取得できませんでした。", author="system").send()
                    return

                image_bytes = base64.b64decode(image_data[0])

                # Chainlit に画像として送信
                img = cl.Image(
                    content=image_bytes,
                    mime="image/png",
                    name="cat_and_otter.png"
                )
                await cl.Message(
                    f"Here's what I generated for **{message.content}**",
                    elements=[img]
                ).send()

            except Exception as e:
                await cl.Message(
                    f"画像生成中にエラーが発生しました: {e}",
                    author="system"
                ).send()
            return
        elif cmd == "Code":
            # エディタ/プレビューを表示。入力が無ければ直近のアシスタント発話から抽出。
            user_input = (message.content or "").strip()
            initial_code = user_input or None
            notification = "Code Workbench を開きました。Editor/Preview を切り替えてご利用ください。"

            if initial_code is None:
                history = cl.user_session.get("conversation_history", [])
                for m in reversed(history):
                    if isinstance(m, AIMessage):
                        # まずHTMLとして抽出を試みる
                        html_code = extract_html_code(m.content)
                        if html_code:
                            initial_code = html_code
                            break
                        # HTMLがなければ、他の言語のコードブロックを探す
                        fenced_code = extract_fenced_code(m.content)
                        if fenced_code:
                            initial_code = fenced_code
                            notification += "\n（HTMLでないためプレビューは正しく表示されない可能性があります）"
                            break
            
            # HTMLコードの場合のみ、雛形でラップする
            if initial_code and "<html" not in initial_code.lower() and initial_code.strip().startswith("<"):
                initial_code = (
                    "<!doctype html>\n"
                    "<html lang=\"ja\">\n"
                    "  <head>\n"
                    "    <meta charset=\"utf-8\"/>\n"
                    "    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"/>\n"
                    "    <title>Preview</title>\n"
                    "  </head>\n"
                    "  <body>\n" + initial_code + "\n  </body>\n</html>"
                )
            
            await open_code_workbench(code=initial_code)
            await cl.Message(notification, author="system").send()
            return

        elif cmd == "slide":
            if not openai_async_client:
                await cl.Message("エラー: OPENAI_API_KEYが設定されていないためスライド生成を実行できません。", author="system").send()
                return

            async with cl.Step(name="スライド生成中...") as step:
                step.input = json.dumps({
                    "prompt": message.content,
                    "model": "gpt-4o",
                })
                # braces を含むテンプレ内で format() を使うと例外になるため、手動置換にする
                prompt = SLIDE_GENERATION_PROMPT_TEMPLATE.replace("{user_input}", message.content)
                
                try:
                    response = await openai_async_client.chat.completions.create(
                        model="gpt-4o",
                        messages=[
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0.7,
                        max_tokens=4000,
                    )
                    slide_json_str = response.choices[0].message.content
                    step.output = json.dumps({"raw": slide_json_str})
                    
                    extracted_json = extract_json_array(slide_json_str)
                    
                    if extracted_json:
                        try:
                            parsed = json.loads(extracted_json)
                            count = len(parsed) if isinstance(parsed, list) else 0
                        except Exception:
                            parsed, count = None, 0
                        if count > 0:
                            await open_slide_preview(slides_json=extracted_json, title=f"{message.content[:20]}... のスライド")
                            await cl.Message(f"スライドのプレビューをサイドバーに表示しました。（{count}枚）", author="system").send()
                        else:
                            # Debug previews for terminal and user
                            raw_preview = (slide_json_str or "")[:800]
                            extracted_preview = (extracted_json or "")[:800]
                            print("[SlideDebug] Empty array after extraction. Raw preview:\n", raw_preview)
                            print("[SlideDebug] Extracted preview:\n", extracted_preview)
                            await cl.Message("抽出できましたが、配列が空です。AI応答を確認します。（プレビューを端末ログに出力しました）", author="system").send()
                            await open_code_workbench(code=f"<pre>{slide_json_str}</pre>", title="Slide JSON Raw Output (empty array)")
                    else:
                        # Debug previews for terminal and user
                        raw_preview = (slide_json_str or "")[:800]
                        print("[SlideDebug] Extraction failed. Raw preview:\n", raw_preview)
                        await cl.Message("スライドのJSON配列を抽出できませんでした。AIの応答をサイドバーに表示します。（プレビューを端末ログに出力しました）", author="system").send()
                        await open_code_workbench(code=f"<pre>{slide_json_str}</pre>", title="Slide JSON Raw Output")

                except Exception as e:
                    error_msg = f"スライド生成中にエラーが発生しました: {e}"
                    await cl.Message(error_msg, author="system").send()
            return
        else:
            await cl.Message(f"未対応のコマンド: {cmd}", author="system").send()
        return
    model_info = cl.user_session.get("model")
    system_prompt = cl.user_session.get("system_prompt")
    conversation_history = cl.user_session.get("conversation_history", [])
    

    if model_info is None:
        model_info = AVAILABLE_MODELS[DEFAULT_MODEL_INDEX]
        cl.user_session.set("model", model_info)
        print(f"Model info was None, set to default: {model_info}")
    
    if system_prompt is None:
        system_prompt = SYSTEM_PROMPT_CHOICES[DEFAULT_PROMPT_INDEX]["content"]
        cl.user_session.set("system_prompt", system_prompt)
        print(f"System prompt was None, set to default")
    
    # 履歴に今回のユーザーメッセージを追加
    conversation_history.append(HumanMessage(content=message.content))
    
    # APIに渡すメッセージリストを作成
    api_messages = [msg for msg in conversation_history if not isinstance(msg, SystemMessage)]
    
    msg = cl.Message(content="")
    await msg.send()
    answer_text = ""

    try:
        # --- OpenAI Models ---
        if model_info["type"] == "openai":
            if not openai_client:
                answer_text = "エラー: OPENAI_API_KEYが設定されていません。"
                await msg.stream_token(answer_text)
                await msg.update()
                return
            
            model = model_info["value"]
            previous_response_id = cl.user_session.get("previous_response_id")

            tools = OPENAI_ALL_TOOLS if cl.user_session.get("tools_enabled", False) else []
            async with cl.Step(name="応答生成中...") as step:
                step.input = json.dumps({
                    "prompt": message.content,
                    "model": model_info["value"],
                    "provider": model_info["type"],
                })
                step.metadata = {
                    "model": model_info["value"],
                    "provider": model_info["type"],
                }
                response = openai_client.responses.create(
                    model=model,
                    input=[
                        {
                            "role": "system",
                            "content": system_prompt
                        },
                        {
                            "role": "user",
                            "content": message.content
                        }
                    ],
                    previous_response_id=previous_response_id,
                    tools=tools,
                    stream=True,
                ) 
                # ステータス表示: 応答生成開始
                try:
                    await cl.context.emitter.set_status("応答生成中...")
                    status_set_at = time.monotonic()
                except Exception:
                    pass
                for event in response:
                    etype = getattr(event, "type", None)

                    # テキストトークン（増分）
                    if etype == "response.output_text.delta":
                        token = getattr(event, "delta", "") or ""
                        if token:
                            answer_text += token
                            await msg.stream_token(token)

                    # ツール呼び出しの進捗（Responses API）
                    elif etype == "response.tool_call.delta":
                        delta = getattr(event, "delta", None)
                        tool_name = None
                        if delta is not None:
                            tool_name = (
                                getattr(delta, "name", None)
                                or getattr(delta, "tool_name", None)
                                or (getattr(getattr(delta, "function", None), "name", None))
                            )
                        try:
                            await cl.context.emitter.set_status(
                                f"ツール実行中: {tool_name}" if tool_name else "ツール実行中..."
                            )
                        except Exception:
                            pass

                    # ツール呼び出し完了（実装差異に対応）
                    elif etype in ("response.tool_call.completed", "response.tool_calls.done"):
                        try:
                            await cl.context.emitter.set_status("応答生成中...")
                        except Exception:
                            pass

                    # 出力テキスト完了（区切りイベント）
                    elif etype == "response.output_text.done":
                        # ここではクリアしない（瞬間的に消えるのを防ぐ）
                        pass

                    # 応答全体が完成
                    elif etype == "response.completed":
                        resp = getattr(event, "response", None)
                        if resp and getattr(resp, "id", None):
                            cl.user_session.set("previous_response_id", resp.id)
                        # ステータスをクリア（最小表示時間を確保）
                        try:
                            elapsed = (time.monotonic() - status_set_at) if 'status_set_at' in locals() else 0
                            if elapsed < 0.3:
                                await asyncio.sleep(0.3 - elapsed)
                            await cl.context.emitter.set_status("")
                        except Exception:
                            pass

                    # エラーイベント
                    elif etype == "response.error":
                        err = getattr(event, "error", None)
                        # ステータスをクリア（最小表示時間を確保）
                        try:
                            elapsed = (time.monotonic() - status_set_at) if 'status_set_at' in locals() else 0
                            if elapsed < 0.3:
                                await asyncio.sleep(0.3 - elapsed)
                            await cl.context.emitter.set_status("")
                        except Exception:
                            pass
                        raise RuntimeError(str(err) if err else "OpenAI streaming error")

                    # 作成開始イベントなどは無視してOK
                    else:
                        # print("DEBUG OpenAI event:", event)
                        pass

            #正常終了後、会話履歴を更新
            if answer_text:
                conversation_history.append(AIMessage(content=answer_text))
                cl.user_session.set("conversation_history", conversation_history)
                try:
                    step.output = answer_text
                    step.metadata = {
                        "model": model_info["value"],
                        "provider": model_info["type"],
                    }
                except Exception:
                    pass
            await msg.update()

        # --- Gemini Models ---
        elif model_info["type"] == "gemini":
            if not GOOGLE_API_KEY:
                answer_text = "エラー: GOOGLE_API_KEYが設定されていません。"
                await msg.stream_token(answer_text)
                await msg.update()
                return
                
            # --- ツール設定（有効時のみ） ---
            tools = (
                [
                    Tool(url_context=UrlContext()),
                    Tool(google_search=GoogleSearch()),
                    Tool(code_execution={}),
                ]
                if cl.user_session.get("tools_enabled", False)
                else []
            )

            # システムプロンプトとメッセージを結合
            messages = [f"System: {system_prompt}"] if system_prompt else []
            messages.extend([m.content for m in api_messages])
            prompt = "\n".join(messages)

            # --- API呼び出し ---
            stream = gemini_client.models.generate_content(
                model=model_info["value"],
                contents=prompt,
                config=GenerateContentConfig(
                    tools=tools,
                )
            )

            # --- レスポンスを処理（Gemini） ---
            if hasattr(stream, "candidates") and stream.candidates:
                candidate = stream.candidates[0]  # 最上位候補のみ採用
                if getattr(candidate, "content", None):
                    for part in (candidate.content.parts or []):
                        text = getattr(part, "text", None)
                        if text:
                            answer_text += text
                            await msg.stream_token(text)

            # 会話履歴を更新
            if answer_text:
                conversation_history.append(AIMessage(content=answer_text))
                cl.user_session.set("conversation_history", conversation_history)
            await msg.update()

        # --- Claude Models ---
        elif model_info["type"] == "claude":
            if not anthropic_client:
                answer_text = "エラー: ANTHROPIC_API_KEYが設定されていません。"
                await msg.stream_token(answer_text)
                await msg.update()
                return
                
            stream = await anthropic_client.messages.create(
                model=model_info["value"],
                system=system_prompt,
                messages=[{"role": "user" if isinstance(m, HumanMessage) else "assistant", "content": m.content} for m in api_messages],
                max_tokens=4096,
                stream=True,
            )
            async for chunk in stream:
                if chunk.type == "content_block_delta":
                    token = chunk.delta.text or ""
                    answer_text += token
                    await msg.stream_token(token)
            # Claude: 出力コードの自動反映
            try:
                html = extract_html_code(answer_text)
                if html:
                    await open_code_workbench(code=html, title="Canvas: Code Workbench (from LLM)")
            except Exception as e:
                print(f"extract_html_code(Claude) error: {e}")

        # --- Grok Models ---
        elif model_info["type"] == "grok":
            if not xai_client:
                answer_text = "エラー: XAI_API_KEYが設定されていません。"
                await msg.stream_token(answer_text)
                await msg.update()
                return

            system_prompt = system(system_prompt)
            prompt = user(message.content)

            # 応答生成
            chat = xai_client.chat.create(
                model=model_info["value"],
                messages=[system_prompt, prompt],
                search_parameters=SearchParameters(mode="auto"),
            )
            
            for response, chunk in chat.stream():
                answer_text += chunk.content
                await msg.stream_token(chunk.content)
                await msg.update()
                #print(chunk.content, end="", flush=True)  # Each chunk's content

            # 会話履歴を更新
            if answer_text:
                conversation_history.append(AIMessage(content=answer_text))
                cl.user_session.set("conversation_history", conversation_history)
            await msg.update()


    except Exception as e:
        error_message = f"エラーが発生しました: {str(e)}"
        print(f"詳細エラー: {e}")
        
        # 修正点② content引数を使わずに更新
        msg.content = error_message
        await msg.update()
        
        # エラー時は最後のユーザーメッセージを履歴から削除
        if conversation_history and isinstance(conversation_history[-1], HumanMessage):
            cl.user_session.set("conversation_history", conversation_history[:-1])
        msg.content = error_message
        await msg.update()

@cl.set_starters
async def set_starters():
    return [
        cl.Starter(
            label="コードをリファクタリングして",
            message="コードをリファクタリングして、解説をしてください",
            #icon="/public/idea.svg",
            ),
        cl.Starter(
            label="生成AIの最新ニュースを教えて",
            message="今日発表された情報を元に生成AIの最新ニュースを教えて",
            #icon="/public/learn.svg",
            ),
        cl.Starter(
            label="Pythonのコードを書いて",
            message="Pythonのサンプルコードを書いて、解説をしてください",
            #icon="/public/terminal.svg",
            ),
        ]
