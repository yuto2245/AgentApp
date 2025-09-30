# pip install httpx python-dotenv
import os, httpx
from dotenv import load_dotenv
load_dotenv()  # .env に OPENAI_API_KEY=... を書いておく

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise SystemExit("OPENAI_API_KEY が未設定です")

headers = {"Authorization": f"Bearer {api_key}"}
r = httpx.get("https://api.openai.com/v1/models", headers=headers, timeout=30)
r.raise_for_status()
data = r.json()

# OpenAI系は data 配列にモデルが入る
models = [m.get("id") for m in data.get("data", []) if isinstance(m, dict)]
print("modelリスト")
print(data)
print("\n".join(models))


#  modelのリスト構造
#  {'id': 'gpt-4-0613', 'object': 'model', 'created': 1686588896, 'owned_by': 'openai'}