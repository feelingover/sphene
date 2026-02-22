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
Discord接続、コマンド/イベントハンドラ初期化、システムプロンプト読み込み、15分ごとのクリーンアップタスク（バッファ清掃・要約・プロファイル永続化）。

### Sphene (`ai/conversation.py`)
チャンネルごとの会話コンテキスト維持、Google Gen AI SDK (Vertex AI) 対話、タイムアウト(30分)、最大10ターン、画像処理、ツール呼び出し制御、エラーハンドリング。
`input_message(channel_context, channel_summary, user_profile)` でコンテキスト注入を一元管理。

### Function Calling (`ai/tools.py`)
ツール定義(`TOOL_DEFINITIONS_RAW`)と実行関数マッピング(`TOOL_FUNCTIONS`)を集約。SDK形式への変換ロジックを保持。

### XIVAPI (`xivapi/client.py`)
XIVAPI v2ゲームデータ検索。アイテム、アクション、レシピ、クエスト等の多種多様なコンテンツに対応。

### Memory Layer (`memory/`)
| ファイル | 役割 |
|---------|------|
| `short_term.py` | チャンネルバッファ（dequeリングバッファ, TTL管理） |
| `channel_context.py` | チャンネルコンテキスト（ローリング要約, mood, topic_keywords） |
| `user_profile.py` | ユーザープロファイル（interaction_count, familiarity_level, last_topic） |
| `judge.py` | RuleBasedJudge（スコアリング + response_type決定） |
| `llm_judge.py` | LLMJudge（中間スコアの二次判定） |
| `summarizer.py` | ローリング要約エンジン（非同期, fire-and-forget） |

## Design Patterns

- **Per-channel instances**: `channel_conversations: defaultdict[str, Sphene]` でチャンネルごとに独立した会話（ユーザー間での履歴共有）
- **Storage abstraction**: `STORAGE_TYPE`（`local` | `firestore`）1変数でバックエンドを統一切り替え（チャンネル設定・チャンネルコンテキスト・ユーザープロファイル）
- **Singleton stores**: `get_channel_context_store()`, `get_user_profile_store()` でインメモリキャッシュを共有
- **Atomic write**: `tempfile.NamedTemporaryFile` + `os.replace()` でデータロスを防止（channel_context, user_profile のローカル保存）
- **Error strategy map**: `google.api_core.exceptions` に基づくエラータイプ別処理
- **Prompt cache**: `_prompt_cache: dict[str, str]` でファイルIO削減
- **Thread offloading**: `asyncio.to_thread()`で同期API呼び出しをイベントループから退避
- **Opt-in flags**: 全記憶機能のデフォルトは `false`。`MEMORY_ENABLED` がマスタースイッチ。各機能は個別フラグでさらに制御。

## Context Injection Flow (`input_message()`)

```
system_prompt
  + channel_context  (MEMORY_ENABLED: 直近10件のraw文字列)
  + channel_summary  (CHANNEL_CONTEXT_ENABLED: ローリング要約)
  + user_profile     (USER_PROFILE_ENABLED: 関係性・直近話題)
  + TOOL_USAGE_INSTRUCTION
```

## Message Flow
ユーザー → Discord → `_handle_message()`
  → バッファ追加 + チャンネルコンテキスト更新 + **ユーザープロファイル記録** (MEMORY_ENABLED)
  → トリガー判定 (is_mentioned)
    → Yes: **プロファイル取得** → `process_conversation()` → `Sphene.input_message()` → **last_topic更新**
    → No:  Judge評価 → `_dispatch_response()` → react / short_ack / **`_process_autonomous_response()`**
  → Vertex AI (Native SDK) → Discord応答
