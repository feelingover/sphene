---
applyTo: "**"
---
# Progress

## Completed Features

- S3廃止 + Firestore移行: AWS依存完全削除、チャンネル設定をFirestoreに移行
- uv移行: pyproject.toml + uv.lock による依存管理、CI/Dockerfileのuv対応
- Discord応答（メンション、名前呼び、リプライ）、スラッシュコマンド
- GPT-4o-mini対話、会話履歴管理、マルチモーダル（画像）
- Function Calling → XIVAPI v2検索（アイテム・アクション・レシピ・クエスト等、詳細フィルタ対応）
- 翻訳（国旗リアクション: US/JP）
- チャンネル管理（全体/限定モード、追加/削除）
- ストレージ: ローカル/Firestore選択（システムプロンプトはローカルのみ）
- デプロイ: ローカル/Docker/Kubernetes
- Vertex AI OpenAI互換API対応: `AI_PROVIDER`環境変数でOpenAI/Vertex AI切替、Workload Identity自動認証

## TODO

### Short-term
- パフォーマンス最適化
- 統合テスト充実

### Mid-term
- チャンネル固有プロンプト
- 使用統計・モニタリング
- CI/CD強化
- AsyncOpenAI移行（フルasync化）
