---
applyTo: "**"
---
# Architecture

## Layer Structure

```
app.py → bot/discord_bot.py → bot/commands.py, bot/events.py
                                                    ↓
                               ai/conversation.py → ai/client.py, ai/tools.py → xivapi/client.py
                                                    ↓
                               utils/ (channel_config, firestore_client, text_utils)
                               log_utils/logger.py
```

## Key Components

### SpheneBot (`bot/discord_bot.py`)
Discord接続、コマンド/イベントハンドラ初期化、システムプロンプト読み込み

### Sphene (`ai/conversation.py`)
チャンネルごとの会話コンテキスト維持、Google Gen AI SDK (Vertex AI) 対話、タイムアウト(30分)、最大10ターン、画像処理、ツール呼び出し制御、エラーハンドリング。

### Function Calling (`ai/tools.py`)
ツール定義(`TOOL_DEFINITIONS_RAW`)と実行関数マッピング(`TOOL_FUNCTIONS`)を集約。SDK形式への変換ロジックを保持。

### XIVAPI (`xivapi/client.py`)
XIVAPI v2ゲームデータ検索。アイテム、アクション、レシピ、クエスト等の多種多様なコンテンツに対応。

## Design Patterns

- **Per-channel instances**: `channel_conversations: defaultdict[str, Sphene]` でチャンネルごとに独立した会話（ユーザー間での履歴共有）
- **Storage abstraction**: ローカル/Firestoreを環境変数で切り替え（チャンネル設定）。
- **Error strategy map**: `google.api_core.exceptions` に基づくエラータイプ別処理
- **Prompt cache**: `_prompt_cache: dict[str, str]` でファイルIO削減
- **Thread offloading**: `asyncio.to_thread()`で同期API呼び出しをイベントループから退避

## Message Flow
ユーザー → Discord → イベントハンドラ(トリガー判定/自律判定) → `asyncio.to_thread(process_conversation / _process_autonomous_response)` → Sphene.input_message (バッファ・要約・履歴注入) → Vertex AI (Native SDK) → Discord応答
