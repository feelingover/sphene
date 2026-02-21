# Sphene Discord Bot

SpheneはGoogle Gen AI SDK（Vertex AI経由のGemini）を活用した会話機能を持つDiscord botです。メンション、名前呼び、リプライのいずれかで反応し、自然な会話体験を提供します。

## 主な機能

- Google Gen AI SDK（Vertex AI / Gemini）による会話機能
- 画像処理対応のマルチモーダル会話
- メンション、名前呼び、リプライによる柔軟な反応
- **チャンネル単位の会話履歴共有**: 複数ユーザーが参加するグループチャットの文脈を理解
- 国旗リアクションによる自動翻訳機能（🇺🇸 英語 / 🇯🇵 日本語）
- チャンネルごとの会話履歴リセットコマンド
- チャンネルごとの応答制限機能（全体モード/限定モード）
- カスタマイズ可能なシステムプロンプトでボットのキャラクター設定が自由に変更可能
- XIVAPI v2連携によるFF14データ検索（アイテム、アクション、レシピ、クエスト、アチーブメント、F.A.T.E.、マウント、ミニオン、ステータス。ジョブ・IL・レベルでの絞り込み対応）
- Google検索Grounding対応（Geminiの検索拡張機能）
- 自律応答機能（ルールベーススコアリング＋LLM二次判定による自動会話参加）
- 短期記憶（チャンネルメッセージバッファ）による文脈を考慮した応答
- **コンテキスト統合**: メンション応答と自律応答が共通の履歴とチャンネル文脈を参照
- チャンネルコンテキスト（ローリング要約による場の空気把握）
- 応答多様性（リアクション / 相槌 / フル応答の3段階で自然な会話参加）
- **ユーザープロファイル**: 交流回数・関係性レベル（stranger/acquaintance/regular/close）・直近の話題を記録し、初見と常連で自然に接し方を変える

## セットアップ方法

### 環境変数の設定

`.env`ファイルを`.env.sample`をもとに作成し、必要な情報を入力します：

```
DISCORD_TOKEN=your_discord_bot_token
BOT_NAME=スフェーン  # ボットの呼び名（コードのデフォルト: アサヒ）
COMMAND_GROUP_NAME=sphene  # コマンドグループ名（コードのデフォルト: asahi）
GEMINI_MODEL=google/gemini-2.5-flash  # 使用するモデル

# Vertex AI設定
AI_PROVIDER=vertex_ai
# VERTEX_AI_PROJECT_ID=your-gcp-project-id  # 未設定の場合はGCEメタデータから自動取得
VERTEX_AI_LOCATION=asia-northeast1

# Google検索によるGroundingを有効にするか
ENABLE_GOOGLE_SEARCH_GROUNDING=false

# システムプロンプトの設定
SYSTEM_PROMPT_FILENAME=system.txt

# チャンネル設定のストレージタイプ: local または firestore
CHANNEL_CONFIG_STORAGE_TYPE=local

# Firestoreコレクション名（CHANNEL_CONFIG_STORAGE_TYPE=firestore の場合に使用）
FIRESTORE_COLLECTION_NAME=channel_configs
# GCPサービスアカウントキーのパス（Workload Identity使用時は不要）
# GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json

# ログレベル設定: DEBUG, INFO, WARNING, ERROR, CRITICAL のいずれか
LOG_LEVEL=INFO
# ログフォーマット設定: json（デフォルト・Google Cloud Logging向け）または text（ローカル開発向け）
LOG_FORMAT=json

# === 記憶機能設定 ===

# 短期記憶（チャンネルメッセージバッファ）
MEMORY_ENABLED=false
# CHANNEL_BUFFER_SIZE=50
# CHANNEL_BUFFER_TTL_MINUTES=30

# 自律応答
AUTONOMOUS_RESPONSE_ENABLED=false
# JUDGE_SCORE_THRESHOLD=20
# JUDGE_SCORE_FULL_RESPONSE=60
# JUDGE_SCORE_SHORT_ACK=30
# COOLDOWN_SECONDS=120
# ENGAGEMENT_DURATION_SECONDS=300  # エンゲージメント期間（秒）。応答後この期間中はスコアブースト
# ENGAGEMENT_BOOST=40              # エンゲージメント中のスコア加算値
# JUDGE_KEYWORDS=  # カンマ区切りでスコアブーストするキーワードを指定

# LLM Judge（二次判定: 中間スコアのメッセージをLLMで判定）
# LLM_JUDGE_ENABLED=false
# JUDGE_MODEL=  # 空の場合はGEMINI_MODELと同じモデルを使用
# JUDGE_LLM_THRESHOLD_LOW=20
# JUDGE_LLM_THRESHOLD_HIGH=60

# チャンネルコンテキスト（ローリング要約による場の空気把握）
# CHANNEL_CONTEXT_ENABLED=false
# CHANNEL_CONTEXT_STORAGE_TYPE=memory  # memory | local | firestore
# SUMMARIZE_EVERY_N_MESSAGES=20        # N件ごとに要約実行
# SUMMARIZE_EVERY_N_MINUTES=15         # N分経過で要約実行（メッセージ1件以上の場合）
# SUMMARIZE_MODEL=                     # 空の場合はGEMINI_MODELと同じモデルを使用

# 応答多様性（有効にするとスコアに応じてリアクション/相槌/フル応答を使い分け）
# RESPONSE_DIVERSITY_ENABLED=false

# ユーザープロファイル（交流回数・関係性・直近話題の記録）
# USER_PROFILE_ENABLED=false
# USER_PROFILE_STORAGE_TYPE=memory  # memory | local | firestore
# FAMILIARITY_THRESHOLD_ACQUAINTANCE=6    # 0-5回: stranger / 6回以上: acquaintance
# FAMILIARITY_THRESHOLD_REGULAR=31        # 6-30回: acquaintance / 31回以上: regular
# FAMILIARITY_THRESHOLD_CLOSE=101         # 31-100回: regular / 101回以上: close
# USER_PROFILES_COLLECTION_NAME=user_profiles  # Firestoreコレクション名（マルチテナント対応）
```

### システムプロンプトの用意

プロジェクトルートにある`system.txt.sample`を使用して、ボットのキャラクター設定を行います：

```bash
# システムプロンプトをローカルストレージにコピー
cp system.txt.sample storage/system.txt
# 必要に応じてsystem.txtを編集してキャラクター設定をカスタマイズ
```

### 必要なパッケージのインストール

[uv](https://docs.astral.sh/uv/)を使用して依存関係を管理しています：

```bash
# uvのインストール（未インストールの場合）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 依存パッケージのインストール
uv sync

# 開発用パッケージも含める場合
uv sync --group dev
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

## Kubernetesへのデプロイ

環境変数をKubernetes Secretとして作成し、Podから参照できるようにします：

```bash
# 環境変数を含むSecretの作成
kubectl create secret generic sphene-envs --from-env-file ./.env

# GitHub Container Registry認証用Secretの作成
kubectl create secret docker-registry regcred --docker-server=ghcr.io --docker-username=<GitHubユーザー名> --docker-password=<GitHubトークン>
```

デプロイメントやサービスの設定は別途YAMLファイルで定義します。

## 使用方法

### ボットとの会話

以下のいずれかの方法でボットと会話できます：

1. **メンション**: `@ボット名 こんにちは！`
2. **名前呼び**: `ボット名、元気？`
3. **リプライ**: ボットのメッセージに返信する

### 自律応答

記憶機能と自律応答を有効にすると、ボットは明示的に呼びかけられなくても、会話の流れに応じて自然に参加します。

- **ルールベース判定**: キーワード一致、エンゲージメント状態、クールダウン、会話フロー分析によるスコアリング
- **LLM二次判定（オプション）**: 中間スコアのメッセージに対して、LLMが会話文脈を考慮して追加判定
- **応答多様性（オプション）**: スコアに応じた3段階の応答タイプ
  - **リアクション**: 低スコア時に絵文字リアクションで軽く参加
  - **相槌**: 中スコア時に一言の短い相槌で反応
  - **フル応答**: 高スコア時にチャンネルの文脈を踏まえた本格的な応答
- **チャンネルコンテキスト（オプション）**: ローリング要約でチャンネルの雰囲気・話題・参加者を把握し、応答品質を向上
- 詳細は `docs/autonomous-response.md` を参照

### 翻訳機能の使い方

メッセージに対して国旗のリアクションを追加するだけで翻訳が実行されます：

1. **英語に翻訳**: メッセージに 🇺🇸 リアクションを追加
2. **日本語に翻訳**: メッセージに 🇯🇵 リアクションを追加

注: 翻訳機能は管理者によって有効/無効を切り替えることができます。

### スラッシュコマンド

コマンドプレフィックスは `COMMAND_GROUP_NAME` 環境変数で設定（デフォルト: `asahi`）。

- `/<prefix> reset` - 会話履歴をリセットします
- `/<prefix> mode` - 評価モード（全体モード/限定モード）を切り替えます（管理者のみ）
- `/<prefix> channels` - チャンネルリストと現在の評価モードを表示します（管理者のみ）
- `/<prefix> addlist` - 現在のチャンネルをリストに追加します（管理者のみ）
- `/<prefix> removelist` - 現在のチャンネルをリストから削除します（管理者のみ）
- `/<prefix> clearlist` - チャンネルリストをクリアします（管理者のみ）
- `/<prefix> updatelist` - チャンネル設定を手動で保存します（管理者のみ）
- `/<prefix> reload_prompt` - システムプロンプトを再読み込みします（管理者のみ）
- `/<prefix> translation` - 翻訳機能の有効/無効を切り替えます（管理者のみ）

## プロジェクト構成

```
/
├── app.py                  # メインアプリケーション（エントリーポイント）
├── config.py               # 環境変数ベースの設定
├── Dockerfile              # Dockerビルド設定
├── pyproject.toml          # プロジェクト設定・依存定義
├── uv.lock                 # 依存パッケージのロックファイル
├── .python-version         # Pythonバージョン指定
├── run_tests.sh            # テスト実行スクリプト
├── .env.sample             # 環境変数サンプル
├── README.md               # このファイル
├── ai/                     # AI関連機能
│   ├── __init__.py
│   ├── client.py           # Google Gen AI SDKクライアント（Vertex AI経由）
│   ├── conversation.py     # 会話管理・プロンプト・Gen AI API呼び出し
│   └── tools.py            # Function Calling ツール定義・変換
├── bot/                    # Discordボット機能
│   ├── __init__.py
│   ├── commands.py         # スラッシュコマンド定義
│   ├── discord_bot.py      # ボットコア実装
│   └── events.py           # メッセージ・リアクションイベントハンドラ
├── memory/                 # 記憶・自律応答機能
│   ├── __init__.py
│   ├── channel_context.py  # チャンネルコンテキスト（ローリング要約）
│   ├── judge.py            # ルールベース自律応答判定
│   ├── llm_judge.py        # LLMによる二次判定
│   ├── short_term.py       # チャンネルメッセージバッファ（短期記憶）
│   ├── summarizer.py       # ローリング要約エンジン
│   └── user_profile.py     # ユーザープロファイル（関係性・直近話題）
├── xivapi/                 # XIVAPI v2連携
│   ├── __init__.py
│   ├── client.py           # ゲームデータ検索クライアント
│   └── SPEC.md             # API仕様・設計メモ
├── utils/                  # ユーティリティ機能
│   ├── __init__.py
│   ├── channel_config.py   # チャンネル設定管理（local/Firestore）
│   ├── firestore_client.py # Firestoreクライアント（シングルトン）
│   └── text_utils.py       # テキスト処理・翻訳
├── log_utils/              # ロギング機能
│   ├── __init__.py
│   └── logger.py           # ロガー設定
├── storage/                # ローカルファイルストレージ（プロンプト、設定）
├── scripts/                # ユーティリティスクリプト
│   ├── migrate_s3_to_firestore.py  # S3→Firestoreマイグレーションツール
│   └── verify_grounding.py         # Grounding検証スクリプト
├── docs/                   # ドキュメント
│   └── autonomous-response.md      # 自律応答機能の仕様
├── tests/                  # テストコード
│   ├── conftest.py         # テスト設定
│   ├── test_ai/            # AI機能テスト
│   ├── test_bot/           # ボット機能テスト
│   ├── test_memory/        # 記憶・自律応答テスト
│   ├── test_utils/         # ユーティリティテスト
│   └── test_xivapi/       # XIVAPI機能テスト
└── .claude/instructions/memory-bank/  # プロジェクト知識ベース
    ├── activeContext.md               # 現在の作業コンテキスト
    ├── architecture.md                # システム設計・アーキテクチャ
    └── progress.md                    # 進捗状況
```

## 技術仕様

- Python 3.14+
- uv - パッケージ管理・仮想環境管理
- discord.py - Discordボットフレームワーク
- Google Gen AI SDK (`google-genai`) - Vertex AI経由のGeminiモデルによる会話（マルチモーダル対応）
- google-auth - GCP認証（Vertex AI利用時）
- google-cloud-aiplatform - Vertex AI基盤
- Docker - コンテナ化
- Kubernetes - オプショナルデプロイ環境
- Cloud Firestore (オプション) - チャンネル設定のリモートストレージ
- XIVAPI v2 - FF14ゲームデータ検索API
- httpx - HTTPクライアント（XIVAPI通信用）
- requests - HTTPクライアント（画像取得用）

## 開発状況

### 現在実装済みの機能

**基本インフラ**

- Discord接続と基本的なボット機能
- Google Gen AI SDK（Vertex AI）連携
- 環境変数による設定
- ログ記録システム

**コアボット機能**

- メンションによる応答
- 名前呼びによる応答
- リプライによる応答
- スラッシュコマンド処理

**AIチャット機能**

- Google Gen AI SDK（Vertex AI / Gemini）による会話
- マルチモーダル対応（画像処理）
- 会話履歴の管理
- 会話タイムアウト（30分）
- 会話履歴制限（最大10ターン）
- Function Callingによるツール連携（XIVAPI ゲームデータ検索）
- Google検索Grounding（オプション）

**記憶・自律応答機能**

- チャンネルメッセージバッファ（短期記憶）
- ルールベースのスコアリングによる自律応答判定
- LLMによる二次判定（オプション）
- エンゲージメント追跡とクールダウン制御
- キーワードベースのスコアブースト
- チャンネルコンテキスト（ローリング要約 - メッセージ数/時間ベースのハイブリッドトリガー）
- 応答多様性（リアクション / 相槌 / フル応答の3段階）
- 会話フロー分析（2人会話検出、高頻度検出、沈黙後検出、会話減衰検出）
- ユーザープロファイル（交流回数・関係性レベル・直近話題の記録、15分ごとの定期永続化）

**翻訳機能**

- 国旗リアクションによる翻訳（🇺🇸 英語 / 🇯🇵 日本語）
- 翻訳機能の有効/無効切り替え
- スレッド内での翻訳サポート

**管理機能**

- 会話リセットコマンド
- チャンネルモード切替（全体/限定）
- チャンネルリスト表示
- チャンネル追加/削除/クリア
- システムプロンプト再読み込み

## セキュリティ情報

- APIキーなどの秘密情報は`.env`ファイルまたはKubernetes Secretに保存してください
- チャンネル制限機能を使用することで、ボットの応答可能なチャンネルを制御できます：
  - **全体モード（deny）**: リストに含まれるチャンネル以外で応答可能
  - **限定モード（allow）**: リストに含まれるチャンネルのみで応答可能

## システムプロンプトのカスタマイズ

ボットのキャラクター設定やふるまいは、システムプロンプトをカスタマイズすることで自由に変更できます。
プロンプトファイルは`storage/system.txt`に配置します。

```bash
# システムプロンプトのカスタマイズ
vi storage/system.txt  # ボットのキャラクター設定を編集
```

## メモリーバンク

Spheneプロジェクトでは、`.claude/instructions/memory-bank/`ディレクトリに重要なプロジェクト情報を整理して保存しています。
これは開発者間の知識共有や、プロジェクトの継続的な発展をサポートするためのものです。

### メモリーバンクの構成

- **activeContext.md** - 現在の作業状況と決定事項、最近の変更履歴
- **architecture.md** - システムアーキテクチャ、設計パターン、コンポーネント構成
- **progress.md** - 実装済みの機能と今後の課題

開発者向けにこのメモリーバンクを参照することで、プロジェクトの全体像を素早く把握できます。

---

開発者向けメモ: システムプロンプトのカスタマイズやボットの挙動変更が必要な場合は、`storage/system.txt`を編集してください。
