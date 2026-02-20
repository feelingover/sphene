# 自律応答システム

## アーキテクチャ

```
メッセージ受信
│
├─ @メンション / リプライ / 名前呼び → 即応答 + エンゲージメント記録
│
└─ それ以外 → RuleBasedJudge でスコアリング
                  │
                  ├─ スコア >= LLM_THRESHOLD_HIGH → 即応答 (タイプはスコアで決定)
                  ├─ スコア <= LLM_THRESHOLD_LOW  → スキップ
                  └─ 中間スコア → LLM Judge で二次判定
                                    │
                                    ├─ respond: true  → 応答 (タイプもLLMが決定)
                                    └─ respond: false → スキップ
```

### スコアリングテーブル

| 条件 | スコア | 備考 |
|------|--------|------|
| @メンション | 100 | 即応答（スコアリング不要） |
| ボットへのリプライ | 100 | 即応答（スコアリング不要） |
| 名前呼び（BOT_NAME） | 80 | 即応答（スコアリング不要） |
| エンゲージメント中 | +ENGAGEMENT_BOOST | 応答後 ENGAGEMENT_DURATION_SECONDS 以内 |
| 疑問符（? / ？）で終わる | +20 | |
| キーワードマッチ | +15 | JUDGE_KEYWORDS のいずれか（1回のみ） |
| **得意話題** | **+15** | 直近の会話にキーワードが含まれる場合 |
| **沈黙後の発言** | **+10** | 直前の発言から10分以上経過 |
| **2人会話** | **-20** | 直近の会話参加者が2名のみ（Bot除く） |
| **ボット言及なし** | **-10** | 直近の会話でBotの名前が出ていない |
| **高頻度会話** | **-10** | 直近10件が60秒以内に集中 |
| **会話減衰** | **-10 ~ -15** | 直近の発言文字数が減少傾向 |
| クールダウン中 | -50 | 応答後 COOLDOWN_SECONDS 以内 |

最終スコアは 0-100 にクランプされる。

### 応答タイプ (Response Diversity)

`RESPONSE_DIVERSITY_ENABLED` が有効な場合、スコアやLLM判定に応じて応答の形式が変化する。

| スコア / 状況 | 応答タイプ | 挙動 |
|---------------|------------|------|
| `JUDGE_SCORE_FULL_RESPONSE` (60) 以上 | `full_response` | 通常の文章による応答 |
| `JUDGE_SCORE_SHORT_ACK` (30) 以上 | `short_ack` | 短い相槌や同意のみ |
| それ未満 | `react_only` | リアクションのみ |

**注:** LLM Judgeが有効な場合、上記の閾値に関わらずLLMが最適な `response_type` (`full`, `short`, `react`) を選択し、その決定が優先される。

### エンゲージメント・タイムライン

```
ボット応答
  │
  ├─ [0 ~ COOLDOWN_SECONDS]              クールダウン(-50) + エンゲージメント(+boost)
  ├─ [COOLDOWN_SECONDS ~ ENGAGEMENT_DURATION_SECONDS]  エンゲージメント(+boost) のみ
  └─ [ENGAGEMENT_DURATION_SECONDS ~]      通常状態
```

- `_last_response_times` を共有し、クールダウンとエンゲージメントの両方を判定
- クールダウン期間中もエンゲージメントブーストは加算される（相殺関係）
- メンション/リプライ/名前呼びによる応答もエンゲージメントを記録する

### LLM Judge

中間スコア帯のメッセージに対して、安価なLLMで「自然に参加すべきか」および「その形式」を二次判定する。
直近15メッセージのコンテキストを渡し、JSON形式で `{"respond": true/false, "response_type": "full"|"short"|"react"|"none", "reason": "..."}` を返す。

## パラメータリファレンス

### 短期記憶

| 変数 | デフォルト | 説明 |
|------|-----------|------|
| `MEMORY_ENABLED` | `false` | 短期記憶（チャンネルバッファ）の有効化 |
| `CHANNEL_BUFFER_SIZE` | `50` | チャンネルごとのバッファ保持メッセージ数 |
| `CHANNEL_BUFFER_TTL_MINUTES` | `30` | バッファ内メッセージの有効期限（分） |

### 自律応答（ルールベース）

| 変数 | デフォルト | 説明 |
|------|-----------|------|
| `AUTONOMOUS_RESPONSE_ENABLED` | `false` | 自律応答の有効化（MEMORY_ENABLED も必要） |
| `JUDGE_SCORE_THRESHOLD` | `20` | ルールベース判定の最小応答閾値 |
| `JUDGE_SCORE_FULL_RESPONSE` | `60` | 通常応答（full）を返すスコア閾値 |
| `JUDGE_SCORE_SHORT_ACK` | `30` | 相槌（short）を返すスコア閾値 |
| `COOLDOWN_SECONDS` | `120` | 応答後のクールダウン期間（秒）。-50 ペナルティ |
| `ENGAGEMENT_DURATION_SECONDS` | `300` | エンゲージメント期間（秒）。応答後この期間中はブースト |
| `ENGAGEMENT_BOOST` | `40` | エンゲージメント中のスコア加算値 |
| `JUDGE_KEYWORDS` | `""` | カンマ区切りのキーワード。マッチで +15 |

### LLM Judge（二次判定）

| 変数 | デフォルト | 説明 |
|------|-----------|------|
| `LLM_JUDGE_ENABLED` | `false` | LLM二次判定の有効化 |
| `JUDGE_MODEL` | `""` | 判定用モデル。空なら GEMINI_MODEL を使用 |
| `JUDGE_LLM_THRESHOLD_LOW` | `20` | この値以下はLLM判定せずスキップ |
| `JUDGE_LLM_THRESHOLD_HIGH` | `60` | この値以上はLLM判定せず即応答 |

### 応答多様性

| 変数 | デフォルト | 説明 |
|------|-----------|------|
| `RESPONSE_DIVERSITY_ENABLED` | `false` | スコアに応じた応答パターンの変化を有効化 |

### チャンネルコンテキスト（要約）

| 変数 | デフォルト | 説明 |
|------|-----------|------|
| `CHANNEL_CONTEXT_ENABLED` | `false` | 長期的な文脈維持の有効化 |
| `CHANNEL_CONTEXT_STORAGE_TYPE` | `memory` | 保存先 (`memory` / `firestore`) |
| `SUMMARIZE_EVERY_N_MESSAGES` | `20` | 要約を実行するメッセージ数間隔 |
| `SUMMARIZE_EVERY_N_MINUTES` | `15` | 要約を実行する時間間隔（分） |
| `SUMMARIZE_MODEL` | `""` | 要約生成に使用するモデル名 |

### チューニングガイド

- **応答しすぎる場合**: `JUDGE_SCORE_THRESHOLD` を上げる / `ENGAGEMENT_BOOST` を下げる / `COOLDOWN_SECONDS` を伸ばす
- **応答が少なすぎる場合**: `JUDGE_SCORE_THRESHOLD` を下げる / `ENGAGEMENT_BOOST` を上げる / `ENGAGEMENT_DURATION_SECONDS` を伸ばす
- **LLM Judgeの判定範囲を広げたい場合**: `JUDGE_LLM_THRESHOLD_LOW` を下げる / `JUDGE_LLM_THRESHOLD_HIGH` を下げる
