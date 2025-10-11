# AI Chat Application

複数のAIモデル（OpenAI, Gemini, Claude, Grok）と対話できるチャットアプリケーションです。
![AgentApp](public/img/AgentApp_img.png)

## 特徴

- 複数のAIモデルを切り替えて利用可能
- 対話履歴の管理
- カスタマイズ可能なシステムプロンプト

## セットアップ

1. 前提
   - Python 3.10〜3.12 を推奨
   - pip が利用可能であること

2. リポジトリをクローン
   ```bash
   git clone [リポジトリのURL]
   cd [リポジトリ名]
   ```

3. 依存関係のインストール
   ```bash
   pip install -r requirements.txt
   ```

4. 環境変数の設定（`.env` を作成）
   ```bash
   OPENAI_API_KEY=your_openai_api_key
   GOOGLE_API_KEY=your_google_api_key
   ANTHROPIC_API_KEY=your_anthropic_api_key
   XAI_API_KEY=your_xai_api_key
   # Chainlitのログインに利用する資格情報
   CHAINLIT_USERNAME=your_login_id
   CHAINLIT_PASSWORD=your_login_password
   # JWTベースの認証セッションを有効化する場合はシークレットも設定
   CHAINLIT_AUTH_SECRET=secret_generated_by_chainlit_cli
   ```

## 起動方法
```bash
chainlit run app.py -w
```

アプリケーションは http://localhost:8000 で起動します。

起動後に表示されるログインフォームには、`.env` に設定した `CHAINLIT_USERNAME` と `CHAINLIT_PASSWORD` を入力してください。`CHAINLIT_AUTH_SECRET` は `chainlit create-secret` コマンドで生成した値を利用します。

ログインに失敗する場合は、次のコマンドで現在の設定で認証が通るか事前に確認できます。

```bash
python scripts/verify_chainlit_auth.py
```

`.env` を使わずに任意の資格情報を直接チェックしたいときは、ログイン時に入力する値（`--username` / `--password`）と、Chainlit に設定したい想定の値（`--expected-username` / `--expected-password`）を引数で渡してください。

```bash
python scripts/verify_chainlit_auth.py \
  --username you@example.com --password your-password \
  --expected-username you@example.com --expected-password your-password
```

### 認証に関する補足

1. `CHAINLIT_AUTH_SECRET` をまだ用意していない場合は、以下のコマンドで生成します。
   ```bash
   chainlit create-secret
   ```
   表示された値を `.env` の `CHAINLIT_AUTH_SECRET` に貼り付けてください。
2. ログイン画面では `.env` で指定した `CHAINLIT_USERNAME` / `CHAINLIT_PASSWORD` を入力します。ユーザー登録画面は提供していないため、環境変数で設定した資格情報をそのまま使用してください。

## 使用方法
1. ブラウザで http://localhost:8000 を開く
2. 使用するAIモデルを選択
3. チャットを開始

## モデルの追加方法
`app.py` の `AVAILABLE_MODELS` 配列に追記します。`label` はUI表示名、`value` はAPIのモデル名、`type` は実装済みの分岐に合わせます（`openai` / `gemini` / `claude` / `grok`）。

```python
# app.py
AVAILABLE_MODELS = [
    # 既存...
    { "label": "GPT-4o", "value": "gpt-4o", "type": "openai" },
]
```

必要に応じて以下も確認してください。
- __APIキー__: `.env` に必要なキーを追加
- __依存パッケージ__: `requirements.txt` にSDKを追加
- __分岐実装__: `@cl.on_message` 内で `type` に対応する分岐（例: `elif model_info["type"] == "openai":`）が存在するか確認。未実装の `type` を追加した場合は、同様のストリーミング処理を実装してください。

## システムプロンプトの追加方法
`app.py` の `SYSTEM_PROMPT_CHOICES` に要素を追加します。`label` がUIに表示され、`content` が実際のシステムメッセージになります。

```python
# app.py
SYSTEM_PROMPT_CHOICES = [
    # 既存...
    { "label": "やさしい説明", "content": f"Current time: {current_time}\n丁寧で親切に説明してください。" },
]
```

起動後は設定パネル（歯車アイコン）から新しいプロンプトを選択できます。

## ライセンス
MIT License