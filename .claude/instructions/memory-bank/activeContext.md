---
applyTo: "**"
---
# Active Context

## Current State (2026/3)

- 記憶システム「リビングメモリー (Living Memory)」の仕様を `docs/living-memory.md` に集約。
- 全テスト通過（655件）、カバレッジ 90%、mypy 72ファイル no issues
- 記憶機能 Phase 3B（Vertex AI Embeddings + ハイブリッド検索）実装済み。`VECTOR_SEARCH_ENABLED` で後方互換フラグ制御。
- リアクション機能の抜本的な見直し（issue #97）実装済み。`should_react` フィールドによる独立制御、先行実行（asyncio.create_task）、LLM絵文字選択に対応。
- 記憶機能 Phase 3A（反省会 + ファクトストア + 自発的会話）実装済み。
- Vertex AI Native SDK (`google-genai`) への完全移行完了。OpenAI互換APIを廃止し、Gemini 3等の最新モデルに完全対応。
- 環境変数を `GEMINI_MODEL` 形式に統一、`OPENAI_API_KEY` を完全削除。
- Google検索Grounding機能のサポート開始（`ENABLE_GOOGLE_SEARCH_GROUNDING`）。
- Discord heartbeat blocking修正済み（`asyncio.to_thread()`）。
- 記憶機能（Phase 1 + Phase 2 + Phase 2A + Phase 2B + Phase 3A）実装済み。
- ツール呼び出しループの改善済み（上限の環境変数化 + ツールなし最終コール）。
- コードレビュー Medium/Low 全課題対応完了（Group A〜E）。

## Recent Changes

### 2026/3: 記憶機能 Phase 3B - Vertex AI Embeddings + ハイブリッド検索 (issue #77, #78)

Jaccard検索にコサイン類似度を組み合わせたハイブリッド検索を実装。`VECTOR_SEARCH_ENABLED=false`（デフォルト）で既存動作を維持。

#### 変更ファイル
- **`ai/client.py`**: `generate_embedding(text)` 追加（失敗時 `None` を返しJaccardにフォールバック）
- **`memory/fact_store.py`**: `Fact.embedding` フィールド追加、`_cosine_similarity()` ヘルパー追加、`search()` にハイブリッドスコアリング追加（コサインは `max(0, cosine)` でクリッピング）
- **`memory/reflection.py`**: `_apply_facts()` を `async def` に変更、`asyncio.gather()` でEmbedding並列生成
- **`bot/events.py`**: `VECTOR_SEARCH_ENABLED` 有効時にクエリEmbeddingを生成して `search()` に渡す
- **`config.py`**: `EMBEDDING_MODEL`（デフォルト: `text-embedding-004`）、`VECTOR_SEARCH_ENABLED`、`HYBRID_ALPHA`（デフォルト: 0.5）追加
- **`.env.sample`**: 新環境変数を追記

#### 新規環境変数
- `EMBEDDING_MODEL`: Embedding生成モデル名（デフォルト: `text-embedding-004`）
- `VECTOR_SEARCH_ENABLED`: ハイブリッド検索有効化（デフォルト: false）
- `HYBRID_ALPHA`: ベクトル/キーワードスコアのバランス係数（デフォルト: 0.5）

### 2026/3: リアクション機能の抜本的な見直し (issue #97)

リアクションを `response_type == "react_only"` の排他制御から独立した `should_react` フィールドに分離。

#### 変更ファイル
- **`config.py`**: `REACTION_ENABLED`（デフォルト false）と `JUDGE_REACT_THRESHOLD`（デフォルト 5）を追加
- **`memory/judge.py`**: `JudgeResult` に `should_react: bool` と `reaction_emojis: list[str]` フィールドを追加。`evaluate()` で独立スコア判定
- **`memory/llm_judge.py`**: プロンプトに `react/emojis` フィールドを追加。戻り値型を 2-tuple → 4-tuple `(bool, str, bool, list[str])` に変更（破壊的変更）
- **`bot/events.py`**: `_send_reaction()` に `emojis/record` パラメータ追加。`_try_autonomous_response()` でリアクションを `asyncio.create_task` で先行発火

#### 新規環境変数
- `REACTION_ENABLED`: リアクション機能の有効化（デフォルト false）
- `JUDGE_REACT_THRESHOLD`: リアクション実行の最低スコア閾値（デフォルト 5）

### 2026/2: 記憶システムのブランド化「リビングメモリー」

ボットの多層的な記憶システムを「リビングメモリー (Living Memory)」と命名し、仕様を `docs/living-memory.md` にまとめた。短期・中期・長期の3層構造で、ボットが「チャンネルの参加者の一人」として振る舞うための基盤となる。

### 2026/2: Phase 3A - 反省会 + ファクトストア + 自発的会話

会話の長期記憶をキーワードベースで実現。チャンネルが沈黙後に再活性化した際、過去に抽出した事実を自発的に話題にする。

#### 新規ファイル
- **`memory/fact_store.py`**: `Fact` dataclass + `FactStore`
  - `Fact`: `fact_id`, `channel_id`, `content`, `keywords`, `source_user_ids`, `created_at`, `shareable`
  - `decay_factor(half_life_days)`: 指数減衰係数（半減期でスコア0.5）
  - `FactStore.add_fact()`: 追加 + 上限超過時は decay 最小のものを削除
  - `FactStore.search(keywords, user_ids, limit)`: Jaccard類似度 × decay_factor × user_idブースト(`FACT_USER_BOOST_FACTOR`倍、デフォルト1.5)でランキング
  - `FactStore.get_shareable_facts()`: shareable=True のみ decay 降順
  - `FactStore.persist_all()`: クリーンアップタスクから呼ばれる全チャンネル永続化
  - 遅延ロード（初回アクセス時のみ）、ローカル(`storage/facts.{channel_id}.json`) / Firestore対応
  - `_jaccard_similarity(set_a, set_b)` / `extract_keywords(text)`: キーワード抽出ヘルパー（公開API）
  - シングルトン: `get_fact_store()`

- **`memory/reflection.py`**: `ReflectionEngine`（反省会エンジン）
  - `maybe_reflect(channel_id, recent_messages)`: トリガー判定 + fire-and-forget非同期実行（`ensure_future`）
  - `_call_reflection_llm(messages)`: Gemini呼び出し（JSON配列を返す）
  - `_apply_facts(channel_id, raw_facts, messages)`: LLM結果を `Fact` に変換し `FactStore` に保存、`mark_reflected()` を呼ぶ
  - `_running: set[int]` で二重実行を防止
  - `Summarizer` と同一パターン（`summarizer.py` の設計を踏襲）
  - シングルトン: `get_reflection_engine()`

#### 既存ファイルの変更
- **`config.py`**:
  - `FIRESTORE_COLLECTION_FACTS`: ネームスペース対応のコレクション名
  - `FACT_STORE_MAX_FACTS_PER_CHANNEL`（デフォルト100）, `FACT_DECAY_HALF_LIFE_DAYS`（デフォルト30）
  - `REFLECTION_ENABLED`, `REFLECTION_LULL_MINUTES`（10）, `REFLECTION_MIN_MESSAGES`（10）, `REFLECTION_MAX_BUFFER_MESSAGES`（100）, `REFLECTION_MODEL`
  - `PROACTIVE_CONVERSATION_ENABLED`: `REFLECTION_ENABLED=True` が必要（起動時バリデーション追加）
  - `FACT_USER_BOOST_FACTOR`（デフォルト1.5）: ユーザーIDが一致するファクトのスコアブースト倍率
  - `PROACTIVE_SILENCE_MINUTES`（デフォルト10）: 自発会話トリガーの沈黙閾値（`REFLECTION_LULL_MINUTES` と独立）

- **`memory/short_term.py`**: `ChannelMessageBuffer` に4メソッド追加
  - `_last_reflected: dict[int, datetime]` フィールド追加
  - `get_active_channel_ids()`: バッファが存在するチャンネルIDリスト
  - `get_last_message_time(channel_id)`: 最新メッセージのUTCタイムスタンプ
  - `count_messages_since_reflection(channel_id)`: 最後の `mark_reflected` 以降のメッセージ数
  - `mark_reflected(channel_id)`: 反省会チェックポイントを現在時刻で記録

- **`ai/conversation.py`**: `input_message()` / `async_input_message()` に `relevant_facts: str = ""` パラメータ追加
  - `user_profile` の後に `context_section` へ注入

- **`bot/events.py`**:
  - `_collect_ai_context()`: 戻り値を5タプルに拡張 `(channel_context, channel_summary, topic_keywords, user_profile_str, relevant_facts_str)`。`REFLECTION_ENABLED` 時にファクト検索・注入。
  - `_handle_message()`: バッファ追加前に `pre_add_last_time` 取得、バッファ量ベース反省会トリガー、自発会話チェック追加
  - `_try_proactive_conversation(bot, message, pre_add_last_time)`: 沈黙時間チェック → クールダウンチェック → shareable ファクト取得 → `_dispatch_proactive_message()`
  - `_dispatch_proactive_message(bot, message, fact)`: ファクトをもとにプロンプト生成・Gemini呼び出し・送信

- **`bot/discord_bot.py`**: `_cleanup_task` に沈黙ベース反省会チェック + ファクトストア `persist_all()` 追加

#### 有効化設定
```
REFLECTION_ENABLED=true
REFLECTION_MIN_MESSAGES=10      # 反省会実行最低メッセージ数
REFLECTION_LULL_MINUTES=10      # 沈黙検知時間（分）
# 自発会話も使う場合:
PROACTIVE_CONVERSATION_ENABLED=true
```

### 2026/2: Phase 3A コードレビュー対応（7件）

PR #76 のコードレビュー指摘を解消。

- **`extract_keywords` 公開化**: `_extract_keywords` → `extract_keywords`（`bot/events.py` からのプライベート関数クロスモジュールインポートを解消）
- **`FACT_USER_BOOST_FACTOR` 環境変数化**: ハードコードの `1.5` を `config.py` で管理
- **`PROACTIVE_SILENCE_MINUTES` 追加**: 自発会話の沈黙閾値を `REFLECTION_LULL_MINUTES` から独立化
- **`_load_channel` コメント修正**: DCL の説明を実装（2段階ロック）に合わせて修正
- **`_dispatch_proactive_message` 型修正**: `fact: Any` → `fact: "Fact"` + `TYPE_CHECKING` インポート
- **冗長インポート削除**: `_try_proactive_conversation` 内の `from datetime import timezone` ローカルインポートを削除（モジュールレベルで定義済み）
- **`_cleanup_task` ブロック統合**: `if config.REFLECTION_ENABLED:` 2ブロック → 1ブロックに集約

### 2026/2: コードレビュー Medium/Low 課題の一括対応（Group A〜E）

コードレビューで指摘された 10件の Medium + 4件の Low を 5グループに分けて解消。

#### Group A: スモールフィックス
- 空 Cog (`discord.ext.commands.Cog(name="Management")`) を削除（`bot/events.py`）
- `error_message` 重複変数を1箇所に集約（`translate_and_reply`）
- 裸の `except:` → `except (ValueError, json.JSONDecodeError):`
- `_handle_api_error` をタイプベースチェックに統一（文字列マッチ廃止）
- フィーチャーフラグの依存関係を `config.py` 末尾で起動時バリデーション

#### Group B: デッドコード削除
- `generate_contextual_response()` 関数を削除（5テストも削除）
- `ai/conversation.py` のローカル `truncate_text` 定義を削除 → `utils.text_utils` を直接インポート

#### Group C: 冗長ロジック整理
- `can_bot_speak()` で `get_channels()` 二重呼び出しを解消
- `_handle_message()` の `behavior` / `in_list` デバッグ変数を削除
- `utils/file_utils.py` を新規作成し `atomic_write_json()` を3ファイルから抽出・共通化
  - 適用先: `utils/channel_config.py`, `memory/channel_context.py`, `memory/user_profile.py`
- `judge.evaluate()` の常時 False パラメータ3個 (`is_mentioned`, `is_name_called`, `is_reply_to_bot`) を削除

#### Group D: 大規模リファクタ（`bot/events.py`）
`process_conversation` と `_process_autonomous_response` の共通ロジックを4ヘルパーに抽出:
- `_collect_ai_context(message)` → `(channel_context, channel_summary, topic_keywords, user_profile_str)`
- `_get_or_reset_conversation(channel_id)` → Spheneインスタンス取得/リセット
- `_send_chunks(message, chunks, is_reply)` → チャンク分割送信
- `_post_response_update(message, answer, topic_keywords, bot_user)` → プロファイル更新 + バッファ追加

#### Group E: アーキテクチャ
- **E-1: `ai/api.py` 新規作成** — API レイヤーを `ai/conversation.py` から分離
  - `generate_content_with_retry`, `call_genai_with_tools`, `_execute_tool_calls`, `_handle_api_error` を移管
  - `memory/summarizer.py`, `memory/llm_judge.py` のインポート先を `ai.api` に更新
  - `ai/conversation.py` は会話ステート層（`Sphene`, `channel_conversations`, `load_system_prompt` 等）のみに
- **E-2: `config.py` 依存コメント追加** — 各フラグに依存関係を明記

### 2026/2: Firestoreコレクション名のネームスペース化

`FIRESTORE_COLLECTION_NAME` と `USER_PROFILES_COLLECTION_NAME` を廃止し、単一の `FIRESTORE_NAMESPACE` 環境変数でコレクション名プレフィックスを制御する形式に統一。

- **削除した環境変数**: `FIRESTORE_COLLECTION_NAME`, `USER_PROFILES_COLLECTION_NAME`
- **追加した環境変数**: `FIRESTORE_NAMESPACE`（空=プレフィックスなし、設定時: `{namespace}_channel_configs` 等）
- **追加した定数**: `FIRESTORE_COLLECTION_CHANNEL_CONFIGS`, `FIRESTORE_COLLECTION_USER_PROFILES`, `FIRESTORE_COLLECTION_CHANNEL_CONTEXTS`
- **ヘルパー関数**: `config.get_collection_name(base_name)` でネームスペース付きコレクション名を生成
- `memory/channel_context.py` のハードコード `"channel_contexts"` を定数参照に修正
- 移行スクリプト: `scripts/migrate_firestore_namespace.py`（旧コレクション→新ネームスペース付きコレクションへのコピー）

### 2026/2: ストレージタイプ設定の統合

`CHANNEL_CONFIG_STORAGE_TYPE`、`CHANNEL_CONTEXT_STORAGE_TYPE`、`USER_PROFILE_STORAGE_TYPE` の3変数を廃止し、単一の `STORAGE_TYPE`（`local` | `firestore`）に統合。`memory` オプションも廃止。

- **削除した環境変数**: `CHANNEL_CONFIG_STORAGE_TYPE`, `CHANNEL_CONTEXT_STORAGE_TYPE`, `USER_PROFILE_STORAGE_TYPE`
- **追加した環境変数**: `STORAGE_TYPE=local`（デフォルト: `"local"`）
- 変更ファイル: `config.py`, `utils/channel_config.py`, `memory/channel_context.py`, `memory/user_profile.py`, `.env.sample`, `README.md`, テスト4ファイル

### 2026/2: Phase 2B - ユーザープロファイル（相手を知る）

各ユーザーとの交流回数・関係性レベル・直近話題を記録し、初見 vs 常連で接し方を変える人間らしい振る舞いを実現。

- **`memory/user_profile.py`（新規）**: `UserProfile` dataclass + `UserProfileStore`
  - `interaction_count`, `mentioned_bot_count`, `channels_active`, `last_interaction`, `last_topic` を保持
  - `familiarity_level` プロパティ: interaction_count の閾値から自動算出（LLM不要）
    - `stranger`（0-5回）→ `acquaintance`（6-30回）→ `regular`（31-100回）→ `close`（101回〜）
  - `format_for_injection()`: interaction_count=0 のとき空文字（新規ユーザーはプロファイル注入しない）
  - ストレージ: local (`storage/user_profile.{user_id}.json`) / firestore (`user_profiles/{user_id}`)
  - アトミック書き込み（tempfile + os.replace）でデータロスを防止
  - シングルトン: `get_user_profile_store()`
- **`config.py`**: 環境変数4個追加
  - `USER_PROFILE_ENABLED`
  - `FAMILIARITY_THRESHOLD_ACQUAINTANCE`（デフォルト6）, `FAMILIARITY_THRESHOLD_REGULAR`（デフォルト31）, `FAMILIARITY_THRESHOLD_CLOSE`（デフォルト101）
- **`ai/conversation.py`**: `input_message()` に `user_profile: str = ""` パラメータ追加、context_section に注入
- **`bot/events.py`**: 3箇所に処理追加
  - `_handle_message()`: `MEMORY_ENABLED` かつメッセージ受信時に `record_message()` 呼び出し（チャンネルコンテキスト追加の直後）
  - `_handle_message()`: ボットメンション検出時に `record_bot_mention()` 呼び出し
  - `process_conversation()`: プロファイル取得・注入、応答後に `update_last_topic()` でチャンネルコンテキストの topic_keywords を同期
  - `_process_autonomous_response()`: 同様のプロファイル取得・注入・last_topic更新
- **`bot/discord_bot.py`**: `_cleanup_task`（15分ループ）に `persist_all()` を追加
- **`.env.sample`**: 新変数5個をコメント付きでドキュメント化

#### LLM注入フォーマット例

```
【Orz さんについて】
関係性: regular（45回のやりとり）
直近の話題: Rust, async, tokio
```

### 2026/2: Phase 2B - 自律応答とトリガー応答のコンテキスト統合

メンション等のトリガー応答と自律応答で、履歴とチャンネル文脈の共有を強化。

- **チャンネル単位の履歴管理**: `user_conversations` (ユーザーごと) を `channel_conversations` (チャンネルごと) に変更。複数人が参加するグループチャットの文脈を理解可能に。
- **履歴への発言者名追加**: AIが誰の発言かを区別できるよう、履歴に `{author_name}: {content}` の形式でインジェクト。
- **共有コンテキスト注入**: メンション応答時にも、短期記憶（Rawバッファ）とチャンネル要約をプロンプトに流し込むように統合。
- **自律応答のマルチターン化**: 自律応答（full_response）を1-shot生成から、Spheneクラスを使用したマルチターン履歴ベースに移行。

### 2026/2: Phase 2A - チャンネルコンテキスト + 応答多様性 + Judge拡張

「場の空気を読む」能力を追加。全機能opt-in（デフォルト無効）で後方互換性維持。

#### チャンネルコンテキスト（ローリング要約）
- `memory/channel_context.py`: `ChannelContext` dataclass + `ChannelContextStore`（memory/local/firestore ストレージ対応）
- `memory/summarizer.py`: `Summarizer` - メッセージ数 or 時間経過でLLM要約を非同期実行（`asyncio.ensure_future` で fire-and-forget）
- チャンネルの summary, mood, topic_keywords, active_users を管理
- `bot/discord_bot.py`: 15分クリーンアップタスクに時間ベース要約チェックを追加

#### 応答多様性（3段階）
- `react_only`: ランダム絵文字リアクション（👀😊👍🤔✨💡）
- `short_ack`: 軽量相槌生成（`generate_short_ack()`, `max_output_tokens=50`）
- `full_response`: 既存の自律応答（チャンネル要約注入対応追加）
- `bot/events.py`: `_dispatch_response()` で3タイプを統一ディスパッチ

#### Judge拡張（新スコアリングルール）
- `JudgeResult` に `response_type` フィールド追加（デフォルト `"full_response"` で後方互換）
- 新ルール: 2人会話(-20), ボット言及なし(-10), 高頻度(-10), 得意話題(+15), 沈黙後(+10), 会話減衰(-10〜-15)
- `_determine_response_type()`: `RESPONSE_DIVERSITY_ENABLED` 時にスコアに応じた応答タイプ選択

#### 新規環境変数（6個）
- `CHANNEL_CONTEXT_ENABLED`, `SUMMARIZE_EVERY_N_MESSAGES`, `SUMMARIZE_EVERY_N_MINUTES`, `SUMMARIZE_MODEL`
- `RESPONSE_DIVERSITY_ENABLED`

### 2026/2: ツール呼び出しループの改善

複数回のツール呼び出しでラウンド上限に達した際、集めた情報が無駄になり固定エラーメッセージが返される問題を修正。

- **`MAX_TOOL_CALL_ROUNDS`の環境変数化**: ハードコード(`3`)を廃止し、`config.py`で環境変数から注入（デフォルト: `5`）。12-factor原則に準拠。
- **ツールなし最終コール**: ループ上限到達後、ツールを渡さずに1回追加APIコールを実行。AIがこれまでに集めた全情報を使ってテキスト応答を生成できるようにした。
- 固定エラー文「処理が複雑すぎて諦めちゃった…」はAPI自体が失敗した場合の最終フォールバックとしてのみ残存。

### 2026/2: Vertex AI Native SDK (`google-genai`) 完全移行

OpenAI互換エンドポイントの制限（最新モデルの404エラー等）を回避し、Geminiの能力をフル活用するため、最新のGoogle Gen AI SDKへ移行。

- **SDK刷新**: `openai`ライブラリへの依存を排除（内部ロジック）。`google-genai` SDKを採用し、2026年6月の旧SDK削除予定に対応。
- **モデル指定**: `OPENAI_MODEL` → `GEMINI_MODEL` へ環境変数をリネーム。デフォルトを `google/gemini-2.5-flash` に設定。
- **Grounding**: Google検索連携（Grounding）をサポート。設定でON/OFF可能に。
- **マルチモーダル**: SDKネイティブな画像処理（`Part.from_bytes`）へ移行。
- **エラーハンドリング**: `google.api_core.exceptions` ベースの堅牢なエラー処理へ更新。
- **プロンプト**: `system_instruction` をネイティブに使用するように修正し、AIの性格維持能力を向上。

### 2026/2: 記憶機能（短期記憶 + 自律応答）

チャンネルの「参加者の一人」として自律的に会話に割り込める基盤を構築。

#### Phase 1: 短期記憶バッファ
- `memory/short_term.py`: `ChannelMessage` dataclass + `ChannelMessageBuffer`（dequeベースのリングバッファ）
- チャンネルごとにインメモリで直近メッセージを保持（`CHANNEL_BUFFER_SIZE`件、`CHANNEL_BUFFER_TTL_MINUTES`分TTL）
- `bot/events.py`: 全メッセージをバッファに追加（`MEMORY_ENABLED`フラグで制御）
- `bot/discord_bot.py`: 15分ごとのクリーンアップタスクにバッファ清掃を追加

#### Phase 2: 自律応答（ハイブリッドJudge）
- `memory/judge.py`: `RuleBasedJudge`によるスコアリング（メンション100, リプライ100, 名前呼び80, 疑問符+20, キーワード+15, クールダウン-50）
- `memory/llm_judge.py`: `LLMJudge`で曖昧ケース（`JUDGE_LLM_THRESHOLD_LOW`〜`HIGH`）のみLLM二次判定
- `ai/conversation.py`: `generate_contextual_response()` - チャンネルコンテキスト付き1-shot応答（既存Spheneクラスとは独立）
- `bot/events.py`: `_try_autonomous_response()` + `_process_autonomous_response()` - Judgeフロー実装

#### 新規環境変数（10個）
- `MEMORY_ENABLED`, `CHANNEL_BUFFER_SIZE`, `CHANNEL_BUFFER_TTL_MINUTES`
- `AUTONOMOUS_RESPONSE_ENABLED`, `JUDGE_SCORE_THRESHOLD`, `COOLDOWN_SECONDS`, `JUDGE_KEYWORDS`
- `LLM_JUDGE_ENABLED`, `JUDGE_MODEL`, `JUDGE_LLM_THRESHOLD_LOW`, `JUDGE_LLM_THRESHOLD_HIGH`

#### 後方互換性
全フラグのデフォルトは`false`/無効。既存のメンション/リプライ/名前呼びパスは一切変更なし。

### 2026/2: Vertex AI OpenAI互換API対応

Vertex AI固定構成。`AI_PROVIDER`環境変数は廃止済み。

- `ai/client.py`: シングルトン`client`を廃止、`get_client()`関数に統一。GCEのWorkload Identity認証（`google.auth.default()`）でトークンを自動取得・リフレッシュ。
- `config.py`: `VERTEX_AI_PROJECT_ID`, `VERTEX_AI_LOCATION`環境変数で設定。
- `ai/conversation.py`, `utils/text_utils.py`: クライアント参照を`get_client()`に変更。
- `pyproject.toml`: `google-auth`を明示的依存に追加。
- OpenAI互換APIのため、`tools.py`のツール定義やAPIコールパラメータは変更不要。

### 2026/2: S3廃止 + Firestore移行
AWS依存（boto3）を完全削除し、GCPベース（google-cloud-firestore）に一本化。
- システムプロンプト: S3/ローカル切り替え → ローカルのみ（k8s configmapマウント前提）
- チャンネル設定: S3 → Firestore（開発環境はローカルファイル維持）
- 削除: `utils/aws_clients.py`, `utils/s3_utils.py`, `PROMPT_STORAGE_TYPE`, `S3_*`環境変数
- 追加: `utils/firestore_client.py`, `FIRESTORE_COLLECTION_NAME`環境変数
- マイグレーションスクリプト: `scripts/migrate_s3_to_firestore.py`

### 2026/2: uv移行
requirements.txt/requirements-dev.txt → pyproject.toml + uv.lock。pytest.ini → pyproject.toml統合。Dockerfile・CI・run_tests.shをuv対応に更新。

### 2026/2: Discord Heartbeat Blocking修正
`bot/events.py`の`process_conversation()`と`utils/text_utils.py`の`translate_text()`で`asyncio.to_thread()`を使用し、同期ブロッキング呼び出しをスレッドプールに退避。フルasync化（AsyncOpenAI移行）は中期改善候補。

### 2026/2: XIVAPI v2連携の大幅拡張
`search_item`に加えて、以下の検索機能を追加。
- `search_action`: アクション（スキル）検索。説明文取得のために2段階リクエスト（search → sheet/Action/{id}）を実装。
- `search_recipe`: 製作レシピ検索。クラフタージョブ絞り込み、必要素材一覧の取得に対応。
- `search_game_content`: クエスト、アチーブメント、FATE、マウント、ミニオン、ステータスの汎用検索。
- DQL（Data Query Language）の最適化: 日本語検索時に `Name@ja~"query"` を使用するように改善。
- 共通ヘルパーの抽出: クエリ構築、API実行、エラーレスポンス作成の共通化。

## Key Decisions

| 日付 | 決定 | 理由 |
|------|------|------|
| 2026/3 | `ENABLE_GOOGLE_SEARCH_GROUNDING` とfunction calling(XIVAPI等)を排他利用 | Vertex AI `generateContent` APIの制約: `google_search` と `function_declarations` は同一リクエストに混在不可。Live API移行で両立可能 (issue #94) |
| 2026/2 | 記憶機能: ハイブリッドJudge方式 | ルールベースでLLMコールを最小化しつつ、曖昧ケースはLLMで精度向上 |
| 2026/2 | 記憶機能: 既存Spheneクラスとは独立した1-shot応答 | 既存の会話管理を壊さない。自律応答は会話履歴不要 |
| 2026/2 | S3廃止→Firestore移行 | k8sデプロイ方針変更に伴いGCPに一本化 |
| 2026/2 | システムプロンプトはローカルのみ | k8s configmapマウントで十分 |
| 2026/2 | `asyncio.to_thread()`で最小修正 | 2ファイル10行で全ブロッキングポイントをカバー。フルasync化は中期候補 |
| 2026/2 | XIVAPI全パラメータにデフォルト値 | `func(**arguments)`動的呼び出しとの後方互換性維持 |
| 2026/2 | Vertex AI固定化 | GCP一本化方針。Workload Identity認証でAPIキー管理不要。`AI_PROVIDER`環境変数は廃止 |

## Open Issues

1. **API制限**: 高負荷時のレート制限対応（基本リトライは実装済み）
2. **コスト最適化**: モデル選択、プロンプト最適化、キャッシング
3. **AsyncOpenAI移行**: フルasync化（中期候補）
4. **Firestore Native Vector Search**: `find_nearest()` を使ったベクトル検索のインフラ層への移譲（現状はin-memoryコサイン類似度）
