# geminiのモデル名を取得する
import os
from google import genai
from dotenv import load_dotenv
load_dotenv() 

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise SystemExit("GEMINI_API_KEY が未設定です")

client = genai.Client(api_key=GEMINI_API_KEY)

print("geminiのモデル名を取得する")
print(client.models.list())

print("List of models that support generateContent:\n")
for m in client.models.list():
    for action in m.supported_actions:
        if action == "generateContent":
            print(m.name)

print("List of models that support embedContent:\n")
for m in client.models.list():
    for action in m.supported_actions:
        if action == "embedContent":
            print(m.name)

#  modelのリスト構造