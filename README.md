# 🔮 Sphene Discord Bot

Spheneは、OpenAI APIを活用した会話機能を持つ、シンプルでパワフルなDiscord botです。メンション、名前呼び、リプライのいずれかで反応し、自然な会話体験を提供します。

## ✨ 主な機能

- 💬 OpenAIのGPT-4o-miniを使用した高度な会話機能
- 👋 メンション、名前呼び、リプライによる柔軟な反応
- 🔄 会話履歴リセットコマンド
- 📋 禁止チャンネル一覧表示
- ⏱️ 30分の会話タイムアウトによるコンテキストリセット
- 🛡️ チャンネルごとの応答制限機能（全体モード/限定モード）
- 🎭 カスタマイズ可能なシステムプロンプトでボットのキャラクター設定が自由に変更可能

## 🚀 セットアップ方法

### 環境変数の設定

`.env`ファイルを`.env.sample`をもとに作成し、必要な情報を入力します：

```
OPENAI_API_KEY=your_openai_api_key
DISCORD_TOKEN=your_discord_bot_token
BOT_NAME=スフェーン  # ボットの呼び名（デフォルト: スフェーン）
COMMAND_GROUP_NAME=sphene  # コマンドグループ名（デフォルト: sphene）
OPENAI_MODEL=gpt-4o-mini  # 使用するOpenAIのモデル

# システムプロンプトの設定
SYSTEM_PROMPT_FILENAME=system.txt
# プロンプトのストレージタイプ: local または s3
PROMPT_STORAGE_TYPE=local
# S3バケット名（PROMPT_STORAGE_TYPE=s3 の場合に使用）
S3_BUCKET_NAME=your-bucket-name
# S3フォルダパス（オプション、指定しない場合はバケットのルートに配置）
S3_FOLDER_PATH=prompts

# チャンネル設定の保存先: local または s3
CHANNEL_CONFIG_STORAGE_TYPE=local
# チャンネル設定ファイルのパス（ローカルの場合）
CHANNEL_CONFIG_PATH=channel_config.json

# 使用を禁止するチャンネルIDをカンマ区切りで指定（例: 123456789012345678,876543210987654321）
# 注: 後方互換性のために残っていますが、新システムではファイルベースの設定に移行しています
DENIED_CHANNEL_IDS=
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
- `/sphene mode` - 評価モード（全体モード/限定モード）を切り替えます（管理者のみ）
- `/sphene channels` - チャンネルリストと現在の評価モードを表示します（管理者のみ）
- `/sphene addlist` - 現在のチャンネルをリストに追加します（管理者のみ）
- `/sphene removelist` - 現在のチャンネルをリストから削除します（管理者のみ）
- `/sphene clearlist` - チャンネルリストをクリアします（管理者のみ）
- `/sphene updatelist` - チャンネル設定を手動で保存します（管理者のみ）
- `/sphene reload_prompt` - システムプロンプトを再読み込みします（管理者のみ）

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
├── utils/                # ユーティリティ機能
│   ├── __init__.py
│   ├── channel_config.py # チャンネル設定管理
│   ├── s3_utils.py       # S3関連ユーティリティ
│   └── text_utils.py     # テキスト処理ユーティリティ
```

## 📊 技術仕様

- Python 3.9+
- discord.py - Discordボットフレームワーク
- OpenAI API - GPT-4o-mini会話モデル
- Docker - コンテナ化
- Kubernetes - オプショナルデプロイ環境
- AWS S3 (オプション) - システムプロンプトのリモートストレージ

## 🔒 セキュリティ情報

- APIキーなどの秘密情報は`.env`ファイルまたはKubernetes Secretに保存してください
- チャンネル制限機能を使用することで、ボットの応答可能なチャンネルを制御できます：
  - **全体モード（deny）**: リストに含まれるチャンネル以外で応答可能
  - **限定モード（allow）**: リストに含まれるチャンネルのみで応答可能

## 📝 システムプロンプトのカスタマイズ

ボットのキャラクター設定やふるまいは、システムプロンプトをカスタマイズすることで自由に変更できます。
プロンプトは`prompts/system.txt`（ローカルストレージの場合）または指定したS3バケット内（S3ストレージの場合）に配置します。

### プロンプトストレージオプション

- **ローカルストレージ（デフォルト）**: `.env`で`PROMPT_STORAGE_TYPE=local`を設定
  - プロンプトファイルは`prompts/`ディレクトリに配置

- **S3ストレージ**: `.env`で`PROMPT_STORAGE_TYPE=s3`を設定
  - S3バケット名とオプションのフォルダパスを指定
  - プロンプトファイルはS3バケットの指定されたパスに配置

---

開発者向けメモ: システムプロンプトのカスタマイズやボットの挙動変更が必要な場合は、`prompts/system.txt`または対応するS3内のファイルを編集してください。
