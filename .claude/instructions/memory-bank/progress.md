---
applyTo: "**"
---
# Progress

## v1.0.0 完成済み機能

### 基盤
- Discord接続・基本ボット機能（メンション、名前呼び、リプライ）
- スラッシュコマンド（reset, mode, channels, addlist/removelist/clearlist, reload_prompt, translation）
- 翻訳機能（国旗リアクション: 🇺🇸 / 🇯🇵）
- チャンネル管理（全体/限定モード、Firestore/ローカル選択）
- Vertex AI Native SDK (`google-genai`) 移行（OpenAI互換API廃止）
- Gemini 4 Hydrogen (`gemini-4-hydrogen`) へモデル移行・`VERTEX_AI_LOCATION` デフォルトを `global` に変更・未使用の `google-cloud-aiplatform` 依存を削除（2026/11）
- Google検索Grounding（`ENABLE_GOOGLE_SEARCH_GROUNDING`、function callingと排他）
- uv による依存管理（pyproject.toml + uv.lock）
- Docker / Kubernetes デプロイ対応

### AI会話
- Gemini（Vertex AI）によるマルチターン会話（チャンネル単位の履歴共有）
- マルチモーダル対応（画像処理）
- 会話タイムアウト（30分）・最大10ターン
- Router LLM による Grounding / Function Calling の動的切り替え
- Function Calling → XIVAPI v2 検索（アイテム・アクション・レシピ・クエスト・マウント・ミニオン等）
- ツール呼び出しループ改善（`MAX_TOOL_CALL_ROUNDS` 環境変数化、ツールなし最終コール）
- 応答失敗時の履歴ロールバック・ツール未宣言モード（none/grounding）および上限到達後の最終コールで返された function_call を実行せず破棄し、function_call を除去・function_response をテキスト化した履歴で1回再リクエスト（前置きテキストは採用しない）・`MAX_TOOL_CALL_ROUNDS` デフォルトを 5→15 に変更（2026/11）
- API レイヤー分離（`ai/api.py`）
- Thinkingレベルの用途別設定（`MAIN_THINKING_LEVEL` / `LIGHT_THINKING_LEVEL`）（2026/11）
- 応答生成中の「入力中...」インジケーター（`bot/events.py` の `_typing_indicator`。通常会話・自律応答・相槌・翻訳で表示）（2026/11）
- 高優先度レビュー対応（2026/11）: チャンネル設定読み込み失敗時の上書き防止、`allowed_mentions` で @everyone/ロールメンション抑止、Gen AI リクエストタイムアウト（`GENAI_REQUEST_TIMEOUT_SECONDS`）、スラッシュコマンド登録を `setup_hook` へ移動
- 反省会の重複抽出防止・プロファイル汚染対策（2026/11）: 前回以降の差分メッセージのみ反省会へ、`FactStore.add_fact` で重複排除、LLMの `user_id` を発言者と照合、抽出値のサニタイズ（`memory/sanitize.py`）
- ストレージI/Oの非同期化とプロファイルのギルド分離（2026/11）: Firestore 等の同期I/Oを `asyncio.to_thread` へ退避（チャンネル設定・記憶ストア・定期永続化）、ストアに `threading.Lock` を導入、ユーザープロファイルを (guild_id, user_id) 単位に分離し旧データはカウンタのみ移行
- プロンプトインジェクション対策・エラー処理・リトライ判定の改善（2026/11）: system_instruction のコンテキストをタグ＋エスケープ、スラッシュコマンドのエラーを固定文言＋followup 対応、話しかけられた時だけエラー通知、リトライ判定を型・ステータスコードベースに変更しタイムアウトもリトライ対象に
- ボット管理ロール宛てのメンション（`<@&id>`）を呼びかけとして検出、`<@!id>` 形式も質問文から除去（2026/11、実機テストで発見）

### リビングメモリー (Living Memory)
- 短期記憶: チャンネルバッファ（dequeリングバッファ、TTL管理）
- 中期記憶: チャンネルコンテキスト（ローリング要約、mood/topic_keywords/active_users）
- 長期記憶: ユーザープロファイル（交流回数・関係性レベル・直近話題）
- 長期記憶: ファクトストア（Jaccard×指数減衰スコアリング、local/Firestore永続化）
- 反省会エンジン（LLMによるファクト抽出、fire-and-forget非同期）
- ファクト忘却機能（参照頻度ブースト + 時間減衰クリーンアップ）
- ハイブリッド検索（Vertex AI Embeddings + Jaccard、`VECTOR_SEARCH_ENABLED`）
- `LIVING_MEMORY_ENABLED` 1フラグで全機能をデフォルト有効化

### VANGUARD（自律応答）
- ルールベースJudge（スコアリング + response_type決定 + should_react判定）
- LLM二次判定（曖昧スコア帯のみLLM呼び出し、絵文字選択）
- 応答多様性（リアクション / 相槌 / フル応答の3段階）
- リアクション先行実行（`asyncio.create_task`）
- チャンネルコンテキスト注入による応答品質向上
- 会話フロー分析（2人会話・高頻度・沈黙後・会話減衰の検出）
- `VANGUARD_ENABLED` 1フラグで全機能をデフォルト有効化

### コードクオリティ（v1.0.0 対応）
- 機能フラグを2グループフラグに統合（旧8フラグ廃止）
- `utils/file_utils.py` 新規作成（`atomic_write_json` 共通化）
- フィーチャーフラグ依存チェックを `config.py` 起動時バリデーション
- 共通ロジックを4ヘルパーに抽出（`_collect_ai_context`, `_get_or_reset_conversation`, `_send_chunks`, `_post_response_update`）
- Firestoreコレクション名のネームスペース化（`FIRESTORE_NAMESPACE`）
- ストレージタイプ設定の統合（`STORAGE_TYPE` 1変数）
- 自発会話機能削除（issue #104、タイマーベースへ再設計予定）
- セキュリティ・品質レビュー対応（Critical/High/Medium 15件）
- ログ・設定の整理（2026/11）: discord.py 独自ログハンドラを無効化して二重出力を解消、サードパーティロガー（discord/httpx/google 等）の最低レベルを設定、廃止済み環境変数の起動時警告を追加

## TODO

### Short-term
- 統合テストのSDK対応

### Mid-term
- チャンネル固有プロンプト
- 使用統計・モニタリング
- CI/CD強化
- フルasync化（google-genai `client.aio` 移行）
- 自発会話機能 タイマーベースへの再設計（issue #104）
- Firestore Native Vector Search（`find_nearest()`）
