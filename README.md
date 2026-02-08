# 🔮 Sphene Discord Bot

Spheneは、OpenAI APIを活用した会話機能を持つ、シンプルでパワフルなDiscord botです。メンション、名前呼び、リプライのいずれかで反応し、自然な会話体験を提供します。

## ✨ 主な機能

- 💬 OpenAIのGPT-4o-miniを使用した高度な会話機能
- 📸 画像処理対応のマルチモーダル会話
- 👋 メンション、名前呼び、リプライによる柔軟な反応
- 🌐 国旗リアクションによる自動翻訳機能（🇺🇸 英語 / 🇯🇵 日本語）
- 🔄 会話履歴リセットコマンド
- 📋 禁止チャンネル一覧表示
- ⏱️ 30分の会話タイムアウトによるコンテキストリセット
- 🛡️ チャンネルごとの応答制限機能（全体モード/限定モード）
- 🎭 カスタマイズ可能なシステムプロンプトでボットのキャラクター設定が自由に変更可能
- 🔍 XIVAPI v2連携によるFF14アイテム検索（アイテム名・ジョブ・アイテムレベルでの絞り込み対応）

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

### システムプロンプトの用意

プロジェクトルートにある`system.txt.sample`を使用して、ボットのキャラクター設定を行います：

1. ローカルストレージを使用する場合:

   ```bash
   # システムプロンプトをローカルストレージにコピー
   cp system.txt.sample storage/system.txt
   # 必要に応じてsystem.txtを編集してキャラクター設定をカスタマイズ
   ```

2. S3ストレージを使用する場合:

   ```bash
   # AWSコマンドラインツールを使用してS3にアップロード
   aws s3 cp system.txt.sample s3://your-bucket-name/[folder-path/]system.txt
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

### 翻訳機能の使い方

メッセージに対して国旗のリアクションを追加するだけで翻訳が実行されます：

1. **英語に翻訳**: メッセージに 🇺🇸 リアクションを追加
2. **日本語に翻訳**: メッセージに 🇯🇵 リアクションを追加

注: 翻訳機能は管理者によって有効/無効を切り替えることができます。

### スラッシュコマンド

- `/sphene reset` - 会話履歴をリセットします
- `/sphene mode` - 評価モード（全体モード/限定モード）を切り替えます（管理者のみ）
- `/sphene channels` - チャンネルリストと現在の評価モードを表示します（管理者のみ）
- `/sphene addlist` - 現在のチャンネルをリストに追加します（管理者のみ）
- `/sphene removelist` - 現在のチャンネルをリストから削除します（管理者のみ）
- `/sphene clearlist` - チャンネルリストをクリアします（管理者のみ）
- `/sphene updatelist` - チャンネル設定を手動で保存します（管理者のみ）
- `/sphene reload_prompt` - システムプロンプトを再読み込みします（管理者のみ）
- `/sphene translation` - 翻訳機能の有効/無効を切り替えます（管理者のみ）

## 🛠️ プロジェクト構成

```
/
├── app.py                # メインアプリケーション
├── config.py             # 設定ファイル
├── Dockerfile            # Dockerビルド設定
├── requirements.txt      # 依存パッケージリスト
├── requirements-dev.txt  # 開発用依存パッケージ
├── run_tests.sh          # テスト実行スクリプト
├── .env.sample           # 環境変数サンプル
├── README.md             # このファイル
├── ai/                   # AI関連機能
│   ├── __init__.py
│   ├── client.py         # OpenAI API クライアント
│   ├── conversation.py   # 会話管理ロジック
│   └── tools.py          # Function Callingツール定義
├── bot/                  # Discordボット機能
│   ├── __init__.py
│   ├── commands.py       # スラッシュコマンド定義
│   ├── discord_bot.py    # ボットコア実装
│   └── events.py         # イベントハンドラ
├── log_utils/            # ロギング機能
│   ├── __init__.py
│   └── logger.py         # ロガー設定
├── .github/instructions/memory-bank/  # プロジェクト知識ベース
│   ├── activeContext.instructions.md  # 現在の作業コンテキスト
│   ├── productContext.instructions.md # 製品コンテキスト
│   ├── progress.instructions.md       # 進捗状況
│   ├── projectbrief.instructions.md   # プロジェクト概要
│   ├── systemPatterns.instructions.md # システム設計パターン
│   └── techContext.instructions.md    # 技術コンテキスト
├── storage/              # ストレージ関連ファイル
│   └── system.txt        # システムプロンプト(存在する場合)
├── xivapi/               # XIVAPI v2連携
│   ├── __init__.py
│   └── client.py         # アイテム検索クライアント
├── tests/                # テストコード
│   ├── __init__.py
│   ├── conftest.py       # テスト設定
│   ├── test_ai/          # AI機能テスト
│   ├── test_bot/         # ボット機能テスト
│   ├── test_utils/       # ユーティリティテスト
│   └── test_xivapi/      # XIVAPI機能テスト
└── utils/                # ユーティリティ機能
    ├── __init__.py
    ├── aws_clients.py    # AWS関連ユーティリティ
    ├── channel_config.py # チャンネル設定管理
    ├── s3_utils.py       # S3関連ユーティリティ
    └── text_utils.py     # テキスト処理ユーティリティ
```

## 📊 技術仕様

- Python 3.13+
- discord.py - Discordボットフレームワーク
- OpenAI API - GPT-4o-mini会話モデル（マルチモーダル対応）
- Docker - コンテナ化
- Kubernetes - オプショナルデプロイ環境
- AWS S3 (オプション) - システムプロンプトのリモートストレージ
- XIVAPI v2 - FF14アイテム情報検索API
- httpx - HTTPクライアント（XIVAPI通信用）

## 📋 開発状況

### 現在実装済みの機能

✅ **基本インフラ**

- Discord接続と基本的なボット機能
- OpenAI API連携
- 環境変数による設定
- ログ記録システム

✅ **コアボット機能**

- メンションによる応答
- 名前呼びによる応答
- リプライによる応答
- スラッシュコマンド処理

✅ **AIチャット機能**

- GPT-4o-miniモデルとの対話
- マルチモーダル対応（画像処理）
- 会話履歴の管理
- 会話タイムアウト（30分）
- 会話履歴制限（最大10ターン）
- Function Callingによるツール連携（XIVAPI アイテム検索）

✅ **翻訳機能**

- 国旗リアクションによる翻訳（🇺🇸 英語 / 🇯🇵 日本語）
- 翻訳機能の有効/無効切り替え
- スレッド内での翻訳サポート

✅ **管理機能**

- 会話リセットコマンド
- チャンネルモード切替（全体/限定）
- チャンネルリスト表示
- チャンネル追加/削除/クリア
- システムプロンプト再読み込み

### 今後の開発予定

- チャンネル固有のカスタムプロンプト
- 使用統計の収集と分析
- パフォーマンス最適化
- モニタリングとアラート機能
- 複数のAIモデル選択オプション

## 🔒 セキュリティ情報

- APIキーなどの秘密情報は`.env`ファイルまたはKubernetes Secretに保存してください
- チャンネル制限機能を使用することで、ボットの応答可能なチャンネルを制御できます：
  - **全体モード（deny）**: リストに含まれるチャンネル以外で応答可能
  - **限定モード（allow）**: リストに含まれるチャンネルのみで応答可能

## 📝 システムプロンプトのカスタマイズ

ボットのキャラクター設定やふるまいは、システムプロンプトをカスタマイズすることで自由に変更できます。
プロンプトは`storage/system.txt`（ローカルストレージの場合）または指定したS3バケット内（S3ストレージの場合）に配置します。

### プロンプトストレージオプション

- **ローカルストレージ（デフォルト）**: `.env`で`PROMPT_STORAGE_TYPE=local`を設定
  - プロンプトファイルは`storage/`ディレクトリに配置

- **S3ストレージ**: `.env`で`PROMPT_STORAGE_TYPE=s3`を設定
  - S3バケット名とオプションのフォルダパスを指定
  - プロンプトファイルはS3バケットの指定されたパスに配置

## 📚 メモリーバンク

Spheneプロジェクトでは、`.github/instructions/memory-bank/`ディレクトリに重要なプロジェクト情報を整理して保存しています。
これは開発者間の知識共有や、プロジェクトの継続的な発展をサポートするためのものです。

### メモリーバンクの構成

- **projectbrief.instructions.md** - プロジェクトの基本定義と要件
- **productContext.instructions.md** - 製品の存在理由と解決する問題
- **systemPatterns.instructions.md** - システムアーキテクチャと設計パターン
- **techContext.instructions.md** - 技術スタックと開発環境
- **activeContext.instructions.md** - 現在の作業状況と決定事項
- **progress.instructions.md** - 実装状況と今後の課題

開発者向けにこのメモリーバンクを参照することで、プロジェクトの全体像を素早く把握できます。

---

開発者向けメモ: システムプロンプトのカスタマイズやボットの挙動変更が必要な場合は、`storage/system.txt`または対応するS3内のファイルを編集してください。
