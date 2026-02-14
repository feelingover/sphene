---
applyTo: "**"
---
# Architecture

## Layer Structure

```
app.py → bot/discord_bot.py → bot/commands.py, bot/events.py
                                                    ↓
                               ai/conversation.py → ai/client.py, ai/tools.py → xivapi/client.py
                                                    ↓
                               utils/ (channel_config, firestore_client, text_utils)
                               log_utils/logger.py
```

## Key Components

### SpheneBot (`bot/discord_bot.py`)
Discord接続、コマンド/イベントハンドラ初期化、システムプロンプト読み込み

### Sphene (`ai/conversation.py`)
会話コンテキスト維持、OpenAI API対話、タイムアウト(30分)、最大10ターン、画像処理、エラーハンドリング

### Function Calling (`ai/tools.py`)
ツール定義(`TOOL_DEFINITIONS`)と実行関数マッピング(`TOOL_FUNCTIONS`)を集約。`func(**arguments)`で動的呼び出しするため、パラメータ追加時はデフォルト値で後方互換維持。

### XIVAPI (`xivapi/client.py`)
XIVAPI v2ゲームデータ検索。アイテム、アクション、レシピ、クエスト等の多種多様なコンテンツに対応。ジョブ名解決（日本語名→英語略称）、IL/レベル範囲フィルタ、2段階リクエストによる説明文補完を実装。

## Design Patterns

- **Per-user instances**: `user_conversations: defaultdict[str, Sphene]` でユーザーごとに独立した会話
- **Storage abstraction**: ローカル/Firestoreを環境変数で切り替え（チャンネル設定）。システムプロンプトはローカルファイル（k8s ConfigMap想定）のみ。
- **Error strategy map**: `_OPENAI_ERROR_HANDLERS: dict[Type[APIError], tuple]` でエラータイプ別処理
- **Prompt cache**: `_prompt_cache: dict[str, str]` でファイルIO削減
- **Thread offloading**: `asyncio.to_thread()`で同期API呼び出しをイベントループから退避

## Message Flow
ユーザー → Discord → イベントハンドラ(トリガー判定) → `asyncio.to_thread(process_conversation)` → Sphene.input_message → OpenAI API → Discord応答
