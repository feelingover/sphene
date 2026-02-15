# 自律応答システム

## アーキテクチャ

```
メッセージ受信
│
├─ @メンション / リプライ / 名前呼び → 即応答 + エンゲージメント記録
│
└─ それ以外 → RuleBasedJudge でスコアリング
                  │
                  ├─ スコア >= LLM_THRESHOLD_HIGH → 即応答
                  ├─ スコア <= LLM_THRESHOLD_LOW  → スキップ
                  └─ 中間スコア → LLM Judge で二次判定
                                    │
                                    ├─ respond: true  → 応答
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
| クールダウン中 | -50 | 応答後 COOLDOWN_SECONDS 以内 |

最終スコアは 0-100 にクランプされる。

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

中間スコア帯のメッセージに対して、安価なLLMで「自然に参加すべきか」を二次判定する。
直近15メッセージのコンテキストを渡し、JSON形式で `{"respond": true/false, "reason": "..."}` を返す。

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
| `JUDGE_SCORE_THRESHOLD` | `60` | ルールベース判定の応答閾値 |
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
| `JUDGE_LLM_THRESHOLD_HIGH` | `80` | この値以上はLLM判定せず即応答 |

### チューニングガイド

- **応答しすぎる場合**: `JUDGE_SCORE_THRESHOLD` を上げる / `ENGAGEMENT_BOOST` を下げる / `COOLDOWN_SECONDS` を伸ばす
- **応答が少なすぎる場合**: `JUDGE_SCORE_THRESHOLD` を下げる / `ENGAGEMENT_BOOST` を上げる / `ENGAGEMENT_DURATION_SECONDS` を伸ばす
- **LLM Judgeの判定範囲を広げたい場合**: `JUDGE_LLM_THRESHOLD_LOW` を下げる / `JUDGE_LLM_THRESHOLD_HIGH` を下げる
