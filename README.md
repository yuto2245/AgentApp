# AgentApp – Multi-Model Conversational Platform

AgentApp は、Chainlit をベースに複数の LLM（OpenAI / Google Gemini / Anthropic / xAI）と対話できる本番運用向けチャットアプリケーションです。同時に、開発者としてのポートフォリオを兼ねたプロジェクトであり、以下のドキュメントは採用担当者にも理解しやすいよう、実装背景と運用フローをまとめています。

![AgentApp UI](public/img/AgentApp_img.png)

---

## 特徴

- **マルチモデル対応**: モデル切り替え、システムプロンプト選択、会話履歴の永続化をサポート。
- **独自認証**: `AppUser` テーブルと Bcrypt によるパスワード管理。Chainlit 標準ユーザーとも連携。
- **メール認証対応**: 環境変数 `EMAIL_VERIFICATION_REQUIRED` のトグルで、本番と開発のフローを切り替え可能。
- **アーキテクチャ可視化**: C4 図 / ERD / シーケンス図 / CI パイプライン図を整備し、理解・説明が容易。
- **Heroku 運用想定**: Config Vars / SendGrid（または任意 SMTP）で本番運用を想定した構成。

---

## アーキテクチャ概要

### システム全体像
![コンテキスト図](public/img/context-diagram.svg)

### コンテナ構成（C4-L2）
![コンテナ図](public/img/container-diagram.svg)

### コンポーネント構成（C4-L3）
![コンポーネント図](public/img/component-diagram.svg)

### データモデル
![ERD](public/img/erd.svg)

### 認証フロー（登録 → ログイン → 履歴保存）
![シーケンス図](public/img/sequence-flow.svg)

### デプロイメント
![デプロイ図](public/img/deployment-diagram.svg)

### CI/CD 概要
![CI/CD パイプライン](public/img/cicd-pipeline.svg)

---

## 技術スタック

| 分類 | 採用技術 |
|------|----------|
| フレームワーク | Chainlit, FastAPI |
| データベース | PostgreSQL (Heroku Postgres) |
| ORM / Driver | asyncpg |
| 認証 | Bcrypt + 独自テーブル + Chainlit user sync |
| メール | `smtplib` 経由で SMTP（SendGrid など） |
| インフラ | Heroku (Dyno + Postgres + Config Vars) |
| 言語 | Python 3.10+ |

---

## セットアップ手順

### 1. 前提
- Python 3.10〜3.12 推奨
- `pip` または `uv` / `poetry` 等が利用可能
- PostgreSQL（ローカル or Heroku）と SMTP サーバー（Mailtrap / SendGrid 等）を準備

### 2. リポジトリを取得
```bash
git clone <REPO_URL>
cd AgentApp
```

### 3. 依存関係インストール
```bash
pip install -r requirements.txt
```

### 4. 環境変数を設定
`.env` を作成し、最低限以下を記述します。

```env
OPENAI_API_KEY=your_openai_api_key
GOOGLE_API_KEY=your_google_api_key
ANTHROPIC_API_KEY=your_anthropic_api_key
XAI_API_KEY=your_xai_api_key

# Database
DATABASE_URL=postgresql://user:password@host:5432/dbname

# SMTP（例：テスト用途で Mailtrap を使用）
SMTP_HOST=sandbox.smtp.mailtrap.io
SMTP_PORT=587
SMTP_USER=your_mailtrap_user
SMTP_PASSWORD=your_mailtrap_password
FROM_EMAIL=noreply@example.com

# 公開 URL（ローカル検証時は http://127.0.0.1:8000 等）
APP_BASE_URL=http://127.0.0.1:8000

# メール認証フラグ
EMAIL_VERIFICATION_REQUIRED=false
```

> **Tips**  
> - `EMAIL_VERIFICATION_REQUIRED=true` にすると、登録時にメールトークンを発行し `/verify` が完了するまでログインできなくなります。  
> - フラグを `false` にすれば、メール送信なしで `status=active` として登録直後からログイン可能です（ローカル検証向け）。

### 5. DB スキーマの初期化
Heroku Postgres 等に接続し、`schema_chainlit.sql` を実行して Chainlit / AppUser 用のテーブルを作成します。

### 6. アプリ起動
```bash
chainlit run app.py -w
```
ブラウザで `http://127.0.0.1:8000` を開くとログインページが表示されます。

---

## 本番デプロイ（Heroku 例）

1. Heroku アプリ・Postgres アドオンを作成。
2. `heroku config:set` で `.env` 相当の環境変数を登録。
   ```bash
   heroku config:set \
     OPENAI_API_KEY=... \
     GOOGLE_API_KEY=... \
     DATABASE_URL=... \
     SMTP_HOST=smtp.sendgrid.net \
     SMTP_PORT=587 \
     SMTP_USER=apikey \
     SMTP_PASSWORD=<SENDGRID_API_KEY> \
     FROM_EMAIL=verified@example.com \
     APP_BASE_URL=https://your-app.herokuapp.com \
     EMAIL_VERIFICATION_REQUIRED=true
   ```
3. `schema_chainlit.sql` を `heroku pg:psql` で適用。
4. `git push heroku main` でデプロイ。  
5. `/api/register` でユーザー登録 → メールリンク確認 → ログイン → 会話を開始。

---

## 認証フローについて

- `AppUser` テーブルにメール・ハッシュ化パスワード・ロール・ステータス等を保存。
- ログイン成功時に Chainlit 側 `User` テーブルへ同期し、会話履歴との紐づけを維持。
- `EMAIL_VERIFICATION_REQUIRED=true` では、`create_app_user` がトークンを発行しメール送信。`/verify?token=...` を踏むと `status` が `active` に更新されるまでログイン不可。
- `EMAIL_VERIFICATION_REQUIRED=false` ではトークン発行をスキップし、すぐに `status=active` 化してメール送信もしません。

> **補足**: 既存ユーザーを一括で有効化する場合は、SQL で `UPDATE "AppUser" SET status='active', email_token=NULL, token_expiry=NULL;` のように調整してください。

---

## モデル／プロンプトの拡張

- モデル追加: `app.py` の `AVAILABLE_MODELS` に `{label, value, type}` を追記。`type` に応じた分岐実装が必要です。
- システムプロンプト追加: `SYSTEM_PROMPT_CHOICES` に `{label, content}` を追加。Chainlit UI のチャット設定から選択可能。

---

## 運用上のメモ

- **ロギング**: メール送信エラーは標準出力に記録されます。Heroku の `heroku logs --tail` などで監視してください。
- **テスト**: 現状自動テストは未整備です。今後 pytest によるユニット／統合テスト追加を予定。
- **監視**: SendGrid などを利用する場合は配信失敗通知やバウンス管理の設定を推奨。
- **管理 UI**: `public/users.html` でユーザー数や DAU/WAU/MAU を確認できます。

---

## ポートフォリオとしての見どころ

- エンタープライズを意識した Chainlit 拡張（独自データレイヤー、メール認証、会話永続化）。
- C4 モデル／ERD／CI/CD 図を用いた設計ドキュメント化。
- Heroku 本番運用を想定した Config Vars / SendGrid 連携 / Deploy フローの整理。
- マルチプロバイダ対応（OpenAI, Gemini, Anthropic, xAI）と切り替え UI。

就職・転職活動では、本プロジェクトを通じて以下をアピールできます。

- Python / FastAPI / Chainlit を用いたフルスタック構築力(Codexを使用)
- 認証・データ永続化・クラウド運用までを統合した設計力(Codexを使用)
- ドキュメント整備・図解によるコミュニケーションスキル(Codexを使用)

---

## ライセンス

MIT License
