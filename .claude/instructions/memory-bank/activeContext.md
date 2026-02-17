---
applyTo: "**"
---
# Active Context

## Current State (2026/2)

- 全テスト通過（423件）
- Vertex AI Native SDK (`google-genai`) への完全移行完了。OpenAI互換APIを廃止し、Gemini 3等の最新モデルに完全対応。
- 環境変数を `GEMINI_MODEL` 形式に統一、`OPENAI_API_KEY` を完全削除。
- Google検索Grounding機能のサポート開始（`ENABLE_GOOGLE_SEARCH_GROUNDING`）。
- Discord heartbeat blocking修正済み（`asyncio.to_thread()`）。
- 記憶機能（Phase 1 + Phase 2）実装済み。
- ツール呼び出しループの改善済み（上限の環境変数化 + ツールなし最終コール）。

## Recent Changes

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

#### 新規環境変数（7個）
- `CHANNEL_CONTEXT_ENABLED`, `CHANNEL_CONTEXT_STORAGE_TYPE`, `SUMMARIZE_EVERY_N_MESSAGES`, `SUMMARIZE_EVERY_N_MINUTES`, `SUMMARIZE_MODEL`
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

`AI_PROVIDER`環境変数（`openai`/`vertex_ai`）でプロバイダーを切り替え可能にした。

- `ai/client.py`: シングルトン`client`を廃止、`get_client()`関数に統一。Vertex AI選択時はGCEのWorkload Identity認証（`google.auth.default()`）でトークンを自動取得・リフレッシュ。
- `config.py`: `AI_PROVIDER`, `VERTEX_AI_PROJECT_ID`, `VERTEX_AI_LOCATION`環境変数を追加。
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
| 2026/2 | 記憶機能: ハイブリッドJudge方式 | ルールベースでLLMコールを最小化しつつ、曖昧ケースはLLMで精度向上 |
| 2026/2 | 記憶機能: 既存Spheneクラスとは独立した1-shot応答 | 既存の会話管理を壊さない。自律応答は会話履歴不要 |
| 2026/2 | S3廃止→Firestore移行 | k8sデプロイ方針変更に伴いGCPに一本化 |
| 2026/2 | システムプロンプトはローカルのみ | k8s configmapマウントで十分 |
| 2026/2 | `asyncio.to_thread()`で最小修正 | 2ファイル10行で全ブロッキングポイントをカバー。フルasync化は中期候補 |
| 2026/2 | XIVAPI全パラメータにデフォルト値 | `func(**arguments)`動的呼び出しとの後方互換性維持 |
| 2026/2 | Vertex AI OpenAI互換API対応 | GCP一本化方針。Workload Identity認証でAPIキー管理不要。`AI_PROVIDER`で切替可能 |

## Open Issues

1. **API制限**: 高負荷時のレート制限対応（基本リトライは実装済み）
2. **コスト最適化**: モデル選択、プロンプト最適化、キャッシング
3. **AsyncOpenAI移行**: フルasync化（中期候補）
4. **記憶機能 Phase 3+**: 中期記憶（Firestore保存）・長期記憶（ベクトル検索）は将来Phase
