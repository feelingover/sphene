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
- ツール呼び出しの堅牢化（2026/11）: ツールスキーマの enum が変換時に落ちていた不具合を修正（`craft_type` に enum 追加、`search_game_content` にレベル範囲を公開）、function_response を function_call と1対1にし id を返却・非dict結果を包む、ツール結果の文字数上限（`MAX_TOOL_RESULT_CHARS`）、完了した過去ターンからツール中間データと画像を除去
- XIVAPI クライアントの強化（2026/11）: DQL 文字列から引用符・バックスラッシュ・制御文字を除去してクエリ注入を防止、レベル値を整数に正規化（`600.0` 等）、httpx.Client をプロセス共有して接続を再利用
- Discord イベントのガード（2026/11）: LLM Judge 経由の react_only で二重リアクションになる不具合を修正（リアクション済みならクールダウン記録のみ）、国旗リアクション翻訳の重複抑止（`TRANSLATION_DEDUP_SECONDS`）、呼びかけのレート制限（`utils/rate_limit.py`、ユーザー/チャンネル単位）
- 記憶系LLMの耐障害性（2026/11）: 要約・反省会の失敗時に指数バックオフ（`memory/backoff.py`、`MEMORY_LLM_BACKOFF_*`）、反省会は `REFLECTION_MAX_FAILURES` 回連続失敗で対象メッセージを破棄・全件不正も失敗扱い・プロファイル更新はチェックポイント確定時のみ、要約JSONの型・長さ検証とサニタイズ
- 記憶ストアの永続化コスト削減（2026/11）: ファクトストア・ユーザープロファイルの `persist_all` を dirty なキーのみに限定（失敗時は再試行）、Firestore ドキュメントサイズの見積もり（`estimate_document_size`）とファクト／アーカイブの1MiB上限ガード、アーカイブから embedding を除去
- 運用系の修正（2026/11）: スラッシュコマンド・ビューのコールバックで I/O 前に `defer(thinking=True)`（3秒の応答期限切れ対策）、Dockerfile で `/app/storage` を実行ユーザー所有で作成し `VOLUME` 宣言・README にボリュームマウント手順
- Gen AI API のリトライ予算の制限（2026/11、#133）: `RetryPolicy` でメイン（会話応答・要約・反省会）と軽量（Router・Judge・相槌）のリトライ設定を分離、タイムアウト系の再試行回数を別枠で制限、ツールループ全体で上限時刻を共有しリクエスト単位のタイムアウトを残り時間で絞る

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
- リアクション先行実行（`asyncio.create_task` + `track_background_task`）
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
- 読み込み失敗時の安全側動作（2026/11, #130 #131）: チャンネル設定は fail-closed、記憶ストアは読み込みエラーを未存在と区別して既存データの上書きを防止。読み込み失敗はバックオフ（`STORAGE_LOAD_BACKOFF_*`）し、読み込み失敗中のスラッシュコマンドはその旨を返す
- 終了時の記憶永続化とバックグラウンドタスク参照の保持（2026/11, #132）: SIGTERM をループのシグナルハンドラで受け、executor 終了待ちより前に全記憶ストアを `persist_all`（チャンネルコンテキストは dirty のみ）、要約・反省会・リアクションのタスクを `utils/background_tasks.py` で強参照保持＋例外ログ
- 並行保存の後勝ち防止（2026/11, #135）: FactStore・UserProfileStore にキー単位の保存ロック（`utils/keyed_lock.py`）を導入し、スナップショット取得から書き込み完了まで保持。古いスナップショットの書き込みが新しいファクトを上書きして dirty も消える競合を解消
- 書き換えと書き出しの並行対策（2026/11, #147）: UserProfileStore の書き換えメソッドを `self._lock` 内で実行し、保存スナップショット（`UserProfile.snapshot()`）もロック内で取得。FactStore も保存・忘却クリーンアップで `Fact.snapshot()` をロック内で取り、`search` の参照頻度更新と混ざらないようにした
- プロファイル読み取りの一貫性（2026/11, #153）: `UserProfileStore.get_profile` / `get_cached_profile` はロック内で取った `UserProfile.snapshot()` を返すようにし、注入用の文字列化と書き換えが並行しても新旧の値が混ざらないようにした。書き換えが必要な `record_message` は内部の `_get_or_load_profile` で生のオブジェクトを使う
- LLMコンテキストのプロンプトインジェクション対策（2026/11, #136）: 直近会話は1発言1行に正規化し名前からロール表記・区切り記号を除去（`memory/sanitize.py` の `safe_author_name`）、翻訳は指示を `system_instruction` に分離し本文をエスケープした `<text>` タグで渡す、反省会の `source_user_ids` を会話参加者に限定
- 国旗リアクション翻訳の堅牢化（2026/11, #138）: `on_raw_reaction_add` に切り替えキャッシュ外メッセージは `fetch_message` で取得、翻訳にユーザー（リアクションした人）単位・チャンネル単位のレート制限（超過時 ⏳、翻訳済みメッセージは枠を消費しない）、リアクション処理エラーのチャンネル通知をクールダウン付きにし送信失敗をログに記録
- チャンネル設定保存の堅牢化（2026/11, #139）: 設定変更メソッドは保存失敗時に変更前の `config_data` へロールバック（`ChannelConfig._update_and_save`、インスタンス単位の RLock で変更〜保存〜ロールバックおよび再読み込みを直列化）、`atomic_write_json` は fsync・失敗時の一時ファイル削除・既存権限維持に対応（umask はプロセス全体を触らず os.open の mode で適用）、ローカル保存先を `LOCAL_STORAGE_DIR`（default: `storage`、`utils/file_utils.local_storage_path`）で指定可能に（チャンネル設定・記憶系すべて）
- Low優先度の修正まとめ（2026/11, #140）: 環境変数ヘルパー（`_env_bool`/`_env_int`/`_env_float`）、`LOG_FORMAT` の大文字小文字無視、管理コマンド応答の ephemeral 化と確認ボタンの無効化、画像取得の https 限定・リダイレクト禁止・ログURLの署名除去・mime 整形、XIVAPI の 0 フィルタで空クエリ送信を防止・レシピパース失敗のログ、LLM Judge の真偽値・絵文字パース修正、`_extract_text` の thought 除外、記憶ストアのキャッシュ LRU/TTL 追い出し、⏳ リアクションをメッセージごとに1回に
- CLAUDE.md規約違反の解消（2026/11, #141）: 60行超の関数を `_` プレフィックスのヘルパーへ分割（`_cleanup_task`, `_try_autonomous_response`, `_handle_message`, `translate_and_reply`, `call_genai_with_tools`, `input_message`, `search_item`, `evaluate`, `_apply_facts`, `_call_llm`, `search` ほか）、except内ログへ `exc_info=True` 付与、型ヒント補完（挙動変更なし）
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
