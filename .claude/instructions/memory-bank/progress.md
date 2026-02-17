---
applyTo: "**"
---
# Progress

## Completed Features

- **Vertex AI Native SDK (`google-genai`) 移行**: OpenAI互換APIを廃止し、最新SDKへ完全移行（Gemini 3/2.5対応、Grounding対応）
- 記憶機能（Phase 1+2+2A）: 短期記憶バッファ + 自律応答（ハイブリッドJudge）+ チャンネルコンテキスト + 応答多様性
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
- 記憶機能 Phase 2B: 応答品質向上（ペルソナ一貫性、コンテキスト活用の深化）
- 記憶機能 Phase 3: 中期記憶（Firestore保存 - ユーザープロファイル）
- 記憶機能 Phase 4: 長期記憶（ベクトル検索 - エピソード記憶）
- チャンネル固有プロンプト
- 使用統計・モニタリング
- CI/CD強化
- AsyncOpenAI移行（フルasync化）
