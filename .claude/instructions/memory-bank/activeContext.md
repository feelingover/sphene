---
applyTo: "**"
---
# Active Context

## v1.0.0+ Current State (2026/11)

### 品質指標
- テスト: 740件全パス
- カバレッジ: 90%
- mypy: 76ファイル no issues

### 主要フィーチャーフラグ（2グループ）

| フラグ | デフォルト | 内容 |
|-------|----------|------|
| `VANGUARD_ENABLED` | true | 自律応答・LLM Judge・応答多様性・リアクション |
| `LIVING_MEMORY_ENABLED` | true | チャンネルコンテキスト・ユーザープロファイル・反省会 |

旧8フラグ（`AUTONOMOUS_RESPONSE_ENABLED`, `LLM_JUDGE_ENABLED`, `RESPONSE_DIVERSITY_ENABLED`, `REACTION_ENABLED`, `CHANNEL_CONTEXT_ENABLED`, `USER_PROFILE_ENABLED`, `USER_PROFILE_TAGS_ENABLED`, `REFLECTION_ENABLED`）は廃止済み。

### 記憶システム「リビングメモリー (Living Memory)」

3層構造で会話の文脈を多層的に管理。仕様は `docs/living-memory.md`、自律応答の仕様は `docs/vanguard.md` を参照。

| レイヤー | ファイル | 役割 |
|---------|---------|------|
| 短期 | `short_term.py` | チャンネルバッファ（deque, TTL, 反省会チェックポイント） |
| 中期 | `channel_context.py`, `summarizer.py` | ローリング要約（mood, topic_keywords） |
| 長期 | `user_profile.py` | ユーザー関係性（stranger→close, last_topic） |
| 長期 | `fact_store.py` | ファクトストア（Jaccard×decay, embedding対応, 忘却機能） |
| 思考 | `reflection.py` | 反省会エンジン（LLMファクト抽出, fire-and-forget） |

### 主要環境変数

**基本設定**
- `BOT_MODEL` / `BOT_LITE_MODEL`: 使用モデル（デフォルト: `google/gemini-4-hydrogen`）
- `VERTEX_AI_LOCATION`: Vertex AIリージョン（デフォルト: `global`。`asia-northeast1` は新しいモデルで404になる）
- `STORAGE_TYPE`: `local` | `firestore`（デフォルト: `local`）
- `FIRESTORE_NAMESPACE`: Firestoreコレクション名プレフィックス
- `BOT_NAME`: ボットの名前（デフォルト: `スフェーン`）
- `COMMAND_GROUP_NAME`: スラッシュコマンドプレフィックス（デフォルト: `INSTANCE_NAME`）

**AI制御**
- `MAX_TOOL_CALL_ROUNDS`: ツール呼び出し最大ラウンド数（デフォルト: 15）
- `GENAI_REQUEST_TIMEOUT_SECONDS`: Gen AI API 1リクエストのタイムアウト秒（デフォルト: 300。混雑時は長く待つと正確な応答が返るため長め）
- `MAIN_THINKING_LEVEL`: 会話応答・ツールループのThinkingレベル（デフォルト: 空 = モデルのデフォルト）
- `LIGHT_THINKING_LEVEL`: Router・Judge・相槌・要約・反省会・翻訳のThinkingレベル（デフォルト: `low`）。`ai/client.py` の `get_light_thinking_config()` 経由で渡す
- `ENABLE_GOOGLE_SEARCH_GROUNDING`: Google検索Grounding（function callingと排他）
- `EMBEDDING_MODEL`: Embedding生成モデル（デフォルト: `text-embedding-004`）
- `VECTOR_SEARCH_ENABLED`: ハイブリッド検索有効化（デフォルト: false）
- `HYBRID_ALPHA`: ベクトル/キーワードバランス係数（デフォルト: 0.5）

**ファクトストア**
- `FACT_STORE_MAX_FACTS_PER_CHANNEL`: 100
- `FACT_DECAY_HALF_LIFE_DAYS`: 30（指数減衰の半減期・日）
- `FACT_STORE_CLEANUP_THRESHOLD`: 0.05（忘却クリーンアップ閾値）
- `FACT_ACCESS_BOOST_WEIGHT`: 0.1（参照頻度ブースト係数）
- `FACT_STORE_ARCHIVE_ENABLED`: false（削除前アーカイブ）
- `FACT_DEDUP_SIMILARITY_THRESHOLD`: 0.95（ファクト重複判定のコサイン類似度閾値。正規化した本文の完全一致でも重複扱い）

**VANGUARD系**
- `JUDGE_SCORE_THRESHOLD`, `COOLDOWN_SECONDS`, `JUDGE_KEYWORDS`
- `JUDGE_LLM_THRESHOLD_LOW`, `JUDGE_LLM_THRESHOLD_HIGH`（要約・反省会は `BOT_MODEL`、LLM Judge は `BOT_LITE_MODEL`。`JUDGE_MODEL` などの専用モデル変数はない）
- `REACTION_ENABLED`, `JUDGE_REACT_THRESHOLD`

## Key Decisions

| 決定 | 理由 |
|------|------|
| Grounding と function calling は排他 | Vertex AI `generateContent` API の制約（同一リクエストに混在不可）。Live API 移行で両立可能（issue #94） |
| ハイブリッド Judge 方式 | ルールベースで LLM コールを最小化、曖昧ケースは LLM で精度向上 |
| チャンネル単位の会話履歴 | 複数ユーザーが参加するグループチャットの文脈を共有 |
| S3 廃止 → Firestore | GCP 一本化、k8s Workload Identity 認証で API キー管理不要 |
| システムプロンプトはローカルのみ | k8s configmap マウントで十分 |
| `asyncio.to_thread()` で最小修正 | フル async 化は中期候補（google-genai の `client.aio` 移行） |
| Vertex AI Native SDK (`google-genai`) | OpenAI 互換 API の制限を回避、Gemini 最新モデル対応 |
| 自発会話機能削除（issue #104） | マルチテナント競合・トリガー設計の根本見直し、タイマーベースへ再設計を継続検討 |
| 旧 8 フラグ → 2 グループフラグ（issue #108） | 設定の複雑さを削減、デフォルト有効化 |
| Gen AI タイムアウトは長め（300秒） | 混雑時は長時間待つと正確な応答が返ることが多い。早期打ち切りより正確さを優先 |
| チャンネル設定の読み込み失敗時は保存拒否＋非キャッシュ | 一時障害でデフォルト設定が本番データを上書きするのを防ぐ |
| コマンド登録・同期は `setup_hook` | `on_ready` は再接続のたびに発火するため |
| 反省会は前回チェックポイント以降の差分のみ処理 | 同一メッセージの重複抽出を防ぐ。チェックポイントは処理メッセージの最大タイムスタンプ（LLM実行中の新着を取りこぼさない） |
| 反省会LLM出力は発言者照合＋サニタイズ後に保存 | `user_id` は会話ログの人間発言者のみ許可。文字列は型・長さ検証し改行/制御文字を除去（`memory/sanitize.py`）。プロンプト再注入による間接インジェクション対策 |

## Open Issues

1. **API 制限**: 高負荷時のレート制限対応（基本リトライは実装済み）
2. **コスト最適化**: モデル選択、プロンプト最適化、キャッシング
3. **フル async 化**: google-genai `client.aio` への移行（中期候補）
4. **Firestore Native Vector Search**: `find_nearest()` を使ったベクトル検索（現状は in-memory コサイン類似度）
5. **自発会話機能**: タイマーベースへの再設計（issue #104 OPEN）
6. **2026/11 コードレビュー残課題**: プロファイルのギルド間漏洩、Firestore 同期I/Oのイベントループブロック、system_instruction へのチャンネル会話の未エスケープ注入、Router プリフィルタ（7文字以下で none）、リトライ判定の文字列一致、反省会LLM失敗時のバックオフなし
7. **EMBEDDING_MODEL**: `text-embedding-004` の提供状況を要確認。移行すると次元が変わり既存ベクトルと非互換になるため要マイグレーション検討
