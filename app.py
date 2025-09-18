import os
import re
import json
import asyncio
import time
import base64
import chainlit as cl
from chainlit.input_widget import Select, Switch
from typing import Optional

# --- Provider SDKs ---
from openai import OpenAI, AsyncOpenAI
from anthropic import AsyncAnthropic
#from groq import AsyncGroq
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

# クライアントはグローバルに初期化しておくと効率的
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
openai_async_client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
anthropic_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None
#grok_client = AsyncGroq(api_key=XAI_API_KEY) if XAI_API_KEY else None
gemini_client = genai.Client(api_key=GOOGLE_API_KEY) if GOOGLE_API_KEY else None

# Chainlitのトレース機能
cl.instrument_openai()

# --- モデルリストの定義 ---
AVAILABLE_MODELS = [
    { "label": "GPT-4o-mini", "value": "gpt-4o-mini", "type": "openai" },
    { "label": "GPT-4.1", "value": "gpt-4.1-2025-04-14", "type": "openai" },
    { "label": "GPT-5 Chat", "value": "gpt-5-chat-latest", "type": "openai" },
    { "label": "GPT-5 Nano", "value": "gpt-5-nano-2025-08-07", "type": "openai" },
    { "label": "GPT-5", "value": "gpt-5-2025-08-07", "type": "openai" },
    { "label": "Gemini 2.5 Flash-Lite", "value": "gemini-2.5-flash-lite", "type": "gemini" },
    { "label": "Gemini 2.5 Flash", "value": "gemini-2.5-flash", "type": "gemini" },
    { "label": "Gemini 2.5 Pro", "value": "gemini-2.5-pro", "type": "gemini" },
    { "label": "Claude Sonnet 3.7", "value": "claude-3-7-sonnet-20250219", "type": "claude" },
    { "label": "Claude Sonnet4", "value": "claude-sonnet-4-20250514", "type": "claude" },
    { "label": "Claude Opus4.1", "value": "claude-opus-4-1-202508054", "type": "claude" },
    { "label": "Grok4", "value": "grok-4-0709", "type": "grok" },
    { "label": "Grok Code Fast 1", "value": "grok-code-fast-1", "type": "grok" },
]
DEFAULT_MODEL_INDEX = 0

# --- Profile Setting ---
@cl.set_chat_profiles
def chat_profile():
    """チャット プロファイル セッター（プロフィール=システムプロンプト）。"""
    return [
        cl.ChatProfile(
            name=p["label"],
            markdown_description=p["content"],
        )
        for p in SYSTEM_PROMPT_CHOICES
    ]

# --- システムプロンプトの定義 ---
current_time = now.strftime("%Y-%m-%d %H:%M")
SYSTEM_PROMPT_CHOICES = [
    { "label": "標準アシスタント", "content": "Current time: {current_time}\nYou are a helpful assistant." },
    { "label": "丁寧な説明", "content": "Current time: {current_time}\nUse a formal tone, providing clear, well-structured sentences and precise language." },
    { "label": "簡潔な回答", "content": "Current time: {current_time}\nRespond briefly and directly, using as few words as possible." },
    { "label": "ソクラテス式", "content": "Current time: {current_time}\nRespond as a Socratic teacher, guiding the user through questions and reasoning to foster deep understanding." },
]
DEFAULT_PROMPT_INDEX = 0

# --- Command Setting ---
COMMANDS_BASE = [
    { "id": "NanoBanana",   "label": "Nano Banana",   "icon": "image",  "description": "Generate a Nano Banana image with Gemini" },
    { "id": "Picture",   "label": "Picture",   "icon": "image",  "description": "Use DALL·E to generate an image" },
    # Canvas command (single, smart)
    { "id": "Map", "label": "Map", "icon": "map", "description": "Open/Move map by place name or lat,lng" },
    # Coding Workbench
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

# --- Canvas helpers (Map) ---
async def open_map(latitude: float = 35.681236, longitude: float = 139.767125, zoom: int = 12, q: Optional[str] = None):
    """CanvasへMapカスタム要素を表示する。qがあれば優先して検索表示。"""
    map_props = {"latitude": latitude, "longitude": longitude, "zoom": zoom}
    if q:
        map_props["q"] = q
    custom_element = cl.CustomElement(name="Map", props=map_props, display="inline")
    await cl.ElementSidebar.set_title("canvas")
    # バージョンをインクリメントしてキーを変え、確実に再マウント
    version = cl.user_session.get("map_version", 0) + 1
    cl.user_session.set("map_version", version)
    key = f"map-canvas-{version}"
    await cl.ElementSidebar.set_elements([custom_element], key=key)

async def open_code_workbench(code: Optional[str] = None, title: str = "Code Workbench"):
    """サイドバーにエディタとプレビューを持つCode Workbenchを表示。"""
    print(f"DEBUG: open_code_workbench called with code length = {len(code) if code else 0}")
    print(f"DEBUG: title = '{title}'")
    if code:
        print(f"DEBUG: code preview = {code[:200]}...")
    
    version = cl.user_session.get("workbench_version", 0) + 1
    cl.user_session.set("workbench_version", version)
    props = {"code": code, "title": title, "key": f"workbench-{version}"}
    print(f"DEBUG: props = {props}")
    print(f"DEBUG: props['code'] length = {len(props['code']) if props['code'] else 0}")
    
    element = cl.CustomElement(name="CodeWorkbench", props=props, display="inline")
    print(f"DEBUG: CustomElement created with name=CodeWorkbench")
    
    await cl.ElementSidebar.set_title("Code Workbench")
    await cl.ElementSidebar.set_elements([element])
    print("DEBUG: ElementSidebar.set_elements completed")

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

@cl.step(type="tool")
async def move_map_to(latitude: float, longitude: float, q: Optional[str] = None):
    """地図を移動/検索する。qがあれば検索、なければ座標中心。"""
    await open_map(latitude, longitude, q=q)
    args = {"latitude": latitude, "longitude": longitude}
    if q:
        args["q"] = q
    fn = cl.CopilotFunction(name="move-map", args=args)
    await fn.acall()
    return "Map moved!"

# --- Geocoding helpers ---
COORD_REGEX = re.compile(r"lat\s*[:=]?\s*([+-]?\d+\.\d+)\s*[,\s]\s*lng\s*[:=]?\s*([+-]?\d+\.\d+)", re.I)
PAIR_REGEX = re.compile(r"([+-]?\d+\.\d+)\s*[,\s]\s*([+-]?\d+\.\d+)")

def parse_coords_freeform(text: str):
    """自由入力から座標らしき2つのfloatを抽出。成功で (lat, lng)。"""
    if not text:
        return None
    t = text.replace("、", ",")  # 全角カンマ対応
    m = COORD_REGEX.search(t)
    if m:
        try:
            return (float(m.group(1)), float(m.group(2)))
        except Exception:
            pass
    m2 = PAIR_REGEX.search(t)
    if m2:
        try:
            return (float(m2.group(1)), float(m2.group(2)))
        except Exception:
            pass
    return None

async def geocode_with_llm(query: str):
    """LLMを使って場所名から座標を推定する。成功で (lat, lng) を返す。失敗時は None。
    1) まず自由入力から数値座標を直接抽出
    2) OpenAI Responses API（あれば）で JSON {lat,lng}
    3) Gemini（あれば）で JSON {lat,lng}
    """
    if not query:
        return None

    # 1) 文字列から直接抽出
    coords = parse_coords_freeform(query)
    if coords:
        return coords

    # 2) OpenAI
    if openai_client:
        try:
            system = (
                "You output only a JSON object with keys 'lat' and 'lng' (floats). "
                "No prose, no explanations. Example: {\"lat\": 35.681236, \"lng\": 139.767125}."
            )
            resp = openai_client.responses.create(
                model="gpt-4o-mini",
                input=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"Return coordinates for: {query}"},
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )
            # 最優先で output_text を使い、無ければ全体文字列から抽出
            text = getattr(resp, "output_text", None)
            if not text:
                raw = str(resp)
                m = re.search(r"\{\s*\"lat\"\s*:.*?\}\s*", raw, re.S)
                text = m.group(0) if m else None
            data = json.loads(text) if text else None
            if isinstance(data, dict) and "lat" in data and "lng" in data:
                return (float(data["lat"]), float(data["lng"]))
        except Exception as e:
            print(f"geocode_with_llm(OpenAI) error: {e}")

    # 3) Gemini
    if gemini_client:
        try:
            prompt = (
                "Return only a JSON object with keys 'lat' and 'lng' (floats). "
                "No text. Example: {\"lat\": 35.681236, \"lng\": 139.767125}.\n"
                f"Place: {query}"
            )
            stream = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )
            # Geminiの簡易取り出し
            text = None
            if hasattr(stream, "candidates") and stream.candidates:
                cand = stream.candidates[0]
                if getattr(cand, "content", None):
                    for part in (cand.content.parts or []):
                        if getattr(part, "text", None):
                            text = part.text
                            break
            if text:
                data = json.loads(text)
                if isinstance(data, dict) and "lat" in data and "lng" in data:
                    return (float(data["lat"]), float(data["lng"]))
        except Exception as e:
            print(f"geocode_with_llm(Gemini) error: {e}")

    return None

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
    initial_prompt_index = DEFAULT_PROMPT_INDEX
    if isinstance(profile_name, str):
        for i, p in enumerate(SYSTEM_PROMPT_CHOICES):
            if p["label"] == profile_name:
                initial_prompt_index = i
                break

    # 設定UI（モデルは設定パネルで切替。プロフィールはプロンプトのみ反映）
    settings = await cl.ChatSettings([
        Select(id="model", label="モデル", values=[m["label"] for m in AVAILABLE_MODELS], initial_index=DEFAULT_MODEL_INDEX),
        Select(id="system_prompt", label="システムプロンプト（AIの性格・役割）", values=[p["label"] for p in SYSTEM_PROMPT_CHOICES], initial_index=initial_prompt_index),
        Switch(id="tools_enabled", label="Tools（Web検索/実行/MCP）", initial=tools_enabled),
    ]).send()
    
    # 初期設定を設定（UIの初期値に合わせる）
    initial_model = AVAILABLE_MODELS[DEFAULT_MODEL_INDEX]
    initial_prompt = SYSTEM_PROMPT_CHOICES[initial_prompt_index]["content"]
    
    cl.user_session.set("model", initial_model)
    cl.user_session.set("system_prompt", initial_prompt)
    cl.user_session.set("conversation_history", [])
    
    print(f"Initial setup: Model={initial_model['label']}, Prompt={SYSTEM_PROMPT_CHOICES[DEFAULT_PROMPT_INDEX]['label']}")
    
    # 修正点① await を追加
    await setup_agent(settings)

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

@cl.on_message
async def on_message(message: cl.Message):
    """ユーザーからのメッセージ受信時に呼び出されます。"""
    # まずはコマンド押下を検出して通常フローを止める
    if getattr(message, "command", None):
        cmd = message.command
        if cmd == "NanoBanana":
            # Gemini を使った Nano Banana 画像生成
            if not gemini_client:
                await cl.Message("エラー: GOOGLE_API_KEYが設定されていないため画像生成を実行できません。", author="system").send()
                return
            prompt = message.content.strip() if (message.content and message.content.strip()) else (
                "Create a picture of a nano banana dish in a fancy restaurant with a Gemini theme"
            )
            async with cl.Step(name="Nano Banana 画像生成中...") as step:
                step.input = prompt
                msg = cl.Message(content="画像を生成中です…")
                await msg.send()
                status_set_at = None
                try:
                    try:
                        await cl.context.emitter.set_status("画像生成中...")
                        status_set_at = time.monotonic()
                    except Exception:
                        pass

                    def _run_gen():
                        return gemini_client.models.generate_content(
                            model="gemini-2.5-flash-image-preview",
                            contents=[prompt],
                        )

                    response = await asyncio.to_thread(_run_gen)

                    image_bytes = None
                    image_mime = "image/png"
                    alt_texts = []
                    try:
                        cand = response.candidates[0]
                        if getattr(cand, "content", None):
                            for part in (cand.content.parts or []):
                                if getattr(part, "text", None):
                                    alt_texts.append(part.text)
                                elif getattr(part, "inline_data", None):
                                    data = getattr(part.inline_data, "data", None)
                                    if data:
                                        mt = getattr(part.inline_data, "mime_type", None)
                                        if mt:
                                            image_mime = mt
                                        # Google returns base64-encoded string sometimes
                                        if isinstance(data, str):
                                            try:
                                                image_bytes = base64.b64decode(data)
                                            except Exception:
                                                image_bytes = None
                                        else:
                                            image_bytes = data
                                        break
                    except Exception:
                        pass

                    if not image_bytes:
                        # 念のため別経路（parts直列）
                        try:
                            for cand in (response.candidates or []):
                                if getattr(cand, "content", None):
                                    for part in (cand.content.parts or []):
                                        if getattr(part, "inline_data", None):
                                            data = getattr(part.inline_data, "data", None)
                                            if data:
                                                mt = getattr(part.inline_data, "mime_type", None)
                                                if mt:
                                                    image_mime = mt
                                                if isinstance(data, str):
                                                    try:
                                                        image_bytes = base64.b64decode(data)
                                                    except Exception:
                                                        image_bytes = None
                                                else:
                                                    image_bytes = data
                                                break
                                    if image_bytes:
                                        break
                        except Exception:
                            pass

                    if image_bytes:
                        # Choose extension from mime
                        ext = "png" if image_mime.endswith("png") else ("jpg" if image_mime.endswith("jpeg") or image_mime.endswith("jpg") else "img")
                        img = cl.Image(content=image_bytes, name=f"nano_banana.{ext}", mime=image_mime)
                        await cl.Message(content="Nano Banana 画像を生成しました。", elements=[img]).send()
                        step.output = "Image generated"
                    else:
                        # テキストのみ返ってきた場合
                        description = ("\n\n".join(alt_texts)).strip() if alt_texts else "画像データを取得できませんでした。"
                        await cl.Message(description or "画像データを取得できませんでした。", author="system").send()
                        step.output = description
                except Exception as e:
                    await cl.Message(f"エラーが発生しました: {e}", author="system").send()
                finally:
                    try:
                        elapsed = (time.monotonic() - status_set_at) if status_set_at is not None else 0
                        if elapsed < 0.3:
                            await asyncio.sleep(max(0.0, 0.3 - elapsed))
                        await cl.context.emitter.set_status("")
                    except Exception:
                        pass
            return
        if cmd == "Picture":
            # 画像生成（DALL·E 3）
            if not openai_async_client:
                await cl.Message("エラー: OPENAI_API_KEYが設定されていないため画像生成を実行できません。", author="system").send()
                return
            try:
                response = await openai_async_client.images.generate(
                    model="dall-e-3",
                    prompt=message.content or "A scenic landscape in watercolor style",
                    size="1024x1024",
                )
                # ログ
                print(f"Image generated. Response: {response}")
                # 最初の画像URLを取得
                image_url = response.data[0].url if response and getattr(response, 'data', None) else None
                if not image_url:
                    await cl.Message("画像のURLを取得できませんでした。", author="system").send()
                    return
                elements = [cl.Image(url=image_url)]
                await cl.Message(f"Here's what I generated for **{message.content or '(no prompt)'}**", elements=elements).send()
            except Exception as e:
                await cl.Message(f"画像生成中にエラーが発生しました: {e}", author="system").send()
            return
        elif cmd == "Map":
            # シンプル: 入力が座標ならそのまま、地名なら q として渡す
            DEFAULT_LAT, DEFAULT_LNG = 35.681236, 139.767125
            content = (message.content or "").strip()
            if not content:
                # デフォルトは東京駅（q指定で検索）
                await move_map_to(DEFAULT_LAT, DEFAULT_LNG, q="東京駅")
                await cl.Message("Map: 東京駅を表示しました").send()
                return
            coords = parse_coords_freeform(content)
            if coords:
                lat, lng = coords
                await move_map_to(lat, lng)
                await cl.Message(f"Map: lat={lat}, lng={lng}").send()
            else:
                await move_map_to(DEFAULT_LAT, DEFAULT_LNG, q=content)
                await cl.Message(f"Map: 検索 '{content}'").send()
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
                step.input = message.content
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
                    step.output = slide_json_str
                    
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
    
    # 修正点③ None防御
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
                step.input = message.content
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

                # Step の出力を設定（最終テキスト）
                try:
                    step.output = answer_text
                except Exception:
                    pass
        
            #正常終了後、会話履歴を更新
            if answer_text:
                conversation_history.append(AIMessage(content=answer_text))
                cl.user_session.set("conversation_history", conversation_history)
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
