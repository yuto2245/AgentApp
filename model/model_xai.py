# pip install httpx python-dotenv
import os, httpx
from dotenv import load_dotenv
load_dotenv()

XAI_API_KEY = os.getenv("XAI_API_KEY")
headers = {"Authorization": f"Bearer {XAI_API_KEY}"}

# 1) /v1/models（最小情報）
r = httpx.get("https://api.x.ai/v1/models", headers=headers, timeout=30)
r.raise_for_status()
data = r.json()
model_ids = [m.get("id") for m in data.get("data", []) if isinstance(m, dict)]
print("== /v1/models ==")
print("\n".join(model_ids))

# 2) /v1/language-models（完全情報）
r2 = httpx.get("https://api.x.ai/v1/language-models", headers=headers, timeout=30)
r2.raise_for_status()
full = r2.json().get("models", [])
print("\n== /v1/language-models ==")
for m in full:
    print(m["id"], m.get("input_modalities"), m.get("output_modalities"), m.get("aliases"))