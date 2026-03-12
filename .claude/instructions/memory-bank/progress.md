---
applyTo: "**"
---
# Progress

## Completed Features

- **記憶機能 Phase 3B - Vertex AI Embeddings + ハイブリッド検索 (issue #77, #78)**:
  - `Fact.embedding` フィールド追加、`_cosine_similarity()` ヘルパー、`search()` にハイブリッドスコアリング（コサインは `max(0, cosine)` クリッピング）
  - `generate_embedding()` 追加（失敗時 `None` でJaccardフォールバック）
  - `_apply_facts()` を async化、`asyncio.gather()` でEmbedding並列生成
  - 新規環境変数3個: `EMBEDDING_MODEL`, `VECTOR_SEARCH_ENABLED`, `HYBRID_ALPHA`
  - `VECTOR_SEARCH_ENABLED=false`（デフォルト）で後方互換性維持
- **リアクション機能の独立制御 (issue #97)**:
  - `JudgeResult.should_react` / `reaction_emojis` フィールドで返信とリアクションを独立管理
  - `REACTION_ENABLED` / `JUDGE_REACT_THRESHOLD` 環境変数でしきい値チューニング可能
  - LLM Judge が文脈に合う絵文字（最大2個）を選択して返すように拡張
  - `asyncio.create_task` によるリアクション先行実行（LLM生成を待たない）
  - `LLMJudge.evaluate()` 戻り値を 4-tuple に変更（破壊的変更、全呼び出し元を更新済み）
- **記憶システム「リビングメモリー (Living Memory)」**:
  - `docs/living-memory.md`: 記憶の3層構造（短期・中期・長期）とライフサイクルを定義。
- **記憶機能 Phase 3A（反省会 + ファクトストア + 自発的会話）**:
  - `memory/fact_store.py`: `Fact` dataclass + `FactStore`（Jaccard類似度 × 指数減衰スコアリング、local/Firestore永続化）
  - `memory/reflection.py`: `ReflectionEngine`（LLMによるファクト抽出、fire-and-forget非同期実行）
  - `memory/short_term.py`: `get_active_channel_ids`, `get_last_message_time`, `count_messages_since_reflection`, `mark_reflected` 追加
  - `ai/conversation.py`: `relevant_facts` パラメータ追加（user_profile の後に context_section へ注入）
  - `bot/events.py`: ファクト検索・注入、沈黙後自発会話（`_try_proactive_conversation`, `_dispatch_proactive_message`）、バッファ量ベース反省会トリガー
  - `bot/discord_bot.py`: 沈黙ベース反省会チェック + ファクトストア永続化
  - 新規環境変数11個: `REFLECTION_ENABLED/LULL_MINUTES/MIN_MESSAGES/MAX_BUFFER_MESSAGES/MODEL`, `FACT_STORE_MAX_FACTS_PER_CHANNEL`, `FACT_DECAY_HALF_LIFE_DAYS`, `FACT_USER_BOOST_FACTOR`, `PROACTIVE_CONVERSATION_ENABLED`, `PROACTIVE_SILENCE_MINUTES`, `FIRESTORE_COLLECTION_FACTS`
- **Phase 3A コードレビュー対応**: `extract_keywords` 公開化、ブースト係数環境変数化、型アノテーション修正、冗長インポート削除、`_cleanup_task` ブロック統合
- **コードレビュー Medium/Low 課題の一括対応**:
  - `utils/file_utils.py` 新規作成（`atomic_write_json` 共通化）
  - `ai/api.py` 新規作成（API レイヤーを `ai/conversation.py` から分離）
  - `judge.evaluate()` から常時 False パラメータ3個削除
  - `process_conversation` / `_process_autonomous_response` の共通ロジックを4ヘルパーに抽出
  - フィーチャーフラグ依存チェックを `config.py` 起動時バリデーションに追加
  - デッドコード削除（`generate_contextual_response`, ローカル `truncate_text`）
- **ストレージタイプ設定の統合**: `CHANNEL_CONFIG_STORAGE_TYPE`・`CHANNEL_CONTEXT_STORAGE_TYPE`・`USER_PROFILE_STORAGE_TYPE` を `STORAGE_TYPE` 1変数に統合。`memory` オプション廃止。
- **Vertex AI Native SDK (`google-genai`) 移行**: OpenAI互換APIを廃止し、最新SDKへ完全移行（Gemini 3/2.5対応、Grounding対応）
- **記憶機能 Phase 1**: 短期記憶バッファ（ChannelMessageBuffer、dequeリングバッファ）
- **記憶機能 Phase 2**: 自律応答（ハイブリッドJudge: RuleBasedJudge + LLMJudge）
- **記憶機能 Phase 2A**: チャンネルコンテキスト（ローリング要約）+ 応答多様性（3段階）+ Judge拡張（会話フロー考慮）
- **記憶機能 Phase 2B（コンテキスト統合）**: チャンネル単位履歴 + メンション/自律応答の共有コンテキスト注入
- **記憶機能 Phase 2B（ユーザープロファイル）**: 交流回数・関係性レベル・直近話題の記録と応答生成への注入
  - `UserProfile` dataclass + `UserProfileStore`（local/firestore）
  - `familiarity_level`（stranger/acquaintance/regular/close）閾値ベース自動算出
  - `last_topic`: チャンネルコンテキストの topic_keywords を応答後に同期
  - `input_message()` に `user_profile` パラメータ追加
  - 15分ごとの定期永続化
- S3廃止 + Firestore移行: AWS依存完全削除、チャンネル設定をFirestoreに移行
- uv移行: pyproject.toml + uv.lock による依存管理、CI/Dockerfileのuv対応
- Discord応答（メンション、名前呼び、リプライ）、スラッシュコマンド
- Gemini-2.5-flash対話、会話履歴管理、マルチモーダル（画像）
- ツール呼び出しループ改善: `MAX_TOOL_CALL_ROUNDS`環境変数化（デフォルト5）+ ツールなし最終コール追加
- Function Calling → XIVAPI v2検索（アイテム・アクション・レシピ・クエスト等、詳細フィルタ対応）
- 翻訳（国旗リアクション: US/JP）
- チャンネル管理（全体/限定モード、追加/削除）
- ストレージ: ローカル/Firestore選択
- デプロイ: ローカル/Docker/Kubernetes
- PRテンプレート整備

## TODO

### Short-term
- 統合テストのSDK対応

### Mid-term
- チャンネル固有プロンプト
- 使用統計・モニタリング
- CI/CD強化
- AsyncOpenAI移行（フルasync化）
