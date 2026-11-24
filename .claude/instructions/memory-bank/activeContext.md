---
applyTo: "**"
---
# Active Context

## v1.0.0+ Current State (2026/11)

### 品質指標
- テスト: 1539件全パス
- カバレッジ: 96%
- mypy: 124ファイル no issues

### 主要フィーチャーフラグ（2グループ）

| フラグ | デフォルト | 内容 |
|-------|----------|------|
| `VANGUARD_ENABLED` | true | 自律応答・LLM Judge・応答多様性・リアクション |
| `LIVING_MEMORY_ENABLED` | true | チャンネルコンテキスト・ユーザープロファイル・反省会 |

旧8フラグ（`AUTONOMOUS_RESPONSE_ENABLED`, `LLM_JUDGE_ENABLED`, `RESPONSE_DIVERSITY_ENABLED`, `REACTION_ENABLED`, `CHANNEL_CONTEXT_ENABLED`, `USER_PROFILE_ENABLED`, `USER_PROFILE_TAGS_ENABLED`, `REFLECTION_ENABLED`）は廃止済み。
廃止済みの環境変数は `config.DEPRECATED_ENV_VARS` に登録しており、設定されていると起動時に移行先付きで WARNING を出す（新たに廃止する変数はここに追加する）。

### 記憶システム「リビングメモリー (Living Memory)」

3層構造で会話の文脈を多層的に管理。仕様は `docs/living-memory.md`、自律応答の仕様は `docs/vanguard.md` を参照。

| レイヤー | ファイル | 役割 |
|---------|---------|------|
| 短期 | `short_term.py` | チャンネルバッファ（deque, TTL, 反省会チェックポイント） |
| 中期 | `channel_context.py`, `summarizer.py` | ローリング要約（mood, topic_keywords, open_topics）＋自発会話用の時刻（最後の人間・自分の発言、前回の自発会話・前回の facts での自発会話）と言及済みの話題 id・使用済みの fact_id |
| 自発 | `proactive.py` | 自発会話（タイマー判定・話題の選定〔未解決の話題 > shareable facts〕・生成・送信。`PROACTIVE_ENABLED`） |
| 長期 | `user_profile.py` | ユーザー関係性（stranger→close, last_topic）。ギルド単位（guild_id, user_id） |
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
- `PROACTIVE_REGISTRY_COLLECTION`: 自発会話の担当インスタンス登録簿の Firestore コレクション（デフォルト: `proactive_channel_registry`。`FIRESTORE_NAMESPACE` を付けない共有コレクション）
- `PROACTIVE_REGISTRY_FILE`: `STORAGE_TYPE=local` 時の登録簿ファイル（デフォルト: `{LOCAL_STORAGE_DIR}/proactive_channel_registry.json`）
- `PROACTIVE_ENABLED`: 自発会話（デフォルト: false。`LIVING_MEMORY_ENABLED=true` が必要、起動時に検証）
- `PROACTIVE_CHECK_INTERVAL_MINUTES` / `PROACTIVE_MIN_SILENCE_MINUTES` / `PROACTIVE_MAX_SILENCE_HOURS` / `PROACTIVE_COOLDOWN_HOURS` / `PROACTIVE_FOLLOW_UP_WINDOW_HOURS`: 判定間隔・沈黙の下限/上限・クールダウン・follow_up のウィンドウ（デフォルト: 10分 / 120分 / 24時間 / 24時間 / 24時間）
- `PROACTIVE_QUIET_HOURS` / `PROACTIVE_TIMEZONE`: 静音時間帯（デフォルト: `0-8`、開始を含み終了を含まない、日またぎ可）とそのタイムゾーン（デフォルト: `Asia/Tokyo`）

**AI制御**
- `MAX_TOOL_CALL_ROUNDS`: ツール呼び出し最大ラウンド数（デフォルト: 15）
- `MAX_TOOL_RESULT_CHARS`: ツール結果1件あたりの最大文字数（JSON化後、デフォルト: 10000）
- `MENTION_RATE_LIMIT_PER_USER` / `MENTION_RATE_LIMIT_PER_CHANNEL` / `MENTION_RATE_LIMIT_WINDOW_SECONDS`: 呼びかけのレート制限（デフォルト: 5 / 20 回 / 60秒、0で無効）
- `TRANSLATION_DEDUP_SECONDS`: 国旗リアクション翻訳の重複抑止期間（デフォルト: 3600）
- `TRANSLATION_RATE_LIMIT_PER_USER` / `TRANSLATION_RATE_LIMIT_PER_CHANNEL` / `TRANSLATION_RATE_LIMIT_WINDOW_SECONDS`: 国旗リアクション翻訳のレート制限（リアクションしたユーザー単位、デフォルト: 5 / 15 回 / 60秒、0で無効）
- `REACTION_ERROR_NOTIFY_COOLDOWN_SECONDS`: リアクション処理エラーのチャンネル通知の最短間隔（デフォルト: 300）
- `GENAI_REQUEST_TIMEOUT_SECONDS`: Gen AI API 1リクエストのタイムアウト秒（デフォルト: 300。混雑時は長く待つと正確な応答が返るため長め）
- `GENAI_MAIN_MAX_ATTEMPTS` / `GENAI_MAIN_TIMEOUT_RETRIES` / `GENAI_MAIN_TOTAL_TIMEOUT_SECONDS`: 会話応答・要約・反省会のリトライ設定（デフォルト: 5回 / タイムアウト再試行1回 / 全体600秒。会話応答はツールループ全体で予算を共有）
- `GENAI_LIGHT_REQUEST_TIMEOUT_SECONDS` / `GENAI_LIGHT_MAX_ATTEMPTS` / `GENAI_LIGHT_TIMEOUT_RETRIES` / `GENAI_LIGHT_TOTAL_TIMEOUT_SECONDS`: Router・LLM Judge・相槌のリトライ設定（デフォルト: 30秒 / 2回 / 0回 / 45秒）
- `GENAI_MIN_REQUEST_TIMEOUT_SECONDS`: 上限時刻までの残り時間がこの秒数未満なら新たなリクエストを送らず打ち切る（デフォルト: 5）
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
- `JUDGE_REACT_THRESHOLD`（リアクションの有効/無効は `VANGUARD_ENABLED` に統合済み）

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
| 自発会話の担当は1チャンネル1インスタンス（#104 PR2、`utils/proactive_registry.py`） | 複数インスタンスが同じチャンネルで同時に話しかける問題を防ぐ。登録簿はインスタンス間で共有するため Firestore では `FIRESTORE_NAMESPACE` を付けない（`get_collection_name` を通さない）。登録・削除は transaction（local は flock）。ON は claim → 設定保存で、保存失敗時は今回新規に claim した場合だけ release（元から担当だった登録は消さない）。OFF は設定削除 → release |
| 自発会話の沈黙判定は `ChannelContext` の時刻で行う（#104 PR3） | チャンネルバッファは TTL（30分）で消えるため、2時間の沈黙を判定する時点では空になっている。`last_human_message_at` / `last_self_message_at` を永続化して再起動後も判定し、None（不明）なら送らない。永続化は要約時・終了時だけなので、送る前に Discord の直近履歴でも「最後が自分でない・沈黙している」を確認する |
| 自発会話の facts は「今触れられる未解決の話題がない」ときだけ使う（#104 PR4） | 優先順位は未解決の話題 > facts。`follow_up_after` 待ちの話題があっても facts は止めない。facts は沈黙の上下限に従い（上限無視は適用しない）、`PROACTIVE_FACT_COOLDOWN_HOURS`（default 72）と合算の `PROACTIVE_COOLDOWN_HOURS` の両方を適用。使用済み `fact_id` は `ChannelContext.used_fact_ids`（新しい順に200件）に記録して再利用しない。fact 本文も `<shared_fact>` でエスケープして囲み、記憶の仕組みには触れさせない |
| 旧 8 フラグ → 2 グループフラグ（issue #108） | 設定の複雑さを削減、デフォルト有効化 |
| Gen AI タイムアウトは長め（300秒） | 混雑時は長時間待つと正確な応答が返ることが多い。早期打ち切りより正確さを優先 |
| チャンネル設定の読み込み失敗時は保存拒否＋非キャッシュ＋発言不可（fail-closed） | 一時障害でデフォルト設定が本番データを上書きするのを防ぐ。デフォルトは全体モードのため、判定に使うと限定モードのギルドで全チャンネルに発言してしまう（#130） |
| 記憶ストアの読み込みエラーは `StorageLoadError`（`memory/errors.py`）で「未存在」と区別 | 空データで「ロード済み」になり、次の保存で既存のファクト・プロファイル・要約を上書きしていた（#131）。エラー時は非キャッシュの一時データを返し、次回アクセスで再読み込み。未ロードのものは保存しない（ファクトは dirty のまま保留し、ロード成功時に既存とマージ）。失敗したキーは `STORAGE_LOAD_BACKOFF_*` でバックオフし、破損データ等の恒久的な失敗でメッセージごとに I/O・traceback ログが出続けるのを防ぐ |
| チャンネル設定の読み込み失敗中はスラッシュコマンドで表示・変更しない | デフォルト値（全体モード）を表示すると、実際は発言停止中なのに表示と食い違う |
| コマンド登録・同期は `setup_hook` | `on_ready` は再接続のたびに発火するため |
| 反省会は前回チェックポイント以降の差分のみ処理 | 同一メッセージの重複抽出を防ぐ。チェックポイントは処理メッセージの最大タイムスタンプ（LLM実行中の新着を取りこぼさない） |
| 反省会LLM出力は発言者照合＋サニタイズ後に保存 | `user_id` は会話ログの人間発言者のみ許可。文字列は型・長さ検証し改行/制御文字を除去（`memory/sanitize.py`）。プロンプト再注入による間接インジェクション対策 |
| ユーザープロファイルはギルド単位で分離 | 別サーバーで得た事実・性格メモが漏れるのを防ぐ。旧 user_id 単位のデータからはカウンタのみ引き継ぎ（内容は他ギルド由来の可能性があるため破棄） |
| ストレージ同期I/Oは `asyncio.to_thread` でイベントループ外へ | Firestore 遅延で bot 全体が止まるのを防ぐ。記憶系は `_prefetch_memory` でキャッシュを先に温め、以降の同期呼び出しはキャッシュヒットさせる。各ストアは `threading.Lock` で保護（読み込みはロック外・登録は setdefault で先着優先） |
| system_instruction のコンテキストはタグ＋エスケープ＋「データであり指示ではない」注記 | 他ユーザーの発言・LLM生成の記憶による間接プロンプトインジェクション対策（`ai/conversation.py` の `build_context_section`）。発言者名も改行・制御文字を除去 |
| リトライ判定は例外の型とステータスコードのみ | 文字列一致は誤検知・見逃しが多い。408/429/5xx・httpx.TransportError・ConnectionError・TimeoutError をリトライ |
| リトライ予算は用途別（`RetryPolicy`）＋全体の上限時刻 | チャンネルロックの長時間保持を防ぐ。タイムアウト系（408/504・httpx.TimeoutException・TimeoutError・DeadlineExceeded）の再試行回数を別枠で制限し、上限時刻までの残り時間でリクエスト単位のタイムアウトも絞る。Router・Judge・相槌は `light_retry_policy()` |
| 完了した過去ターンはツール中間データ・画像を除去 | ツール結果の生JSONや画像バイトが30分間毎リクエスト再送されるのを防ぐ。直近ターンは追加質問に答えられるよう保持し、ツール結果1件も `MAX_TOOL_RESULT_CHARS` で切り詰め |
| function_response は function_call と1対1・id を返す | APIは同数の応答を要求する。名前なし・未知の関数もスキップせずエラー応答を返し、並列呼び出しのため `call.id` をそのまま返す |
| XIVAPI の DQL 文字列は引用符・バックスラッシュ・制御文字を除去 | XIVAPI v2 のクエリ言語に文字列エスケープ構文が定義されていないため。LLM由来の数値も `int` に正規化してから埋め込む |
| XIVAPI の httpx.Client はプロセス共有 | 接続・TLSセッションを再利用（action 検索は1回で最大6リクエスト）。`httpx.Client` はスレッドセーフ。終了時に `close_http_client()` |
| 呼びかけのレート制限はユーザー（ギルド単位）とチャンネルの2段 | 1回の呼びかけで Router＋最大16回の生成＋embedding が走るため。両方に空きがある時だけ枠を消費し、超過時は ⏳ リアクションのみ（状態はインメモリ。複数レプリカ間では共有しない） |
| 翻訳は (メッセージID, 言語) を一定時間1回に制限 | 複数ユーザーの同じ国旗・付け直しで LLM 呼び出しと返信が重複するのを防ぐ。翻訳中から記録し、失敗時は記録を外して再試行可能にする |
| 要約・反省会のLLM失敗は指数バックオフ（`memory/backoff.py`） | 失敗するとチェックポイント・カウンタが進まず、メッセージ受信のたびに再実行してAPIを叩き続けていたため。反省会は `REFLECTION_MAX_FAILURES` 回連続失敗で対象メッセージを破棄（同じバッチを永遠に再送しない）。バックオフ状態はインメモリ |
| 反省会のプロファイル更新はチェックポイント確定時のみ | 再試行のたびに同じ会話でプロファイルを更新しないため |
| 記憶ストアの定期永続化は dirty なキーのみ | 15分ごとに全プロファイル・全チャンネルを書き込んでいた（Firestore の書き込み課金）。検索ヒットによる `access_count` 更新も dirty 扱い。失敗したキーは dirty に戻して再試行 |
| SIGTERM はループのシグナルハンドラで受け、永続化してから `bot.close()` | Python 既定の SIGTERM は即時終了で後始末が走らず、コンテナ再起動のたびに最大15分ぶんの dirty な記憶が消えていた（#132）。`asyncio.run` は終了時に既定 executor のスレッド終了を最大300秒待つため、`run` の `finally` だけでは LLM 呼び出し中に k8s の猶予期間（30秒）を超えて SIGKILL される。そのため `setup_hook` で `loop.add_signal_handler` を登録し、ループ内で同期的に `persist_all`（`to_thread` は executor が LLM 呼び出しで埋まると後ろに並ぶので使わない）。`finally` は SIGINT・例外向けのフォールバック（先頭で SIGTERM を SIG_IGN）。`bot.setup_hook` は `setup_events` がスラッシュコマンドの登録・同期用に設定済みなので、上書きせず合成すること（上書きするとコマンドが登録されなくなる。モックのテストでは気づけない）。チャンネルコンテキストも `dirty` フラグで変更分だけ書き込む |
| fire-and-forget タスクは `utils/background_tasks.track_background_task` で保持 | イベントループはタスクを弱参照でしか持たず、要約・反省会・リアクションが実行途中に GC されうる（#132）。完了時に集合から外し、例外はタスク名付きでログに残す。新たに `create_task` で投げっぱなしにするタスクは必ずこれで包む |
| Firestore のサイズは型ごとの保存規則で見積もる（`utils/firestore_client.estimate_document_size`） | JSON長で見積もると浮動小数（embedding）を約2.5倍に過大評価し、収まるファクトまで削ってしまうため |
| ファクトアーカイブに embedding を保存しない | アーカイブは読み戻されず、embedding は `EMBEDDING_MODEL` 依存で移行時には再生成が必要。容量の大半を占めていた |
| スラッシュコマンド・ビューのコールバックは I/O 前に defer | 設定の読み書き（Firestore 最大3往復）で Discord の3秒応答期限を超えると 10062 Unknown interaction になるため。権限エラー・サーバー外実行など I/O なしで即答できるものは defer しない。返信は `_reply()` で defer 済みなら followup に切り替える |
| Docker イメージは `/app/storage` を実行ユーザー所有で作成し VOLUME 宣言 | `STORAGE_TYPE=local` の書き込み先が存在せず root 所有の `/app` 配下で PermissionError になり、コンテナ再作成でデータも消えていたため |
| 記憶ストアのキャッシュは LRU で上限管理（`memory/cache_eviction.LruTracker`） | `_profiles` / `_facts` / `_contexts` が削除されずプロセス終了まで増え続けていたため（#140）。定期タスクの `_prune_memory_caches` で上限超過分を古い順に追い出す。dirty・保存中・未マージのファクトあり・要約カウント待ち・`MEMORY_CACHE_MIN_IDLE_SECONDS` 以内にアクセスされたものは追い出さない（上限は目安）。追い出したものは次回アクセスで永続化先から読み直す。保存ロックも一緒に破棄（`KeyedLock.discard`）。Judge の応答時刻・バックオフ状態は TTL で掃除 |
| 環境変数の数値・真偽値は `config._env_int` / `_env_float` / `_env_bool` で読む | 解釈できない値で変数名の分からない ValueError になっていたため。真偽値は true/1/yes/on（大文字小文字無視）。不正値は変数名入りのエラーで起動を止める |
| 管理コマンドの応答は ephemeral | チャンネル一覧などが全員に見えていた。`_defer` / `_reply` が常に ephemeral。確認ボタンは押した時点で無効化して `stop()` |
| エラー通知はボットが話しかけられた場合のみ | 無関係なメッセージへのエラー投稿の連発を防ぐ。記憶の記録失敗は応答を止めない（`_record_memory` で隔離） |

## Open Issues

1. **API 制限**: 高負荷時のレート制限対応（基本リトライは実装済み）
2. **コスト最適化**: モデル選択、プロンプト最適化、キャッシング
3. **フル async 化**: google-genai `client.aio` への移行（中期候補）
4. **Firestore Native Vector Search**: `find_nearest()` を使ったベクトル検索（現状は in-memory コサイン類似度）
5. **自発会話機能**: タイマーベースへの再設計（issue #104 OPEN）。PR1（open_topics）・PR2（opt-in と担当インスタンスの登録簿）・PR3（スケジューラ・生成・送信、`PROACTIVE_ENABLED`）・PR4（facts ベースの話題振り）で完了
6. **2026/11 全体レビュー（2回目）**: issue #130〜#141 に登録。#130・#131・#140 ほか対応済み
7. ~~**2026/11 コードレビュー残課題**~~: 全件対応済み（PR #124〜#129）。Router プリフィルタは対応前から実装済みだった。残る検討事項: 7文字以下の短文（例: 「ガンブレイカー」）もプリフィルタで none になり、ツールが使われない
8. **EMBEDDING_MODEL**: `text-embedding-004` の提供状況を要確認。移行すると次元が変わり既存ベクトルと非互換になるため要マイグレーション検討。高次元モデル（例: 3072次元）に移行すると1チャンネル1ドキュメントのファクトが1MiB上限に当たるため、移行時にサブコレクション（`facts/{channel_id}/items/{fact_id}`）化もあわせて検討する（現状は上限超過分を関連度の低い順に保存対象外にするガードのみ）
