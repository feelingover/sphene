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
- API レイヤー分離（`ai/api.py`）

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

## TODO

### Short-term
- 統合テストのSDK対応

### Mid-term
- チャンネル固有プロンプト
- 使用統計・モニタリング
- CI/CD強化
- AsyncOpenAI移行（フルasync化）
- 自発会話機能 タイマーベースへの再設計（issue #104）
- Firestore Native Vector Search（`find_nearest()`）
