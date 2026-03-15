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

### ② 中期記憶 (Channel Context) - 場の空気
会話の流れから抽出された「要約」と「雰囲気」のキャッシュ。
- **役割:** 短期記憶から溢れた古い文脈を補完し、会話のトーン（Mood）を調整。
- **実装:** `memory/channel_context.py`, `memory/summarizer.py`
- **内容:**
  - **Summary:** インクリメンタルに更新される会話の要約。
  - **Mood:** 会話のトーン（例: 「技術的」「カジュアル」）。
  - **Topic Keywords:** 現在のトピックを表すキーワード。
  - **Active Users:** 直近の参加メンバー。
- **トリガー:** メッセージ数ベース（20件ごと）または時間ベース（15分ごと）のハイブリッド。

### ③ 長期記憶 (Long-term Memory) - 知識と関係性
ユーザーごとの特性や、過去の重要な「事実」を永続化。
- **場所:** Firestore
- **構成要素:**
  1. **User Profile (`memory/user_profile.py`)**
     - 親密度レベル (`stranger` -> `close`)。
     - 直近の話題 (`last_topic`)。
     - 会話頻度や活動傾向。
  2. **Fact Store (`memory/fact_store.py`)**
     - 会話から抽出された「面白い事実」や「重要な情報」。
     - キーワード（Jaccard類似度）またはベクトル検索（Vertex AI Embeddings）による呼び出し。
     - `VECTOR_SEARCH_ENABLED=true` 時はコサイン類似度 × Jaccard のハイブリッドスコアリング。
     - 参照頻度（`access_count`）を記録し、`effective_relevance_score`（時間減衰 + 参照頻度ブースト）で重要度を評価。
     - スコアが閾値を下回ると15分ごとに自動削除（忘却）。頻繁に参照されたファクトは閾値を超えやすく長く残る。

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
| **長期 (User)** | Firestore | 永続 (常連) | User ID |
| **長期 (Fact)** | Firestore | 永続 (鮮度減衰あり) | キーワード / ベクトル |

---

## 5. 環境変数 (Environment Variables)

記憶システムを制御するための主要な環境変数一覧。

### 短期記憶 (Short Term Memory)
- `CHANNEL_BUFFER_SIZE`: チャンネルごとに保持するメッセージの最大数 (デフォルト: 50)
- `CHANNEL_BUFFER_TTL_MINUTES`: メッセージをバッファに保持する時間（分） (デフォルト: 30)

### 中期記憶 (Channel Context)
- `LIVING_MEMORY_ENABLED`: チャンネルコンテキスト・ユーザープロファイル・反省会を一括有効にするか (デフォルト: true)
- `SUMMARIZE_EVERY_N_MESSAGES`: 何件のメッセージごとに要約を実行するか (デフォルト: 20)
- `SUMMARIZE_EVERY_N_MINUTES`: 何分経過で要約を実行するか (デフォルト: 15)
- `SUMMARIZE_MODEL`: 要約に使用するモデル名（空の場合はメインモデルを使用）

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
- `JUDGE_MODEL`: LLM Judgeに使用するモデル名（空の場合はメインモデルを使用）
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
- `REFLECTION_MODEL`: 反省会に使用するモデル名（空の場合はメインモデルを使用）

### 長期記憶: ファクトストア (Fact Store)
- `FACT_STORE_MAX_FACTS_PER_CHANNEL`: チャンネルあたりの最大ファクト保持件数 (デフォルト: 100)
- `FACT_DECAY_HALF_LIFE_DAYS`: ファクトのスコア減衰の半減期（日数） (デフォルト: 30)
- `FACT_USER_BOOST_FACTOR`: 発言ユーザーIDが一致するファクトの検索スコアブースト倍率 (デフォルト: 1.5)

### 長期記憶: ファクト忘却クリーンアップ (Fact Decay Cleanup)
- `FACT_STORE_CLEANUP_THRESHOLD`: この値を下回る `effective_relevance_score` のファクトを15分ごとに削除 (デフォルト: 0.05)
- `FACT_ACCESS_BOOST_WEIGHT`: 参照頻度ブーストの重み係数。`log1p(access_count) * weight` がスコアに加算される (デフォルト: 0.1)
- `FACT_STORE_ARCHIVE_ENABLED`: `true` にすると削除ファクトをアーカイブストレージに保存する。`false` の場合はログ出力のみ (デフォルト: false)

### 長期記憶: ベクトル検索 (Vector Search)
- `VECTOR_SEARCH_ENABLED`: ハイブリッド検索（キーワード + コサイン類似度）を有効にするか。`LIVING_MEMORY_ENABLED=true`が必要 (デフォルト: false)
- `EMBEDDING_MODEL`: Embedding生成に使用するモデル名 (デフォルト: text-embedding-004)
- `HYBRID_ALPHA`: ハイブリッドスコアのバランス係数。0=Jaccardのみ、1=ベクトルのみ (デフォルト: 0.5)

---

## 6. 今後の拡張 (Roadmap)

- **リッチプロファイル:** LLMによるユーザー性格のタグ付け、特別な呼び名の記憶。 ([#79](https://github.com/feelingover/sphene/issues/79))
- **Firestore Native Vector Search:** `find_nearest()` を使ったベクトル検索のインフラ層への移譲（現状はin-memoryコサイン類似度）。
