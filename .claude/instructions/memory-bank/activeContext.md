---
applyTo: "**"
---
# Active Context

## Current State (2026/2)

- 全137テスト通過、カバレッジ86%
- Discord heartbeat blocking修正済み（`asyncio.to_thread()`）

## Recent Changes

### 2026/2: Discord Heartbeat Blocking修正
`bot/events.py`の`process_conversation()`と`utils/text_utils.py`の`translate_text()`で`asyncio.to_thread()`を使用し、同期ブロッキング呼び出しをスレッドプールに退避。フルasync化（AsyncOpenAI移行）は中期改善候補。

### 2026/2: XIVAPI検索条件拡張
`search_item`にジョブ名（`class_job`）・IL範囲（`ilvl_min`/`ilvl_max`）を追加。日本語ジョブ名/英語略称の両対応。フィルタ時limit=20、名前のみ時limit=5の動的制御。

### 2025/12/7: リファクタリング
セキュリティ修正、翻訳関数統合（30%削減）、60行関数→3分割、private関数に`_`プレフィックス統一、エラーログに`exc_info=True`追加。

## Key Decisions

| 日付 | 決定 | 理由 |
|------|------|------|
| 2026/2 | `asyncio.to_thread()`で最小修正 | 2ファイル10行で全ブロッキングポイントをカバー。フルasync化は中期候補 |
| 2026/2 | XIVAPI全パラメータにデフォルト値 | `func(**arguments)`動的呼び出しとの後方互換性維持 |
| 2026/2 | ジョブ名解決を二段階方式に | 日本語名→略称マッピング + 英語略称バリデーション |
| 2025/12/7 | ユーザー向けエラーメッセージから内部詳細を除外 | 情報漏洩リスク低減 |
| 2025/12/7 | 関数長20-30行目安、60行超で分割 | 単一責任、可読性、テスト容易性 |

## Open Issues

1. **API制限**: 高負荷時のレート制限対応（基本リトライは実装済み）
2. **コスト最適化**: モデル選択、プロンプト最適化、キャッシング
3. **Dockerfile最適化**: マルチステージビルド未実施
