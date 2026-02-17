# 自然会話Discordボット設計案

## 1. コンセプト

「ただの便利ツール」ではなく、チャンネルの**参加者の一人**として振る舞うボット。

文脈（Context）を理解し、空気を読み、適切なタイミングで会話に割り込むことができる「人格」を持つ。

## 2. システム構成概略

* **Runtime:** 常駐プロセス (Stateful)
  * Websocket接続でリアルタイムに全イベントをハンドリング。
  * オンメモリで直近のステートを管理できるため高速。
* **Database:** Google Cloud Firestore
  * ドキュメントDBとして構造化データ（プロファイル・要約）を保存。
  * **Vector Search** を利用して「曖昧な記憶」の検索に対応。
* **AI Models:**
  * **Judge (判定役):** ルールベース（即座） + LLM二次判定（Gemini Flash、オプション）
  * **Main Brain (発話・要約):** Gemini 2.5 Flash（デフォルト） / Gemini 2.5 Pro

## 3. 記憶の構造デザイン (3層構造)

### ① 短期記憶 (Working Memory) — ✅ 実装済み

* **場所:** オンメモリ (RAM) — `memory/short_term.py`
* **実装:**
  * **ChannelMessageBuffer:** チャンネルごとの `collections.deque` リングバッファ。
  * **容量:** `CHANNEL_BUFFER_SIZE`（デフォルト: 50件）。
  * **TTL:** `CHANNEL_BUFFER_TTL_MINUTES`（デフォルト: 30分）超過で自動削除。
  * **コンテキスト生成:** `get_context_string()` でLLM向けフォーマット済み文字列を出力。
  * **クリーンアップ:** 15分間隔のバックグラウンドタスクで期限切れメッセージを除去。

### ② 中期記憶 (Channel Context) — ✅ 実装済み (Phase 2A)

* **場所:** インメモリ（デフォルト） / ローカルJSON / Firestore（`CHANNEL_CONTEXT_STORAGE_TYPE` で切替）
* **内容:** 「場の空気」のキャッシュ。
  * **Summary:** LLMによるローリング要約（インクリメンタル更新）。
  * **Mood:** 会話のトーンをフリーテキストで記述（例: 「カジュアルで盛り上がっている」「技術的で落ち着いた議論」）。LLMが要約時に自然言語で生成。
  * **Topic Keywords:** 現在のトピックを表すキーワード群。
  * **Active Users:** 直近の参加メンバー。
* **トリガー（ハイブリッド方式）:**
  * **メッセージ数ベース:** `SUMMARIZE_EVERY_N_MESSAGES`（デフォルト: 20件）到達で発火。
  * **時間ベース:** `SUMMARIZE_EVERY_N_MINUTES`（デフォルト: 15分）経過で発火（まったり会話向け）。
  * どちらか早い方で非同期に再要約を実行。
* **コンテキスト注入フォーマット:** 要約を応答生成に注入する際の構造:

  ```text
  【このチャンネルの状況】
  話題: {topic_keywords}
  雰囲気: {mood}
  参加者: {active_users}
  直近の流れ: {summary}
  ```

### ③ 長期記憶 (Long-term Memory)

* **場所:** Firestore (/user_profiles/{id}, /facts/{id})
* **内容:**
  * **User Profile (Phase 2B):** シンプルなカウンター（発言数、メンション数、活動チャンネル）に加え、関係性レベル（`familiarity_level`）と直近の話題（`last_topic`）を保持。LLMベースのタグ抽出は Phase 3B で追加。
  * **Fact Store (Phase 3A):** 反省会プロセスで抽出された事実。**まずキーワードベース検索**（Jaccard類似度）で実装し、ベクトル検索は Phase 3B でオプション追加。

## 4. 思考と発話のプロセス (The Loop)

常駐プロセスが MESSAGE_CREATE を受信した時のフロー：

1. **フィルタリング:**
   * 自身の発言、空メッセージ、DMを除外。
   * チャンネル設定（ホワイトリスト/ブラックリスト）で発話可否を判定。
2. **短期記憶への追加:** ✅ 実装済み
   * `ChannelMessageBuffer` にメッセージを追加（リングバッファ）。
3. **メンション判定:** ✅ 実装済み
   * @メンション / リプライ / 名前呼びを検出。
   * 該当時 → 即座に `process_conversation()` で応答（会話履歴を保持）。
4. **Judge (自律応答判定) — 2段階方式:** ✅ 実装済み
   * **第1段: RuleBasedJudge** (`memory/judge.py`) — 即座にスコアリング (0-100)。
     * @メンション: 100点（即応答）
     * ボットへのリプライ: 100点（即応答）
     * 名前呼び: 80点（即応答）
     * エンゲージメント期間中（直近応答から5分以内）: +40点
     * 疑問符（?/？）で終わる: +20点
     * キーワードマッチ（`JUDGE_KEYWORDS`）: +15点
     * クールダウン中（直近応答から2分以内）: -50点
     * **会話フロー考慮ルール（Phase 2A で追加済み ✅）:**
     * 会話参加者が2人だけ（1対1の会話に割り込まない）: -20点
     * 直近N件でボットへの言及なし: -10点
     * 直近N件のメッセージ頻度が高い（盛り上がり中に水を差さない）: -10点
     * ボットが知識を持つ話題（FF14関連など）: +15点
     * 長時間沈黙後の最初のメッセージ（新しい会話の開始 = 参加しやすい）: +10点
     * 会話の減衰検知（応答が短くなる傾向）: -10〜-15点
   * **第2段: LLMJudge** (`memory/llm_judge.py`) — 曖昧な場合のみ起動。
     * スコアが `JUDGE_LLM_THRESHOLD_HIGH`（80）以上 → LLM不要、即応答。
     * スコアが `JUDGE_LLM_THRESHOLD_LOW`（20）以下 → LLM不要、スキップ。
     * その間 → LLMが直近会話コンテキストを分析して `{"respond": true/false}` を返す。
5. **Action:** ✅ 実装済み（応答多様性 Phase 2A で追加済み ✅）
   * スコアが閾値を超えた場合 → 応答タイプを決定し、タイプに応じた処理を実行。
   * **応答タイプ判定（`RESPONSE_DIVERSITY_ENABLED` で有効化）:**
     * `react_only`: 絵文字リアクションのみ（👀😊👍🤔✨💡）。スコアが60未満の場合。
     * `short_ack`: 一言の相槌を生成（`max_output_tokens=50`）。スコアが60〜79でエンゲージメント外の場合。
     * `full_response`: 通常の応答。スコアが80以上 or 質問・名前呼びなど明確なトリガーがある場合。
     * 判定はルールベースJudge内でスコアと合わせて決定（LLM不要）。
   * **Context Retrieval:**
     * 短期ログ（直近10件のフォーマット済み文字列）。
     * チャンネル要約（Phase 2A で実装済み ✅） + (Phase 2B以降) ユーザープロファイル + 関連ファクト。
   * **Generation:**
     * システムプロンプト + チャンネルコンテキストを含む指示で応答生成。
     * Function Calling（XIVAPI検索等）も利用可能。
6. **会話の減衰検知:** ✅ 実装済み (Phase 2A)
   * エンゲージメント期間中でも、相手の応答が短くなってきた場合（直近6件の前半vs後半の平均文字数を比較）にスコアを減衰（-10〜-15点）。
   * 会話の終わり時を察し、無限に返し続けない自然なフェードアウトを実現。
7. **Post-Process (Phase 3A で実装予定):**
   * 会話の沈静化を検知（N分間新規メッセージなし）OR メッセージ蓄積量超過。
   * 反省会プロセス: ログを要約、事実を抽出してファクトストアへ保存。
   * ユーザープロファイルの更新。
8. **自発的な会話開始 (Phase 3A 以降で実装予定):**
   * 反省会で発見した「面白い事実」を保持。
   * チャンネルが再度活性化した際に、関連話題があれば自発的に共有（例: 「そういえば前に○○の話してたけど…」）。
   * 発動条件: 共有すべきファクトがある + チャンネルが沈黙後に再活性化 + クールダウン外。

## 5. データ構造案 (Firestore)

```javascript
/* チャンネルコンテキスト (Phase 2A)：場の空気を保存 */
/channel_contexts/{channelId}
{
  "summary": "Rustの非同期処理について議論中。Aさんが苦戦している。",
  "mood": "technical, helpful",
  "topicKeywords": ["Rust", "async", "tokio"],
  "activeUsers": ["UserA", "UserB"],
  "lastUpdated": Timestamp,
  "messageCountSinceUpdate": 0
}

/* ユーザープロファイル (Phase 2B → 3B で拡張)：相手を知る */
/user_profiles/{userId}
{
  "displayName": "UserA",
  "interactionCount": 150,       // Phase 2B: シンプルカウンター
  "mentionedBotCount": 12,       // Phase 2B
  "channelsActive": [100, 200],  // Phase 2B
  "lastInteraction": Timestamp,  // Phase 2B
  "familiarityLevel": "regular", // Phase 2B: interactionCountから自動算出 (stranger/acquaintance/regular/close)
  "lastTopic": ["CI/CD", "GitHub Actions"], // Phase 2B: 直近会話のトピックキーワード
  "tags": ["Rustacean", "猫好き"], // Phase 3B: LLM抽出（オプション）
  "lastConversationSummary": "前回はCI/CDの構築について話した" // Phase 3B
}

/* ファクトストア (Phase 3A)：抽出された事実 */
/facts/{factId}
{
  "content": "UserAが初めてRustで非同期処理を書いた時の話。コンパイルエラーに3時間ハマった。",
  "sourceChannelId": 100,
  "sourceUserIds": [12345],
  "keywords": ["Rust", "async", "compile error"],  // Phase 3A: キーワードベース検索
  "embedding": [0.012, -0.34, ...],                 // Phase 3B: ベクトル検索（オプション）
  "confidence": 0.85,
  "timestamp": Timestamp,
  "decayFactor": 0.95             // Phase 3A: 時間経過で減衰（検索スコアに乗算）
}
```

## 6. 実装ロードマップ

### Phase 1: 基礎会話 & Judge ✅ 完了

* 常駐プロセス (discord.py Websocket) の立ち上げ。
* 短期記憶: `ChannelMessageBuffer`（リングバッファ + TTL破棄）。
* 2段階 Judge: `RuleBasedJudge`（ルールベーススコアリング）+ `LLMJudge`（LLM二次判定）。
* 自律応答: `generate_contextual_response()` による1-shot コンテキスト応答。
* クールダウン & エンゲージメント追跡（チャンネル単位）。

### Phase 2A: チャンネルコンテキスト + 応答多様性 + Judge拡張 ✅ 完了

* **ローリング要約エンジン**（`memory/summarizer.py`）。
  * ハイブリッドトリガー: N件（デフォルト20件）ごと OR N分（デフォルト15分）経過のどちらか早い方。
  * インクリメンタル要約（前回の要約 + 新規メッセージ → 新要約）。
  * mood はフリーテキストで生成（LLMが自然言語で記述）。
  * 非同期実行（`asyncio.to_thread()`、Discordハートビートをブロックしない）。
* **`ChannelContext` データモデル**（`memory/channel_context.py`）。
  * summary, mood, topic_keywords, active_users を保持。
* ストレージ: `CHANNEL_CONTEXT_STORAGE_TYPE` で切替（memory / local / firestore）。
* **コンテキスト注入**: `generate_contextual_response()` にチャンネル要約を定型フォーマットで注入。
* **応答多様性**（`memory/judge.py` 拡張）。
  * JudgeResult に `response_type` フィールドを追加（`react_only` / `short_ack` / `full_response`）。
  * スコアと状況に基づいてルールベースで応答タイプを決定。
  * `react_only`: 絵文字リアクションのみ追加（LLM呼び出し不要）。
  * `short_ack`: 一言の相槌を生成（軽量プロンプト）。
  * `full_response`: 従来通りの応答生成。
* **Judge拡張: 会話フロー考慮**（`memory/judge.py` 拡張）。
  * 短期記憶の `active_users` から会話参加者数を判定。
  * 2人だけの会話: -20点 / ボットへの言及なし: -10点 / 高頻度メッセージ: -10点。
  * ボットの得意話題: +15点 / 沈黙後の最初のメッセージ: +10点。
* **会話の減衰検知**: エンゲージメント中でも相手の応答が短くなる傾向を検知してスコアを減衰。
* 環境変数: `CHANNEL_CONTEXT_ENABLED`, `CHANNEL_CONTEXT_STORAGE_TYPE`, `SUMMARIZE_EVERY_N_MESSAGES`, `SUMMARIZE_EVERY_N_MINUTES`, `SUMMARIZE_MODEL`, `RESPONSE_DIVERSITY_ENABLED`

### Phase 2B: ユーザープロファイル（カウンター + 関係性 + 直近話題）

* `UserProfile` データモデル（`memory/user_profile.py`）。
  * interaction_count, mentioned_bot_count, channels_active, last_interaction。
  * `familiarity_level`: interaction_count の閾値から自動算出（LLM不要）。
    * `stranger`（0-5回）→ `acquaintance`（6-30回）→ `regular`（31-100回）→ `close`（101回〜）
    * 初見の相手にはやや丁寧に、常連にはよりフランクに振る舞う基準として使用。
  * `last_topic`: 直近の会話で話したトピックキーワード（メッセージバッファから抽出、LLM不要）。
    * 「前に○○の話してたよね」を可能にし、人間らしい記憶の連続性を実現。
* インメモリキャッシュ + 定期永続化（15分間隔）。
* ストレージ: `USER_PROFILE_STORAGE_TYPE` で切替（memory / local / firestore）。
* `generate_contextual_response()` にユーザー情報（関係性レベル・直近話題を含む）を注入。
* 環境変数: `USER_PROFILE_ENABLED`, `USER_PROFILE_STORAGE_TYPE`, `FAMILIARITY_THRESHOLDS`

### Phase 3A: 反省会 + ファクトストア + 自発的会話（キーワードベース長期記憶）

* **反省会トリガー（ハイブリッド方式）:**
  * **沈静化検知:** N分間（デフォルト10分）新規メッセージなしで発動。
  * **蓄積量ベース:** `REFLECTION_MAX_BUFFER_MESSAGES`（デフォルト: 100件）を超えた場合に強制実行。24時間活発なサーバーで反省会が走らない問題を回避。
  * 既存の15分間隔クリーンアップタスク内でチェック。
  * 最低メッセージ数（デフォルト10件）を満たした場合のみ実行。
* 反省会エンジン（`memory/reflection.py`）: 会話ログから事実を抽出。
* ファクトストア（`memory/fact_store.py`）: キーワードベースの事実保存・検索。
  * Jaccard類似度でキーワード重複をランキング。
  * Firestore `array-contains-any` クエリで候補取得。
* **ファクト検索タイミング:** Judge判定で「応答する」と決まった後、応答生成前に実行。
  * トリガーメッセージのキーワード + 発言者の user_id でファクト検索。
  * 関連ファクトが見つかった場合「関連する過去の記憶」としてプロンプトに注入。
  * 毎メッセージではなく応答確定後のみ検索することでレイテンシへの影響を最小化。
* **ファクト鮮度管理:** 古い記憶を自然に忘れる仕組み。
  * `relevance_decay`: 時間経過でファクトの検索スコアを減衰（例: 30日で半減）。
  * 検索時: `Jaccard類似度 × decay_factor` でランキング。
  * 一定スコア以下のファクトは定期クリーンアップで削除。
* **自発的な会話開始:** 反省会で発見した「面白い事実」を共有。
  * 反省会プロセスで `shareable` フラグ付きのファクトを生成（LLMが判定）。
  * チャンネルが沈黙後に再活性化した際、関連する shareable ファクトがあれば自発的に話題を振る。
  * 発動条件: shareable ファクトあり + 沈黙後の再活性化 + クールダウン外。
* 環境変数: `REFLECTION_ENABLED`, `REFLECTION_LULL_MINUTES`, `REFLECTION_MIN_MESSAGES`, `REFLECTION_MAX_BUFFER_MESSAGES`, `REFLECTION_MODEL`, `FACT_STORE_STORAGE_TYPE`, `FACT_STORE_MAX_FACTS_PER_CHANNEL`, `FACT_DECAY_HALF_LIFE_DAYS`, `PROACTIVE_CONVERSATION_ENABLED`

### Phase 3B: ベクトル検索 + リッチプロファイル（オプション）

* Phase 3A のキーワード検索で不十分と判明した場合に実施。
* Vertex AI Embeddings API（`text-embedding-004`）でベクトル生成。
* Firestore Vector Search による意味的類似性検索。
* ユーザープロファイル拡張: LLM抽出のタグ、性格メモ、最終会話要約。
* 環境変数: `VECTOR_SEARCH_ENABLED`, `EMBEDDING_MODEL`, `USER_PROFILE_TAGS_ENABLED`
