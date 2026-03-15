---
applyTo: "**"
---
# Architecture

## Layer Structure

```
app.py → bot/discord_bot.py → bot/commands.py, bot/events.py
                                                    ↓
                               ai/conversation.py → ai/api.py → ai/client.py, ai/tools.py → xivapi/client.py
                               memory/ → ai/api.py
                                                    ↓
                               utils/ (channel_config, file_utils, firestore_client, text_utils)
                               log_utils/logger.py
```

## Key Components

### SpheneBot (`bot/discord_bot.py`)
Discord接続、コマンド/イベントハンドラ初期化、システムプロンプト読み込み、15分ごとのクリーンアップタスク（バッファ清掃・要約・プロファイル永続化）。

### API Layer (`ai/api.py`)
GenAI API 呼び出しロジックを集約。`generate_content_with_retry`（tenacityリトライ付き）、`call_genai_with_tools`（ツール呼び出しループ）、`_execute_tool_calls`、`_handle_api_error`。`memory/summarizer.py` および `memory/llm_judge.py` はこのモジュールをインポート。

### Sphene (`ai/conversation.py`)
会話ステート層のみ。チャンネルごとの履歴管理（`channel_conversations: defaultdict`）、タイムアウト(30分)、最大10ターン、画像処理、システムプロンプトキャッシュ。API 呼び出し本体は `ai/api.py` に委譲。
`input_message(channel_context, channel_summary, user_profile, relevant_facts)` でコンテキスト注入を一元管理。

### Event Helpers (`bot/events.py`)
共通ロジックを4ヘルパーに抽出: `_collect_ai_context()`, `_get_or_reset_conversation()`, `_send_chunks()`, `_post_response_update()`。
自発会話: `_try_proactive_conversation()`, `_dispatch_proactive_message()`。

### Function Calling (`ai/tools.py`)
ツール定義(`TOOL_DEFINITIONS_RAW`)と実行関数マッピング(`TOOL_FUNCTIONS`)を集約。SDK形式への変換ロジックを保持。

### XIVAPI (`xivapi/client.py`)
XIVAPI v2ゲームデータ検索。アイテム、アクション、レシピ、クエスト等の多種多様なコンテンツに対応。

### Memory Layer (`memory/`) - 「リビングメモリー (Living Memory)」

多層的な記憶システム。詳細は `docs/living-memory.md` を参照。

| レイヤー | ファイル | 役割 |
|---------|---------|------|
| **短期** | `short_term.py` | チャンネルバッファ（dequeリングバッファ, TTL管理, 反省会チェックポイント） |
| **中期** | `channel_context.py` | チャンネルコンテキスト（mood, topic_keywords） |
| **中期** | `summarizer.py` | ローリング要約エンジン（非同期, fire-and-forget） |
| **長期** | `user_profile.py` | ユーザープロファイル（interaction_count, familiarity_level, last_topic） |
| **長期** | `fact_store.py` | ファクトストア（Fact dataclass, Jaccard×decay検索, local/Firestore永続化） |
| **思考** | `reflection.py` | 反省会エンジン（LLMによるファクト抽出, fire-and-forget非同期） |
| **判定** | `judge.py` | RuleBasedJudge（スコアリング + response_type決定） |
| **判定** | `llm_judge.py` | LLMJudge（中間スコアの二次判定） |

## Design Patterns

- **Per-channel instances**: `channel_conversations: defaultdict[str, Sphene]` でチャンネルごとに独立した会話（ユーザー間での履歴共有）
- **Storage abstraction**: `STORAGE_TYPE`（`local` | `firestore`）1変数でバックエンドを統一切り替え（チャンネル設定・チャンネルコンテキスト・ユーザープロファイル）
- **Singleton stores**: `get_channel_context_store()`, `get_user_profile_store()` でインメモリキャッシュを共有
- **Atomic write**: `utils/file_utils.py:atomic_write_json()` に共通化。`tempfile.NamedTemporaryFile` + `os.replace()` でデータロスを防止（channel_config, channel_context, user_profile のローカル保存）
- **Startup validation**: `config.py` 末尾でフィーチャーフラグの依存関係を起動時に検証（`ValueError` で即時失敗）
- **Error strategy map**: `google.api_core.exceptions` に基づくエラータイプ別処理
- **Prompt cache**: `_prompt_cache: dict[str, str]` でファイルIO削減
- **Thread offloading**: `asyncio.to_thread()`で同期API呼び出しをイベントループから退避
- **Opt-in flags**: 短期記憶（チャンネルバッファ）は常時有効。`CHANNEL_CONTEXT_ENABLED`、`USER_PROFILE_ENABLED`、`AUTONOMOUS_RESPONSE_ENABLED` 等の機能フラグで個別に制御。

## Context Injection Flow (`input_message()`)

```
system_prompt
  + channel_context  (常時有効: 直近10件のraw文字列)
  + channel_summary  (CHANNEL_CONTEXT_ENABLED: ローリング要約)
  + user_profile     (USER_PROFILE_ENABLED: 関係性・直近話題)
  + relevant_facts   (REFLECTION_ENABLED: 関連する過去の記憶)
  + TOOL_USAGE_INSTRUCTION
```

## Message Flow
ユーザー → Discord → `_handle_message()`
  → バッファ追加 + チャンネルコンテキスト更新 + **ユーザープロファイル記録**
  → **バッファ量ベース反省会トリガー** (`REFLECTION_ENABLED`: メッセージ数 >= MAX_BUFFER_MESSAGES)
  → トリガー判定 (is_mentioned)
    → Yes: **プロファイル取得** → `process_conversation()` → `Sphene.input_message()` → **last_topic更新**
    → No:  Judge評価 → `_dispatch_response()` → react / short_ack / **`_process_autonomous_response()`**
  → Vertex AI (Native SDK) → Discord応答

## Reflection Flow（反省会）
トリガー: 沈黙N分（`_cleanup_task`で検知）OR バッファ量超過（`_handle_message`で検知）
  → `ReflectionEngine.maybe_reflect()` → `asyncio.ensure_future(_run_reflect())`
  → `asyncio.to_thread(_call_reflection_llm())` → Gemini API → JSON配列
  → `_apply_facts()` → `FactStore.add_fact()` × N件 → `mark_reflected()`
  → 次回 `_collect_ai_context()` でファクト検索 → `relevant_facts` としてプロンプトへ注入
