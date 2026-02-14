---
applyTo: "**"
---
# Active Context

## Current State (2026/2)

- 全テスト通過、カバレッジ86%
- Discord heartbeat blocking修正済み（`asyncio.to_thread()`）

## Recent Changes

### 2026/2: S3廃止 + Firestore移行
AWS依存（boto3）を完全削除し、GCPベース（google-cloud-firestore）に一本化。
- システムプロンプト: S3/ローカル切り替え → ローカルのみ（k8s configmapマウント前提）
- チャンネル設定: S3 → Firestore（開発環境はローカルファイル維持）
- 削除: `utils/aws_clients.py`, `utils/s3_utils.py`, `PROMPT_STORAGE_TYPE`, `S3_*`環境変数
- 追加: `utils/firestore_client.py`, `FIRESTORE_COLLECTION_NAME`環境変数
- マイグレーションスクリプト: `scripts/migrate_s3_to_firestore.py`

### 2026/2: uv移行
requirements.txt/requirements-dev.txt → pyproject.toml + uv.lock。pytest.ini → pyproject.toml統合。Dockerfile・CI・run_tests.shをuv対応に更新。

### 2026/2: Discord Heartbeat Blocking修正
`bot/events.py`の`process_conversation()`と`utils/text_utils.py`の`translate_text()`で`asyncio.to_thread()`を使用し、同期ブロッキング呼び出しをスレッドプールに退避。フルasync化（AsyncOpenAI移行）は中期改善候補。

### 2026/2: XIVAPI v2連携の大幅拡張
`search_item`に加えて、以下の検索機能を追加。
- `search_action`: アクション（スキル）検索。説明文取得のために2段階リクエスト（search → sheet/Action/{id}）を実装。
- `search_recipe`: 製作レシピ検索。クラフタージョブ絞り込み、必要素材一覧の取得に対応。
- `search_game_content`: クエスト、アチーブメント、FATE、マウント、ミニオン、ステータスの汎用検索。
- DQL（Data Query Language）の最適化: 日本語検索時に `Name@ja~"query"` を使用するように改善。
- 共通ヘルパーの抽出: クエリ構築、API実行、エラーレスポンス作成の共通化。

## Key Decisions

| 日付 | 決定 | 理由 |
|------|------|------|
| 2026/2 | S3廃止→Firestore移行 | k8sデプロイ方針変更に伴いGCPに一本化 |
| 2026/2 | システムプロンプトはローカルのみ | k8s configmapマウントで十分 |
| 2026/2 | `asyncio.to_thread()`で最小修正 | 2ファイル10行で全ブロッキングポイントをカバー。フルasync化は中期候補 |
| 2026/2 | XIVAPI全パラメータにデフォルト値 | `func(**arguments)`動的呼び出しとの後方互換性維持 |

## Open Issues

1. **API制限**: 高負荷時のレート制限対応（基本リトライは実装済み）
2. **コスト最適化**: モデル選択、プロンプト最適化、キャッシング
3. **AsyncOpenAI移行**: フルasync化（中期候補）
