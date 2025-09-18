import os

from xai_sdk import Client
from xai_sdk.chat import user, system
from xai_sdk.search import SearchParameters
from dotenv import load_dotenv

load_dotenv()

client = Client(
    api_key=os.getenv('XAI_API_KEY'),
    timeout=3600,  # Override default timeout with longer timeout for reasoning models
)

system_prompt = system("You are Grok, a super intelligent chatbot using Japanese.")
prompt = user("Grok codeの最新情報を調べてください。")

chat = client.chat.create(
    model="grok-3-mini",
    messages=[system_prompt, prompt],
    search_parameters=SearchParameters(mode="auto"),
)

for response, chunk in chat.stream():
    print(chunk.content, end="", flush=True)  # Each chunk's content




"""
import os
from datetime import datetime


from xai_sdk import Client
from xai_sdk.chat import user, system
from xai_sdk.search import SearchParameters, SearchSource
from dotenv import load_dotenv


load_dotenv()


client = Client(
    api_key=os.getenv('XAI_API_KEY'),
    timeout=3600,  # Override default timeout with longer timeout for reasoning models
)


system_prompt = system("You are Grok, a super intelligent chatbot using Japanese.")
prompt = user("Grok codeの最新情報を調べてください。")


# ライブ検索のパラメータを設定
search_params = SearchParameters(
    mode="auto",  # ライブ検索を有効化
    return_citations=True,  # 引用を返すように設定
    max_search_results=5,  # 最大検索結果数を5に制限
    from_date=datetime(2024, 1, 1),  # 2024年1月1日以降のデータを検索対象とする
    to_date=datetime.now(),  # 現在までのデータを検索対象とする
    sources=[
        SearchSource.WEB,  # ウェブ検索を有効化
        SearchSource.X,    # 旧Twitterの検索を有効化
        SearchSource.NEWS  # ニュース検索を有効化
    ],
    # ウェブ検索とニュース検索の特定のパラメータ
    web_search_params={
        "country": "jp",  # 日本国内のウェブサイトに限定
        "safe_search": True, # セーフサーチを有効化 (デフォルトでも有効)
        "excluded_websites": ["example.com"] # 特定のウェブサイトを除外
    },
    # X (旧Twitter) 検索の特定のパラメータ
    x_search_params={
        "included_x_handles": ["xai"], # 特定のXアカウントからの投稿のみ含める
        "post_view_count": 1000 # 1000回以上の閲覧数がある投稿に限定
    }
    # RSSフィードは "rss_search_params={"links": ["http://example.com/rss.xml"]}" のように指定できます
)


chat = client.chat.create(
    model="grok-3-mini",
    messages=[system_prompt, prompt],
    search_parameters=search_params, # ここで設定したsearch_paramsを渡す
)


for response, chunk in chat.stream():
    print(chunk.content, end="", flush=True)  # Each chunk's content

"""
