# 🔮 Sphene Discord Bot

Spheneは、OpenAI APIを活用した会話機能を持つ、シンプルでパワフルなDiscord botです。メンション、名前呼び、リプライのいずれかで反応し、自然な会話体験を提供します。

## ✨ 主な機能

- 💬 OpenAIのGPT-4o-miniを使用した高度な会話機能
- 👋 メンション、名前呼び、リプライによる柔軟な反応
- 🔄 会話履歴リセットコマンド
- 📋 利用可能チャンネル一覧表示
- ⏱️ 30分の会話タイムアウトによるコンテキストリセット
- 🛡️ 特定チャンネルのみでの応答制限機能

## 🚀 セットアップ方法

### 環境変数の設定

`.env`ファイルを`.env.sample`をもとに作成し、必要な情報を入力します：

```
OPENAI_API_KEY=your_openai_api_key
DISCORD_TOKEN=your_discord_bot_token
BOT_NAME=スフェーン  # ボットの呼び名（デフォルト: スフェーン）
COMMAND_GROUP_NAME=sphene  # コマンドグループ名（デフォルト: sphene）

# 許可するチャンネルIDをカンマ区切りで指定（空の場合は全チャンネルで応答）
ALLOWED_CHANNEL_IDS=
```

### 必要なパッケージのインストール

```bash
pip install -r requirements.txt
```

### ローカルでの実行方法

```bash
python app.py
```

### Dockerでの実行方法

```bash
# イメージのビルド
docker build -t sphene-discord-bot .

# コンテナの実行
docker run --env-file .env sphene-discord-bot
```

## ☸️ Kubernetesへのデプロイ

環境変数をKubernetes Secretとして作成し、Podから参照できるようにします：

```bash
# 環境変数を含むSecretの作成
kubectl create secret generic sphene-envs --from-env-file ./.env

# GitHub Container Registry認証用Secretの作成
kubectl create secret docker-registry regcred --docker-server=ghcr.io --docker-username=<GitHubユーザー名> --docker-password=<GitHubトークン>
```

デプロイメントやサービスの設定は別途YAMLファイルで定義します。

## 📝 使用方法

### ボットとの会話

以下のいずれかの方法でボットと会話できます：

1. **メンション**: `@スフェーン こんにちは！`
2. **名前呼び**: `スフェーン、元気？`
3. **リプライ**: ボットのメッセージに返信する

### スラッシュコマンド

- `/sphene reset` - 会話履歴をリセットします
- `/sphene channels` - ボットが使用可能なチャンネル一覧を表示します（管理者のみ）

## 🛠️ プロジェクト構成

```
/
├── app.py                # メインアプリケーション
├── config.py             # 設定ファイル
├── Dockerfile            # Dockerビルド設定
├── requirements.txt      # 依存パッケージリスト
├── .env.sample           # 環境変数サンプル
├── README.md             # このファイル
├── ai/                   # AI関連機能
│   ├── __init__.py
│   ├── client.py         # OpenAI API クライアント
│   └── conversation.py   # 会話管理ロジック
├── bot/                  # Discordボット機能
│   ├── __init__.py
│   ├── commands.py       # スラッシュコマンド定義
│   ├── discord_bot.py    # ボットコア実装
│   └── events.py         # イベントハンドラ
├── log_utils/            # ロギング機能
│   ├── __init__.py
│   └── logger.py         # ロガー設定
├── prompts/              # プロンプト関連ファイル
│   └── system.txt        # システムプロンプト
└── utils/                # ユーティリティ機能
    ├── __init__.py
    └── text_utils.py     # テキスト処理ユーティリティ
```

## 📊 技術仕様

- Python 3.8+
- discord.py - Discordボットフレームワーク
- OpenAI API - GPT-4o-mini会話モデル
- Docker - コンテナ化
- Kubernetes - オプショナルデプロイ環境

## 🔒 セキュリティ情報

- APIキーなどの秘密情報は`.env`ファイルまたはKubernetes Secretに保存してください
- チャンネル制限を設定することで、特定のチャンネルでのみボットを使用できます

---

開発者向けメモ: システムプロンプトのカスタマイズやボットの挙動変更が必要な場合は、`prompts/system.txt`を編集してください。
