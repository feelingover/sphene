# CLAUDE.md

## Memory Bank

`.claude/instructions/memory-bank/` に開発コンテキストを保持。大きな変更後は `activeContext.md` と `progress.md` を更新すること。

## Commands

```bash
python app.py                              # Run bot
uv run python -m pytest                    # Test (全件)
LOG_LEVEL=DEBUG uv run python -m pytest    # Test (デバッグ)
./run_tests.sh                             # Test + coverage report
uv run mypy .                              # Type check
uv sync --group dev                        # Dev dependencies
docker build -t sphene-discord-bot .       # Docker build
```

## Architecture

```
app.py                    # Entry point
config.py                 # Environment-based config
ai/
  client.py               # Google Gen AI SDK client
  conversation.py         # Conversation state, prompt, Gen AI API calls
  tools.py                # Function Calling definitions & conversion
bot/
  discord_bot.py          # Bot core, setup
  commands.py             # Slash commands
  events.py               # Message/reaction event handlers
xivapi/
  client.py               # XIVAPI v2 item search
utils/
  channel_config.py       # Channel permissions (local/Firestore)
  firestore_client.py     # Firestore client (singleton)
  text_utils.py           # Text processing, translation
log_utils/logger.py       # Logging config
storage/                  # Local file storage (prompts, configs)
```

### Key Config Env Vars

- `CHANNEL_CONFIG_STORAGE_TYPE`: "local" | "firestore"
- `FIRESTORE_COLLECTION_NAME`: Firestore collection name (default: "channel_configs")
- `BOT_NAME`: Bot trigger name (default: "スフェーン")
- `COMMAND_GROUP_NAME`: Slash command group prefix

## Code Standards

- 関数長: 20-30行目安、60行超で分割
- Private関数: `_` プレフィックス必須
- エラーログ: `exc_info=True` 必須
- ユーザー向けエラー: 内部詳細を含めない
- Docstring: Google Style
- テストカバレッジ: 86%以上を維持
- 型ヒントを必ず付ける。関数シグネチャを変更した場合は `uv run mypy .` を実行し、影響する全ファイルのインポートも確認する

## Testing

- コード変更後は必ず `uv run python -m pytest` でテスト全件を実行し、全パスを確認してからコミット・PR作成すること。テストが失敗した場合は先に修正する
- フィーチャーフラグ・設定デフォルト値・環境変数に触れる変更をした場合は、テストフィクスチャや `mock_config` オブジェクトで参照箇所がないか確認し、必要に応じて更新する

## PR Creation

- PRには必ず以下を含める:
  - 変更内容のサマリー
  - 変更したファイルの一覧
  - テスト結果（パス件数）
  - ドキュメント更新の有無

## Code Review

- レビュー指摘を出す前に、実際のコード構造と一致しているか確認する（ループの種類、データフローのパターンなど）。実際のコードを引用してから修正案を提示すること
