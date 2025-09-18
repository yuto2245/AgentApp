from google import genai
from google.genai.types import Tool, GenerateContentConfig, GoogleSearch, UrlContext

client = genai.Client(
    api_key="AIzaSyBPtwUvl6H1GZ_ka2Fy7Czhk86Uq-CegT8"
)
model_id = "gemini-2.5-flash"

tools = [
      {"url_context": {}},
      {"google_search": {}},
      {"code_execution": {}},
  ]

response = client.models.generate_content(
    model=model_id,
    contents="Give me latest information about llm api use what gemini's function about multiple tool function in japanese.",
    config=GenerateContentConfig(
        tools=tools,
    )
)

for each in response.candidates[0].content.parts:
    print(each.text)
# get URLs retrieved for context
print(response.candidates[0].url_context_metadata)
