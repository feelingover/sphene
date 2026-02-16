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

### ② 中期記憶 (Channel Context) — Phase 2A で実装予定

* **場所:** インメモリ（デフォルト） / ローカルJSON / Firestore（`CHANNEL_CONTEXT_STORAGE_TYPE` で切替）
* **内容:** 「場の空気」のキャッシュ。
  * **Summary:** LLMによるローリング要約（N件ごとにインクリメンタル更新）。
  * **Mood:** 会話のトーン（casual, technical, heated 等）。
  * **Topic Keywords:** 現在のトピックを表すキーワード群。
  * **Active Users:** 直近の参加メンバー。
* **トリガー:** `SUMMARIZE_EVERY_N_MESSAGES`（デフォルト: 20件）ごとに非同期で再要約。

### ③ 長期記憶 (Long-term Memory)

* **場所:** Firestore (/user_profiles/{id}, /facts/{id})
* **内容:**
  * **User Profile (Phase 2B):** まずはシンプルなカウンター（発言数、メンション数、活動チャンネル）。LLMベースのタグ抽出は Phase 3B で追加。
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
   * **第2段: LLMJudge** (`memory/llm_judge.py`) — 曖昧な場合のみ起動。
     * スコアが `JUDGE_LLM_THRESHOLD_HIGH`（80）以上 → LLM不要、即応答。
     * スコアが `JUDGE_LLM_THRESHOLD_LOW`（20）以下 → LLM不要、スキップ。
     * その間 → LLMが直近会話コンテキストを分析して `{"respond": true/false}` を返す。
5. **Action:** ✅ 実装済み
   * スコアが閾値を超えた場合 → `generate_contextual_response()` を1-shot で呼び出し。
   * **Context Retrieval:**
     * 短期ログ（直近10件のフォーマット済み文字列）。
     * (Phase 2A以降) チャンネル要約 + ユーザープロファイル + 関連ファクト。
   * **Generation:**
     * システムプロンプト + チャンネルコンテキストを含む指示で応答生成。
     * Function Calling（XIVAPI検索等）も利用可能。
6. **Post-Process (Phase 3A で実装予定):**
   * 会話の沈静化を検知（N分間新規メッセージなし）。
   * 反省会プロセス: ログを要約、事実を抽出してファクトストアへ保存。
   * ユーザープロファイルの更新。

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
  "timestamp": Timestamp
}
```

## 6. 実装ロードマップ

### Phase 1: 基礎会話 & Judge ✅ 完了

* 常駐プロセス (discord.py Websocket) の立ち上げ。
* 短期記憶: `ChannelMessageBuffer`（リングバッファ + TTL破棄）。
* 2段階 Judge: `RuleBasedJudge`（ルールベーススコアリング）+ `LLMJudge`（LLM二次判定）。
* 自律応答: `generate_contextual_response()` による1-shot コンテキスト応答。
* クールダウン & エンゲージメント追跡（チャンネル単位）。

### Phase 2A: チャンネルコンテキスト（中期記憶の最小実装）

* LLMによるローリング要約エンジン（`memory/summarizer.py`）。
  * N件（デフォルト20件）ごとにインクリメンタル要約（前回の要約 + 新規メッセージ → 新要約）。
  * 非同期実行（`asyncio.to_thread()`、Discordハートビートをブロックしない）。
* `ChannelContext` データモデル（`memory/channel_context.py`）。
  * summary, mood, topic_keywords, active_users を保持。
* ストレージ: `CHANNEL_CONTEXT_STORAGE_TYPE` で切替（memory / local / firestore）。
* `generate_contextual_response()` にチャンネル要約を注入。
* 環境変数: `CHANNEL_CONTEXT_ENABLED`, `CHANNEL_CONTEXT_STORAGE_TYPE`, `SUMMARIZE_EVERY_N_MESSAGES`, `SUMMARIZE_MODEL`

### Phase 2B: ユーザープロファイル（シンプルカウンター）

* `UserProfile` データモデル（`memory/user_profile.py`）。
  * interaction_count, mentioned_bot_count, channels_active, last_interaction。
* インメモリキャッシュ + 定期永続化（15分間隔）。
* ストレージ: `USER_PROFILE_STORAGE_TYPE` で切替（memory / local / firestore）。
* `generate_contextual_response()` にユーザー情報を注入。
* 環境変数: `USER_PROFILE_ENABLED`, `USER_PROFILE_STORAGE_TYPE`

### Phase 3A: 反省会 + ファクトストア（キーワードベース長期記憶）

* 会話の沈静化検知: N分間（デフォルト10分）新規メッセージなしで発動。
  * 既存の15分間隔クリーンアップタスク内でチェック。
  * 最低メッセージ数（デフォルト10件）を満たした場合のみ実行。
* 反省会エンジン（`memory/reflection.py`）: 会話ログから事実を抽出。
* ファクトストア（`memory/fact_store.py`）: キーワードベースの事実保存・検索。
  * Jaccard類似度でキーワード重複をランキング。
  * Firestore `array-contains-any` クエリで候補取得。
* `generate_contextual_response()` に関連ファクトを注入。
* 環境変数: `REFLECTION_ENABLED`, `REFLECTION_LULL_MINUTES`, `REFLECTION_MIN_MESSAGES`, `REFLECTION_MODEL`, `FACT_STORE_STORAGE_TYPE`, `FACT_STORE_MAX_FACTS_PER_CHANNEL`

### Phase 3B: ベクトル検索 + リッチプロファイル（オプション）

* Phase 3A のキーワード検索で不十分と判明した場合に実施。
* Vertex AI Embeddings API（`text-embedding-004`）でベクトル生成。
* Firestore Vector Search による意味的類似性検索。
* ユーザープロファイル拡張: LLM抽出のタグ、性格メモ、最終会話要約。
* 環境変数: `VECTOR_SEARCH_ENABLED`, `EMBEDDING_MODEL`, `USER_PROFILE_TAGS_ENABLED`
