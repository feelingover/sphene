# 記憶システム「リビングメモリー (Living Memory)」仕様

## 1. コンセプト

「リビングメモリー」は、ボットを単なるツールではなく、チャンネルの**参加者の一人**として振る舞わせるための多層的な記憶システム。
文脈（Context）を理解し、空気を読み、適切なタイミングで会話に割り込むことができる「人格」を支える基盤。

---

## 2. 記憶の3層構造

記憶は、その鮮度と重要度に応じて3つの層に分類される。

### ① 短期記憶 (Working Memory) - 現場の直感
直近のやり取りをそのまま保持する「短期のバッファ」。
- **役割:** 直近の文脈をLLMに伝え、自然な会話のキャッチボールを実現。
- **実装:** `memory/short_term.py` (ChannelMessageBuffer)
- **特徴:**
  - チャンネルごとのリングバッファ（デフォルト: 50件）。
  - TTLによる自動破棄（デフォルト: 30分）。
  - インメモリ（RAM）で高速に動作。
  - LLM に渡す直近会話（`名前[BOT]: 本文` の行形式）は、1発言を必ず1行に収める。本文の改行・制御文字はつぶし、名前は NFKC 正規化のうえ `[` `]` `【】` `:` などロール表記・区切りを偽装できる記号を除く（`memory/sanitize.py` の `safe_author_name`。要約・反省会・参加者一覧・会話履歴でも同じ正規化を通す）。本文に改行を入れたり表示名を `Foo[BOT]` にしたりして、他人やボットの発言を挿入することはできない（#136）

### ② 中期記憶 (Channel Context) - 場の空気
会話の流れから抽出された「要約」と「雰囲気」のキャッシュ。
- **役割:** 短期記憶から溢れた古い文脈を補完し、会話のトーン（Mood）を調整。
- **実装:** `memory/channel_context.py`, `memory/summarizer.py`
- **内容:**
  - **Summary:** インクリメンタルに更新される会話の要約。
  - **Mood:** 会話のトーン（例: 「技術的」「カジュアル」）。
  - **Topic Keywords:** 現在のトピックを表すキーワード。
  - **Active Users:** 直近の参加メンバー。
  - **Open Topics:** 会話に残った未解決の話題（最大5件）。詳細は下記。
- **トリガー:** メッセージ数ベース（20件ごと）または時間ベース（15分ごと）のハイブリッド。
- **検証:** 要約は system_instruction に注入されるため、LLM出力の型・長さを検証し改行・制御文字を除去してから保存する（summary 必須、不正な mood / topic_keywords は前回値を維持）。
- **失敗時:** 失敗が続くとバックオフ（`MEMORY_LLM_BACKOFF_*`）し、メッセージ受信のたびに再実行しない。要約対象のメッセージが無い（TTL 切れ等）場合は失敗とみなさず、カウンタを消化するだけにする。
- **カウンタ:** 要約完了時は開始時点のカウント分だけ差し引き、要約中に届いたメッセージ分は次回に持ち越す。
- **未解決の話題（open_topics）:** 自発会話（#104）で「あの件どうなった？」と後から触れるための下準備。要約と同じLLM呼び出しで抽出する（`memory/open_topics.py`）。
  - 各要素: `id`（短い uuid）/ `text`（1文、最大100文字）/ `kind` / `follow_up_after`（フォローに適した時刻。推定できなければ null）
  - `kind`: `plan`（予定・挑戦の結果待ち）/ `question`（未回答の質問）/ `pending`（迷い中・相談中）
  - プロンプトには現在時刻（JST・曜日付き）と前回の open_topics を渡し、解決済みの話題は LLM に削除させる。継続中の話題は前回の `id` を返させ、新しい話題は `id: null` → コード側で採番する（前回に無い id・重複 id も採番し直す）
  - 検証: kind が不正・text が空の要素は捨てる。`follow_up_after` はタイムゾーンなしなら JST とみなし、UTC に正規化して保存（解釈できなければ null）。最大5件。キーの欠落・型不正は前回値を維持し、空配列はクリアとして扱う
  - 永続化: `ChannelContext.open_topics` として local / Firestore の両方に保存する。フィールドの無い旧データは空リストとして読み込む。保存済みデータに同じ `id` が重複していたら先頭の1件だけを残す（自発会話が `id` をキーに言及済みを判定するため）
  - 会話プロンプトへの注入（`format_for_injection`）には含めない。自発会話（下記「自発会話: スケジューラ・生成・送信」）だけが使う

### ③ 長期記憶 (Long-term Memory) - 知識と関係性
ユーザーごとの特性や、過去の重要な「事実」を永続化。
- **場所:** `STORAGE_TYPE` で切り替え（`local` / `firestore`）
- **構成要素:**
  1. **User Profile (`memory/user_profile.py`)**
     - **ギルド単位**で保持（キー: `guild_id` + `user_id`）。あるサーバーで得た事実・性格メモが別サーバーの応答に注入されない。
     - 保存先: Firestore はドキュメントID `{guild_id}_{user_id}`、ローカルは `storage/user_profile.{guild_id}.{user_id}.json`。
     - ギルド分離前の旧プロファイル（`user_id` 単位）からは、交流回数・メンション回数だけを初回アクセス時に引き継ぐ。
     - 親密度レベル (`stranger` -> `close`)。
     - 直近の話題 (`last_topic`)。
     - 会話頻度や活動傾向。
  2. **Fact Store (`memory/fact_store.py`)**
     - 会話から抽出された「面白い事実」や「重要な情報」。
     - キーワード（Jaccard類似度）またはベクトル検索（Vertex AI Embeddings）による呼び出し。
     - `VECTOR_SEARCH_ENABLED=true` 時はコサイン類似度 × Jaccard のハイブリッドスコアリング。
     - 参照頻度（`access_count`）を記録し、`effective_relevance_score`（時間減衰 + 参照頻度ブースト）で重要度を評価。
     - スコアが閾値を下回ると15分ごとに自動削除（忘却）。頻繁に参照されたファクトは閾値を超えやすく長く残る。
     - 反省会LLMが返した `source_user_ids` は、その会話に登場した人間ユーザーのIDだけに絞る。会話内容で誘導された無関係なユーザーのファクトに検索ブーストがかからないようにするため（#136）

---

## 3. 思考と発話のプロセス (The Loop)

メッセージを受信した際、システムは以下のステップで記憶を参照・更新する。

1. **インプット:** 短期記憶にメッセージを追加。
2. **判定 (Judge):** `memory/judge.py` が短期・中期記憶を参照して「今話すべきか」をスコアリング。
3. **検索 (Retrieval):** 応答が決定した場合、キーワードから `Fact Store` や `User Profile` を検索。
4. **生成:** 短期ログ + 中期要約 + 関連ファクト + ユーザー情報を統合してLLMへ入力。
5. **反省 (Reflection):** 会話の沈静化時、`memory/reflection.py` がログを分析して新規ファクトを抽出。

---

## 4. データのライフサイクル

| レイヤー | ストレージ | ライフサイクル | 検索手法 |
| :--- | :--- | :--- | :--- |
| **短期** | メモリ (RAM) | 30分 (TTL) / 50件 | シーケンシャル |
| **中期** | メモリ / Firestore | 会話中継続 / 逐次要約 | キーマッチ |
| **長期 (User)** | ローカル / Firestore | 永続 (常連) | Guild ID + User ID |
| **長期 (Fact)** | ローカル / Firestore | 永続 (鮮度減衰あり) | キーワード / ベクトル |

---

## 5. 環境変数 (Environment Variables)

記憶システムを制御するための主要な環境変数一覧。

### 短期記憶 (Short Term Memory)
- `CHANNEL_BUFFER_SIZE`: チャンネルごとに保持するメッセージの最大数 (デフォルト: 50)
- `CHANNEL_BUFFER_TTL_MINUTES`: メッセージをバッファに保持する時間（分） (デフォルト: 30)

> 使用モデル: 要約・反省会は `BOT_MODEL`、LLM Judge は `BOT_LITE_MODEL`（機能別のモデル変数はない）

### 中期記憶 (Channel Context)
- `LIVING_MEMORY_ENABLED`: チャンネルコンテキスト・ユーザープロファイル・反省会を一括有効にするか (デフォルト: true)
- `SUMMARIZE_EVERY_N_MESSAGES`: 何件のメッセージごとに要約を実行するか (デフォルト: 20)
- `SUMMARIZE_EVERY_N_MINUTES`: 何分経過で要約を実行するか (デフォルト: 15)

### 自律応答 (Autonomous Response) & LLM Judge
> 詳細は [docs/vanguard.md](./vanguard.md) を参照
- `VANGUARD_ENABLED`: 自律応答・LLM Judge・応答多様性・リアクションを一括有効にするか (デフォルト: true)
- `JUDGE_SCORE_THRESHOLD`: 応答するための最低スコア (デフォルト: 20)
- `JUDGE_SCORE_FULL_RESPONSE`: フル応答するためのスコア閾値 (デフォルト: 60)
- `JUDGE_SCORE_SHORT_ACK`: 相槌などの短い応答をするためのスコア閾値 (デフォルト: 30)
- `COOLDOWN_SECONDS`: 発言後のクールダウン時間（秒） (デフォルト: 120)
- `ENGAGEMENT_DURATION_SECONDS`: 応答後のエンゲージメント（会話継続）とみなす期間（秒） (デフォルト: 300)
- `ENGAGEMENT_BOOST`: エンゲージメント中のスコア加算値 (デフォルト: 40)
- `JUDGE_KEYWORDS`: スコアをブーストするキーワード（カンマ区切り）
- `JUDGE_LLM_THRESHOLD_LOW`: LLM Judgeが発動するスコアの下限 (デフォルト: 20)
- `JUDGE_LLM_THRESHOLD_HIGH`: LLM Judgeが発動するスコアの上限 (デフォルト: 60)

### ユーザープロファイル (User Profile)
- `FAMILIARITY_THRESHOLD_ACQUAINTANCE`: 親密度がstrangerからacquaintanceに上がる会話回数 (デフォルト: 6)
- `FAMILIARITY_THRESHOLD_REGULAR`: 親密度がacquaintanceからregularに上がる会話回数 (デフォルト: 31)
- `FAMILIARITY_THRESHOLD_CLOSE`: 親密度がregularからcloseに上がる会話回数 (デフォルト: 101)

### 長期記憶: 反省会エンジン (Reflection)
- `REFLECTION_LULL_MINUTES`: 沈黙が何分続いたら反省会をトリガーするか (デフォルト: 10)
- `REFLECTION_MIN_MESSAGES`: 反省会をトリガーするために必要な最低メッセージ数 (デフォルト: 10)
- `REFLECTION_MAX_BUFFER_MESSAGES`: バッファ蓄積量での強制反省会トリガー件数 (デフォルト: 30)
- `REFLECTION_MAX_FAILURES`: 反省会がこの回数連続で失敗したら（LLM失敗・有効なファクト0件）、対象メッセージを諦めてチェックポイントを進める (デフォルト: 3)
- `MEMORY_LLM_BACKOFF_BASE_SECONDS` / `MEMORY_LLM_BACKOFF_MAX_SECONDS`: 要約・反省会が失敗した後に再実行しない時間。n回連続失敗後は BASE × 2^(n-1) 秒、上限 MAX 秒 (デフォルト: 300 / 3600)
- `STORAGE_LOAD_BACKOFF_BASE_SECONDS` / `STORAGE_LOAD_BACKOFF_MAX_SECONDS`: ファクト・ユーザープロファイル・チャンネルコンテキストの読み込みに失敗した後、再読み込みしない時間。n回連続失敗後は BASE × 2^(n-1) 秒、上限 MAX 秒 (デフォルト: 30 / 600)
- ユーザープロファイルの更新は、対象メッセージの処理が確定した（チェックポイントが進んだ）ときだけ行う。再試行のたびに同じ会話で更新しない

### 長期記憶: ファクトストア (Fact Store)
- `FACT_STORE_MAX_FACTS_PER_CHANNEL`: チャンネルあたりの最大ファクト保持件数 (デフォルト: 100)
- `FACT_DECAY_HALF_LIFE_DAYS`: ファクトのスコア減衰の半減期（日数） (デフォルト: 30)
- `FACT_DEDUP_SIMILARITY_THRESHOLD`: ファクト重複判定のコサイン類似度閾値。正規化した本文の一致、または両方にEmbeddingがありこの値以上なら追加しない (デフォルト: 0.95)
- `FACT_USER_BOOST_FACTOR`: 発言ユーザーIDが一致するファクトの検索スコアブースト倍率 (デフォルト: 1.5)

### 長期記憶: ファクト忘却クリーンアップ (Fact Decay Cleanup)
- `FACT_STORE_CLEANUP_THRESHOLD`: この値を下回る `effective_relevance_score` のファクトを15分ごとに削除 (デフォルト: 0.05)
- `FACT_ACCESS_BOOST_WEIGHT`: 参照頻度ブーストの重み係数。`log1p(access_count) * weight` がスコアに加算される (デフォルト: 0.1)
- `FACT_STORE_ARCHIVE_ENABLED`: `true` にすると削除ファクトをアーカイブストレージに保存する。`false` の場合はログ出力のみ (デフォルト: false)
  - アーカイブには embedding を保存しない（読み戻されず、`EMBEDDING_MODEL` に依存するため。必要になったら本文から再生成する）。既存アーカイブに残る embedding も次回書き込み時に除去する
  - Firestore では件数上限（`FACT_ARCHIVE_MAX_ENTRIES`）に加え、ドキュメントサイズ上限（1MiB）に収まるよう古い順に切り捨てる

### 長期記憶: 永続化
- ファクトストア・ユーザープロファイルは変更のあったチャンネル／プロファイルだけを定期（15分ごと）に書き込む（dirty フラグ）。書き込みに失敗したものは次回再試行する
- 同じチャンネル／プロファイルの保存は、キー単位の保存ロック（`utils/keyed_lock.py`）でスナップショット取得から書き込み完了まで直列化する。忘却クリーンアップと反省会の保存が並行しても、古いスナップショットが後から書き込まれて新しいファクトを消すことはない（#135）。待機中に別スレッドが保存を済ませたものは再書き込みしない
- 保存時のスナップショットは `self._lock` の中で複製して取り、JSON 化・書き込みはロックの外で行う。プロファイルを書き換えるメソッド（`record_message` など）も `self._lock` の中で書き換えるため、1回の保存に書き換え前後の値が混ざらない。FactStore も `search` が書き換える `access_count` 等を固定するため、ロック内で `Fact` を複製してから保存する（#147）
- プロンプト注入用の読み取り（`UserProfileStore.get_profile` / `get_cached_profile`）も `self._lock` の中で取ったスナップショットを返す。人物像などを文字列化している最中に反省会の書き換えが入っても、1回の注入に新旧の値が混ざらない。返り値を書き換えてもキャッシュには反映されないため、更新は `record_message` などストアのメソッドを使う（#153）
- Bot の終了時（SIGTERM / SIGINT を含む）にも、ユーザープロファイル・ファクトストア・チャンネルコンテキストの未保存分（dirty）を永続化する。定期書き込みの合間に溜まった変更を再起動で失わないため。SIGTERM では実行中の LLM 呼び出しの完了を待たずに、接続を閉じる前に書き込む（k8s の猶予期間内に収めるため）
- 永続化先からの読み込みに失敗した場合（ドキュメント未存在は除く）、既存データを空で上書きしないよう次のように扱う。いずれも次回アクセス時に再読み込みする
  - ファクト: チャンネルを未ロードのまま扱う。その間に追加されたファクトは保存を保留し、ロード成功時に既存ファクトとマージしてから保存する
  - ユーザープロファイル／チャンネルコンテキスト: キャッシュしない一時データを返し、保存しない
  - 読み込みに失敗したチャンネル／プロファイルは、失敗が続くとバックオフ（`STORAGE_LOAD_BACKOFF_*`）し、その間はアクセスのたびに読み込まない。traceback 付きの警告ログは連続失敗の初回だけ出す
- Firestore のファクトは1チャンネル1ドキュメント。推定サイズが上限（1MiB）を超える場合は関連度（`effective_relevance_score`）の低いファクトから保存対象外にして警告ログを出す（メモリ上のファクトは変更しない）。警告が出る場合は `FACT_STORE_MAX_FACTS_PER_CHANNEL` を下げる

### 長期記憶: ベクトル検索 (Vector Search)
- `VECTOR_SEARCH_ENABLED`: ハイブリッド検索（キーワード + コサイン類似度）を有効にするか。`LIVING_MEMORY_ENABLED=true`が必要 (デフォルト: false)
- `EMBEDDING_MODEL`: Embedding生成に使用するモデル名 (デフォルト: text-embedding-004)
- `HYBRID_ALPHA`: ハイブリッドスコアのバランス係数。0=Jaccardのみ、1=ベクトルのみ (デフォルト: 0.5)

### 自発会話: チャンネルの opt-in と担当インスタンス (#104 PR2)
「どのチャンネルで、どのインスタンスが話しかけるか」を決める仕組み。送信の条件・流れは次の節を参照。

- **運用ルール: 1チャンネルの担当は1インスタンス。** 同じサーバーで複数のインスタンス（別キャラ）が動いていても、1つのチャンネルで自発会話をするのは担当の1インスタンスだけ。複数のインスタンスが同時に話しかける問題（旧実装）を防ぐため
- **opt-in:** 管理者が対象チャンネルで `/<prefix> proactive enabled:True` を実行する。`ChannelConfig` の `proactive_channels`（チャンネルIDの文字列のリスト）に追加される。対象はチャンネルのみで、スレッドで実行した場合は案内だけ返して何もしない。フィールドの無い旧データは空リストとして読み込む
- **登録簿:** 「チャンネル → 担当インスタンス（`INSTANCE_NAME`）」をインスタンス間で共有する登録簿（`utils/proactive_registry.py`）で管理する
  - firestore: `PROACTIVE_REGISTRY_COLLECTION` の共有コレクション（ドキュメントID = チャンネルID、`{instance, claimed_at}`）。インスタンス間で共有するのが目的なので `FIRESTORE_NAMESPACE` は付けない。登録・削除は transaction で行い、同時に opt-in しても担当は1つに決まる
  - local: `PROACTIVE_REGISTRY_FILE` の JSON ファイル。ロックファイルに flock をかけて読み書きするため、同じホストのプロセス間では排他される。別ホストのインスタンスとは共有できない。形式が壊れたファイルは上書きせずエラーにする
- **ON の流れ:** 登録簿に claim → `ChannelConfig` に保存。別のインスタンスが担当中なら拒否して担当インスタンス名を返す。自分がすでに担当なら冪等に成功する。設定の保存に失敗したら、今回新しく登録した場合だけ登録簿から削除して巻き戻す
- **OFF の流れ:** `ChannelConfig` から削除 → 登録簿から削除（自分が担当している場合だけ）。登録簿の削除に失敗したら、もう一度 OFF を実行するよう案内する（登録が残ると他のインスタンスが担当になれないため）
- **障害時:** 登録簿・設定ストレージの障害では、ユーザーには内部情報を含まない一般的なエラーを返し、ログには traceback を残す
- 担当を別のインスタンスに移すときは、今の担当インスタンスで OFF にしてから、新しい担当インスタンスで ON にする

環境変数:
- `PROACTIVE_REGISTRY_COLLECTION`: 登録簿の Firestore コレクション名。同じサーバーで動く全インスタンスで同じ値にする (デフォルト: `proactive_channel_registry`)
- `PROACTIVE_REGISTRY_FILE`: `STORAGE_TYPE=local` 時の登録簿ファイル (デフォルト: `{LOCAL_STORAGE_DIR}/proactive_channel_registry.json`)。同じホストの複数インスタンスで共有するには全インスタンスで同じパスを指定する

### 自発会話: スケジューラ・生成・送信 (#104 PR3)
沈黙が続いたチャンネルで、会話に残った未解決の話題（open_topics）に担当インスタンスがさりげなく触れる（`memory/proactive.py`）。`PROACTIVE_ENABLED=true` のときだけ動く。

- **タイマーループ:** `PROACTIVE_CHECK_INTERVAL_MINUTES` ごとの `tasks.loop`（`bot/discord_bot.py`）。`on_ready` で開始し（再接続では二重に開始しない）、終了処理（SIGTERM）で止める。`on_message` には依存しない。1ギルド・1チャンネルの例外でループ全体を止めない
- **対象チャンネル:** 全ギルドの `proactive_channels` のうち、取得できるテキストチャンネル（スレッドは除く）で、`can_bot_speak` が True、かつ登録簿の担当が自分（`INSTANCE_NAME`）のもの
- **送信条件（すべて満たすとき）:**
  - 最後の人間の発言からの沈黙が `PROACTIVE_MIN_SILENCE_MINUTES` 以上 `PROACTIVE_MAX_SILENCE_HOURS` 以下
  - 最後の発言が自分ではない（`last_self_message_at < last_human_message_at`）
  - 前回の自発会話から `PROACTIVE_COOLDOWN_HOURS` 以上経っている（全種類合算で1日1回まで）
  - 静音時間帯 `PROACTIVE_QUIET_HOURS`（`PROACTIVE_TIMEZONE` の時刻）の外。`"0-8"` は 0:00〜7:59。`"22-6"` のような日またぎも可
  - 最後の人間の発言時刻が不明（再起動直後で旧データしかない等）なら送らない
- **沈黙の判定に使う時刻:** チャンネルバッファは TTL（`CHANNEL_BUFFER_TTL_MINUTES`）で消えるため使わず、`ChannelContext` に持つ
  - `last_human_message_at`: 人間の発言を記録したとき（`increment_message_count` と同じ場所）に更新する。発言可能なチャンネルの、ボット以外の発言だけが対象
  - `last_self_message_at`: 自分が発言したとき（メンション応答・自律応答・相槌・自発会話）に更新する
  - これらは要約時・終了時にだけ永続化されるので、クラッシュ後は古い値が残りうる。そのため生成の前に Discord の直近の履歴（10件）を取得し、最後の発言が自分、または最後の発言が `PROACTIVE_MIN_SILENCE_MINUTES` 以内なら送らない。履歴を取得できなければ送らない
- **話題の選び方（1回に1件）:** 言及済みの `id`（`mentioned_topic_ids`）を除く → `follow_up_after` を過ぎて `PROACTIVE_FOLLOW_UP_WINDOW_HOURS` 以内の話題を優先する（時刻の早い順。沈黙の上限は無視するが、下限・静音時間帯・クールダウンは適用する）→ なければ沈黙が上限内のときだけ `follow_up_after` を持たない話題から選ぶ。`follow_up_after` が未来の話題・ウィンドウを過ぎた話題は選ばない
- **生成:** `ai/conversation.py` の `generate_proactive_message`。`system.txt` ＋ チャンネル要約 ＋ 直近の履歴 ＋ 対象の話題（`<open_topic>` タグで囲みエスケープ）から、構造化出力 `{speak, message}`（`response_json_schema`）で返させる。`speak` が `true` でない・メッセージが空・JSON 不正・API 失敗なら送らない
- **送信:** 返信先がないのでチャンネルに直接 `split_message` → `channel.send`。生成中に人間が発言した、または担当が変わった（送信直前に登録簿を再確認）場合は送らない
- **送信後の記録:** 1チャンクでも送れたら、まず `ChannelContext` に言及済みの `id`（最大50件）・`last_proactive_at`・`last_self_message_at` を記録して保存する（同じ話題に二度と触れないため）。続けて会話履歴（`channel_conversations`）に「自分から話しかけた」記録＋モデルの発言を追加し（返信されたときに文脈を持つため）、チャンネルバッファに `is_bot=True` で追加し、`judge.record_response()` を呼ぶ
- **永続化:** 新しいフィールドは local / Firestore の両方に保存する。フィールドの無い旧データは「不明（None）」・空リストとして読み込む
- **既知の制約:** 言及済みの判定は話題の `id` で行う。要約LLMが継続中の話題に `id: null` や前回に無い id を返すと、コード側で新しい id が採番される（`open_topics.py` の `_parse_topic_item`）。そのため同じ話題でも `mentioned_topic_ids` に一致せず、クールダウン（`PROACTIVE_COOLDOWN_HOURS`）が明けたあとに同じ話題へもう一度触れることがある。クールダウンで頻度は抑えられるので、現時点では許容している

環境変数:
- `PROACTIVE_ENABLED`: 自発会話を有効にする (デフォルト: `false`)。`LIVING_MEMORY_ENABLED=true` が必要で、起動時に設定を検証する（不正なら起動しない）
- `PROACTIVE_CHECK_INTERVAL_MINUTES`: 判定の間隔（分） (デフォルト: 10)
- `PROACTIVE_MIN_SILENCE_MINUTES`: 沈黙の下限（分） (デフォルト: 120)
- `PROACTIVE_MAX_SILENCE_HOURS`: 沈黙の上限（時間） (デフォルト: 24)
- `PROACTIVE_COOLDOWN_HOURS`: 前回の自発会話からの最短間隔（時間） (デフォルト: 24)
- `PROACTIVE_QUIET_HOURS`: 静音時間帯（`開始-終了` の時、開始を含み終了を含まない。空文字で無効） (デフォルト: `0-8`)
- `PROACTIVE_TIMEZONE`: 静音時間帯のタイムゾーン（IANA 名） (デフォルト: `Asia/Tokyo`)
- `PROACTIVE_FOLLOW_UP_WINDOW_HOURS`: `follow_up_after` からこの時間内なら沈黙の上限を無視して触れる (デフォルト: 24)

---

## 6. 今後の拡張 (Roadmap)

- **リッチプロファイル:** LLMによるユーザー性格のタグ付け、特別な呼び名の記憶。 ([#79](https://github.com/feelingover/sphene/issues/79))
- **Firestore Native Vector Search:** `find_nearest()` を使ったベクトル検索のインフラ層への移譲（現状はin-memoryコサイン類似度）。
