# 🧩 Sphene Discord Bot システムパターン

## システムアーキテクチャ

Sphene Discord Botは、モジュール性と拡張性を重視した構造になっています。主要コンポーネントは次のように分かれています：

```mermaid
graph TD
    A[app.py] --> B[bot/discord_bot.py]
    B --> C[bot/commands.py]
    B --> D[bot/events.py]
    D --> E[ai/conversation.py]
    E --> F[ai/client.py]
    E --> G[utils/s3_utils.py]
    E --> H[utils/text_utils.py]
    B --> I[utils/channel_config.py]
    
    style A fill:#f9f,stroke:#333,stroke-width:2px
    style B fill:#bbf,stroke:#333,stroke-width:2px
    style C fill:#ddf,stroke:#333,stroke-width:2px
    style D fill:#ddf,stroke:#333,stroke-width:2px
    style E fill:#fdd,stroke:#333,stroke-width:2px
    style F fill:#fdd,stroke:#333,stroke-width:2px
    style G fill:#dfd,stroke:#333,stroke-width:2px
    style H fill:#dfd,stroke:#333,stroke-width:2px
    style I fill:#dfd,stroke:#333,stroke-width:2px
```

### レイヤー構成

1. **エントリーポイント層**
   - `app.py` - アプリケーションのエントリーポイント

2. **ボットコア層**
   - `bot/discord_bot.py` - Discord Botのコア機能とセットアップ
   - `bot/commands.py` - スラッシュコマンド定義
   - `bot/events.py` - Discordイベントハンドラ

3. **AI処理層**
   - `ai/conversation.py` - 会話管理ロジック
   - `ai/client.py` - OpenAI APIクライアント

4. **ユーティリティ層**
   - `utils/channel_config.py` - チャンネル設定管理
   - `utils/s3_utils.py` - S3関連ユーティリティ
   - `utils/text_utils.py` - テキスト処理ユーティリティ

5. **ロギング層**
   - `log_utils/logger.py` - ロギング設定

## 主要コンポーネントと関係

### 1. Botコア (SpheneBot)

SpheneBot クラスはアプリケーションの中心的な役割を果たし、以下の責務を持ちます:

- Discord APIとの接続確立
- コマンドとイベントハンドラの初期化
- システムプロンプトの読み込み検証
- ボットのライフサイクル管理

```mermaid
classDiagram
    class SpheneBot {
        +bot: commands.Bot
        +__init__()
        -_setup()
        +run()
    }
```

### 2. 会話管理 (Sphene)

Sphene クラスは会話の状態と履歴を管理し、以下の責務を持ちます:

- 会話コンテキストの維持
- メッセージの処理
- タイムアウト管理
- OpenAI APIとの対話
- エラーハンドリング
- 画像処理

```mermaid
classDiagram
    class Sphene {
        +system: ChatCompletionSystemMessageParam
        +input_list: list[ChatCompletionMessageParam]
        +logs: list[ChatCompletion]
        +last_interaction: datetime
        +__init__(system_setting: str)
        +is_expired() bool
        +update_interaction_time()
        +trim_conversation_history()
        +input_message(input_text, image_urls) str
        -_handle_openai_error(error) str
        -_call_openai_api(with_images) tuple[bool, str]
        -_process_images(image_urls) list[dict]
        -_download_and_encode_image(url) str
    }
```

### 3. システムプロンプト管理

システムプロンプトのロード機能は以下のパターンで実装されています:

- キャッシュ機構による効率化
- ローカルファイルとS3からの読み込み
- フォールバック戦略
- エラーハンドリング

```mermaid
sequenceDiagram
    participant A as アプリケーション
    participant C as プロンプトキャッシュ
    participant L as ローカルストレージ
    participant S as S3ストレージ
    
    A->>C: load_system_prompt()
    alt キャッシュ有り && 強制再読込でない
        C-->>A: キャッシュから返す
    else キャッシュ無し || 強制再読込
        alt ストレージタイプ == S3
            A->>S: S3からロード試行
            alt S3ロード成功
                S-->>A: プロンプト内容
            else S3ロード失敗
                A->>L: ローカルからロード試行
                L-->>A: プロンプト内容
            end
        else ストレージタイプ == ローカル
            A->>L: ローカルからロード試行
            L-->>A: プロンプト内容
        end
        A->>C: キャッシュに保存
        C-->>A: プロンプト内容
    end
```

## デザインパターン

### 1. シングルトンパターン

`user_conversations` 辞書を使用して、ユーザーごとに一意の会話インスタンスを保持します。
これによりユーザー間の会話が混ざることなく、適切に状態を維持できます。

```python
# ユーザーごとの会話インスタンスを保持する辞書
user_conversations: defaultdict[str, Sphene] = defaultdict(
    lambda: Sphene(system_setting=load_system_prompt())
)
```

### 2. ファクトリーパターン

`load_system_prompt` 関数は、ストレージタイプ（ローカルまたはS3）に基づいて適切なプロンプト読み込み処理を選択し、
プロンプトオブジェクトを生成するファクトリーとして機能します。

### 3. ストラテジーパターン

エラーハンドリングでは各エラータイプと対応する処理戦略をマッピングし、
実行時に適切なエラー処理を選択するストラテジーパターンを採用しています。

```python
_OPENAI_ERROR_HANDLERS: dict[Type[APIError], tuple[int, str, str]] = {
    AuthenticationError: (...),
    PermissionDeniedError: (...),
    # 他のエラータイプ
}
```

### 4. デコレータパターン

discord.pyの機能を活用したイベントハンドリングやコマンド処理では、
Pythonのデコレータパターンを使用して宣言的にハンドラを定義しています。

### 5. キャッシュパターン

システムプロンプトのロードでは、キャッシュパターンを使用して
頻繁なファイルIO操作を回避し、パフォーマンスを向上させています。

```python
# プロンプトのキャッシュ
_prompt_cache: dict[str, str] = {}
```

## 重要な実装パス

### 1. メッセージ処理フロー

```mermaid
sequenceDiagram
    participant U as ユーザー
    participant D as Discord
    participant E as イベントハンドラ
    participant S as Sphene会話管理
    participant O as OpenAI API
    
    U->>D: メッセージ送信
    D->>E: on_messageイベント発火
    E->>E: メッセージ種別判定
    alt メンション || 名前呼び || リプライ
        E->>S: input_message()
        S->>S: 会話期限確認
        S->>S: ユーザーメッセージ追加
        alt 画像添付あり
            S->>S: 画像処理
        end
        S->>O: APIリクエスト
        O-->>S: 応答返却
        S->>S: 応答を履歴に追加
        S->>E: 応答返却
        E->>D: 応答送信
        D->>U: 応答表示
    end
```

### 2. コマンド処理フロー

```mermaid
sequenceDiagram
    participant U as ユーザー
    participant D as Discord
    participant C as コマンドハンドラ
    participant CH as チャンネル設定管理
    participant S as Sphene会話管理
    
    U->>D: スラッシュコマンド実行
    D->>C: コマンドイベント発火
    alt reset
        C->>S: ユーザー会話リセット
    else mode
        C->>CH: 評価モード切替
    else channels
        C->>CH: チャンネルリスト表示
    else addlist/removelist/clearlist
        C->>CH: チャンネル設定変更
    else reload_prompt
        C->>S: システムプロンプト再読込
    end
    C->>D: 結果返却
    D->>U: 結果表示
```

### 3. エラーハンドリングフロー

```mermaid
sequenceDiagram
    participant S as Sphene会話管理
    participant A as OpenAI API
    participant E as エラーハンドラ
    participant U as ユーザー
    
    S->>A: APIリクエスト
    alt 成功
        A-->>S: 正常応答
    else エラー発生
        A-->>S: エラー例外
        S->>E: _handle_openai_error()
        E->>E: エラー種別特定
        E->>E: 適切なログ出力
        E-->>S: ユーザー向けエラーメッセージ
    end
    S-->>U: 応答またはエラーメッセージ
```

## 拡張性とメンテナンス性

1. **モジュール分割**
   - 責務ごとに適切に分離されたモジュール構造
   - 各レイヤー間の明確なインターフェース

2. **設定管理**
   - 環境変数を使用した外部設定
   - ストレージオプションの抽象化

3. **エラー処理**
   - 階層的なエラーハンドリング
   - ユーザーフレンドリーなエラーメッセージ
   - 詳細なログ記録

4. **型安全性**
   - Pythonの型ヒントを活用
   - 明示的な型キャスト

5. **テスト容易性**
   - 適切に分離されたコンポーネント
   - 依存関係の明確な構造
