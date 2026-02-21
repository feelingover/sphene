---
applyTo: "**"
---
# Progress

## Completed Features

- **Vertex AI Native SDK (`google-genai`) 移行**: OpenAI互換APIを廃止し、最新SDKへ完全移行（Gemini 3/2.5対応、Grounding対応）
- **記憶機能 Phase 1**: 短期記憶バッファ（ChannelMessageBuffer、dequeリングバッファ）
- **記憶機能 Phase 2**: 自律応答（ハイブリッドJudge: RuleBasedJudge + LLMJudge）
- **記憶機能 Phase 2A**: チャンネルコンテキスト（ローリング要約）+ 応答多様性（3段階）+ Judge拡張（会話フロー考慮）
- **記憶機能 Phase 2B（コンテキスト統合）**: チャンネル単位履歴 + メンション/自律応答の共有コンテキスト注入
- **記憶機能 Phase 2B（ユーザープロファイル）**: 交流回数・関係性レベル・直近話題の記録と応答生成への注入
  - `UserProfile` dataclass + `UserProfileStore`（memory/local/firestore）
  - `familiarity_level`（stranger/acquaintance/regular/close）閾値ベース自動算出
  - `last_topic`: チャンネルコンテキストの topic_keywords を応答後に同期
  - `input_message()` に `user_profile` パラメータ追加
  - 15分ごとの定期永続化
- S3廃止 + Firestore移行: AWS依存完全削除、チャンネル設定をFirestoreに移行
- uv移行: pyproject.toml + uv.lock による依存管理、CI/Dockerfileのuv対応
- Discord応答（メンション、名前呼び、リプライ）、スラッシュコマンド
- Gemini-2.5-flash対話、会話履歴管理、マルチモーダル（画像）
- ツール呼び出しループ改善: `MAX_TOOL_CALL_ROUNDS`環境変数化（デフォルト5）+ ツールなし最終コール追加
- Function Calling → XIVAPI v2検索（アイテム・アクション・レシピ・クエスト等、詳細フィルタ対応）
- 翻訳（国旗リアクション: US/JP）
- チャンネル管理（全体/限定モード、追加/削除）
- ストレージ: ローカル/Firestore選択
- デプロイ: ローカル/Docker/Kubernetes
- PRテンプレート整備

## TODO

### Short-term
- 旧OpenAIコードの残骸（テストコード等）の完全クリーンアップ
- 統合テストのSDK対応

### Mid-term
- 記憶機能 Phase 3A: 反省会 + ファクトストア（Jaccard類似度キーワード検索）+ 自発的会話開始
- 記憶機能 Phase 3B: ベクトル検索（Vertex AI Embeddings）+ リッチプロファイル（LLMタグ抽出）
- チャンネル固有プロンプト
- 使用統計・モニタリング
- CI/CD強化
- AsyncOpenAI移行（フルasync化）
