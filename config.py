import os

from dotenv import load_dotenv

load_dotenv()

# ログレベル設定（デフォルトはINFO）
LOG_LEVEL: str = str(os.getenv("LOG_LEVEL", "INFO"))
# ログフォーマット設定（"json" または "text"）
LOG_FORMAT: str = str(os.getenv("LOG_FORMAT", "json"))

# インスタンス識別子（マルチテナント識別のため必須）
INSTANCE_NAME: str = os.getenv("INSTANCE_NAME", "")
if not INSTANCE_NAME:
    raise ValueError("INSTANCE_NAME is required")

BOT_MODEL: str = os.getenv("BOT_MODEL", "google/gemini-4-hydrogen")
BOT_LITE_MODEL: str = os.getenv("BOT_LITE_MODEL", "google/gemini-4-hydrogen")

# Vertex AI設定
VERTEX_AI_PROJECT_ID: str = os.getenv("VERTEX_AI_PROJECT_ID", "")
VERTEX_AI_LOCATION: str = os.getenv("VERTEX_AI_LOCATION", "global")
# Router LLM設定 (issue #94)
# ユーザーの意図を軽量LLMで判定し、grounding/function_calling/noneを動的選択する
ROUTER_ENABLED: bool = os.getenv("ROUTER_ENABLED", "true").lower() == "true"

DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKEN is required")
BOT_NAME: str = str(os.getenv("BOT_NAME", "スフェーン"))
COMMAND_GROUP_NAME: str = str(os.getenv("COMMAND_GROUP_NAME", INSTANCE_NAME))
SYSTEM_PROMPT_FILENAME: str = str(os.getenv("SYSTEM_PROMPT_FILENAME", "system.txt"))

# ストレージタイプ（local または firestore）
STORAGE_TYPE: str = str(os.getenv("STORAGE_TYPE", "local"))

# ローカルストレージのディレクトリ（STORAGE_TYPE=local 時のチャンネル設定などの保存先）
LOCAL_STORAGE_DIR: str = str(os.getenv("LOCAL_STORAGE_DIR", "storage"))

# システムプロンプトのファイルパス
SYSTEM_PROMPT_PATH: str = str(os.getenv("SYSTEM_PROMPT_PATH", "storage/system.txt"))

# Firestoreネームスペース（マルチテナント対応）
FIRESTORE_NAMESPACE: str = os.getenv("FIRESTORE_NAMESPACE", INSTANCE_NAME)


def get_collection_name(base_name: str) -> str:
    """ネームスペース付きFirestoreコレクション名を返す"""
    if FIRESTORE_NAMESPACE:
        return f"{FIRESTORE_NAMESPACE}_{base_name}"
    return base_name


FIRESTORE_COLLECTION_CHANNEL_CONFIGS: str = get_collection_name("channel_configs")
FIRESTORE_COLLECTION_USER_PROFILES: str = get_collection_name("user_profiles")
FIRESTORE_COLLECTION_CHANNEL_CONTEXTS: str = get_collection_name("channel_contexts")
FIRESTORE_COLLECTION_FACTS: str = get_collection_name("facts")
FIRESTORE_COLLECTION_FACTS_ARCHIVE: str = get_collection_name("facts_archive")

# === AI会話設定 ===
MAX_TOOL_CALL_ROUNDS: int = int(os.getenv("MAX_TOOL_CALL_ROUNDS", "15"))
# ツール結果1件あたりの最大文字数（JSON化後）。超えた分は切り詰めて履歴の肥大化を防ぐ
MAX_TOOL_RESULT_CHARS: int = int(os.getenv("MAX_TOOL_RESULT_CHARS", "10000"))

# メンション・名前呼び・リプライによる会話のレート制限（ウィンドウ内の上限回数。0で無効）
MENTION_RATE_LIMIT_PER_USER: int = int(os.getenv("MENTION_RATE_LIMIT_PER_USER", "5"))
MENTION_RATE_LIMIT_PER_CHANNEL: int = int(os.getenv("MENTION_RATE_LIMIT_PER_CHANNEL", "20"))
MENTION_RATE_LIMIT_WINDOW_SECONDS: int = int(os.getenv("MENTION_RATE_LIMIT_WINDOW_SECONDS", "60"))
# 国旗リアクション翻訳の重複抑止期間（秒）。同じメッセージ×言語はこの間1回だけ翻訳する
TRANSLATION_DEDUP_SECONDS: int = int(os.getenv("TRANSLATION_DEDUP_SECONDS", "3600"))
# 国旗リアクション翻訳のレート制限（リアクションしたユーザー単位/チャンネル単位、ウィンドウ内の上限回数。0で無効）
TRANSLATION_RATE_LIMIT_PER_USER: int = int(os.getenv("TRANSLATION_RATE_LIMIT_PER_USER", "5"))
TRANSLATION_RATE_LIMIT_PER_CHANNEL: int = int(os.getenv("TRANSLATION_RATE_LIMIT_PER_CHANNEL", "15"))
TRANSLATION_RATE_LIMIT_WINDOW_SECONDS: int = int(
    os.getenv("TRANSLATION_RATE_LIMIT_WINDOW_SECONDS", "60")
)
# リアクション処理のエラーをチャンネルに通知する最短間隔（秒）。連投を防ぐ
REACTION_ERROR_NOTIFY_COOLDOWN_SECONDS: int = int(
    os.getenv("REACTION_ERROR_NOTIFY_COOLDOWN_SECONDS", "300")
)

# Gen AI APIの1リクエストあたりのタイムアウト（秒）
# 混雑時は長く待つと正確な応答が返ることが多いため長めに設定している
GENAI_REQUEST_TIMEOUT_SECONDS: int = int(os.getenv("GENAI_REQUEST_TIMEOUT_SECONDS", "300"))

# Gen AI APIのリトライ設定（チャンネルロックの長時間保持を防ぐため、全体の所要時間に上限を設ける）
# MAIN: 会話応答（ツール呼び出しループ全体）・要約・反省会
#   TIMEOUT_RETRIES はタイムアウト系エラーのリトライ回数（429/5xx は MAX_ATTEMPTS まで試行）
#   TOTAL_TIMEOUT はツールループを含む1回の応答生成全体の上限秒数
GENAI_MAIN_MAX_ATTEMPTS: int = int(os.getenv("GENAI_MAIN_MAX_ATTEMPTS", "5"))
GENAI_MAIN_TIMEOUT_RETRIES: int = int(os.getenv("GENAI_MAIN_TIMEOUT_RETRIES", "1"))
GENAI_MAIN_TOTAL_TIMEOUT_SECONDS: int = int(os.getenv("GENAI_MAIN_TOTAL_TIMEOUT_SECONDS", "600"))
# LIGHT: Router・LLM Judge・相槌（応答前に同期的に待つため短く設定する）
GENAI_LIGHT_REQUEST_TIMEOUT_SECONDS: int = int(
    os.getenv("GENAI_LIGHT_REQUEST_TIMEOUT_SECONDS", "30")
)
GENAI_LIGHT_MAX_ATTEMPTS: int = int(os.getenv("GENAI_LIGHT_MAX_ATTEMPTS", "2"))
GENAI_LIGHT_TIMEOUT_RETRIES: int = int(os.getenv("GENAI_LIGHT_TIMEOUT_RETRIES", "0"))
GENAI_LIGHT_TOTAL_TIMEOUT_SECONDS: int = int(
    os.getenv("GENAI_LIGHT_TOTAL_TIMEOUT_SECONDS", "45")
)
# 上限時刻までの残り時間がこの秒数未満なら、新たなリクエストを送らずに打ち切る
GENAI_MIN_REQUEST_TIMEOUT_SECONDS: int = int(
    os.getenv("GENAI_MIN_REQUEST_TIMEOUT_SECONDS", "5")
)

# Thinkingレベル（"" = モデルのデフォルト / "minimal" / "low" / "medium" / "high"）
# MAIN: 会話応答・ツール呼び出しループ
# LIGHT: Router・LLM Judge・相槌・要約・反省会・翻訳などの軽量タスク
MAIN_THINKING_LEVEL: str = os.getenv("MAIN_THINKING_LEVEL", "").strip().lower()
LIGHT_THINKING_LEVEL: str = os.getenv("LIGHT_THINKING_LEVEL", "low").strip().lower()

# === 記憶機能設定 ===

# 短期記憶（チャンネルメッセージバッファ）
CHANNEL_BUFFER_SIZE: int = int(os.getenv("CHANNEL_BUFFER_SIZE", "50"))
CHANNEL_BUFFER_TTL_MINUTES: int = int(os.getenv("CHANNEL_BUFFER_TTL_MINUTES", "30"))

# === 機能グループフラグ ===
# VANGUARD: 自律応答・LLM Judge・応答多様性・リアクション を一括制御
VANGUARD_ENABLED: bool = os.getenv("VANGUARD_ENABLED", "true").lower() == "true"
# LIVING_MEMORY: チャンネルコンテキスト・ユーザープロファイル・ユーザープロファイルタグ・反省会 を一括制御
LIVING_MEMORY_ENABLED: bool = os.getenv("LIVING_MEMORY_ENABLED", "true").lower() == "true"

# 自律応答
JUDGE_SCORE_THRESHOLD: int = int(os.getenv("JUDGE_SCORE_THRESHOLD", "20"))
JUDGE_SCORE_FULL_RESPONSE: int = int(os.getenv("JUDGE_SCORE_FULL_RESPONSE", "60"))
JUDGE_SCORE_SHORT_ACK: int = int(os.getenv("JUDGE_SCORE_SHORT_ACK", "30"))
COOLDOWN_SECONDS: int = int(os.getenv("COOLDOWN_SECONDS", "120"))
ENGAGEMENT_DURATION_SECONDS: int = int(os.getenv("ENGAGEMENT_DURATION_SECONDS", "300"))
ENGAGEMENT_BOOST: int = int(os.getenv("ENGAGEMENT_BOOST", "40"))
JUDGE_KEYWORDS: str = os.getenv("JUDGE_KEYWORDS", "")

# LLM Judge（二次判定）
JUDGE_LLM_THRESHOLD_LOW: int = int(os.getenv("JUDGE_LLM_THRESHOLD_LOW", "20"))
JUDGE_LLM_THRESHOLD_HIGH: int = int(os.getenv("JUDGE_LLM_THRESHOLD_HIGH", "60"))

# === チャンネルコンテキスト設定 ===
SUMMARIZE_EVERY_N_MESSAGES: int = int(os.getenv("SUMMARIZE_EVERY_N_MESSAGES", "20"))
SUMMARIZE_EVERY_N_MINUTES: int = int(os.getenv("SUMMARIZE_EVERY_N_MINUTES", "15"))

# リアクション機能
# should_react=True になる最低スコア閾値（JUDGE_SCORE_THRESHOLD より低く設定する）
JUDGE_REACT_THRESHOLD: int = int(os.getenv("JUDGE_REACT_THRESHOLD", "5"))

# === ユーザープロファイル設定 (Phase 2B) ===
FAMILIARITY_THRESHOLD_ACQUAINTANCE: int = int(os.getenv("FAMILIARITY_THRESHOLD_ACQUAINTANCE", "6"))
FAMILIARITY_THRESHOLD_REGULAR: int = int(os.getenv("FAMILIARITY_THRESHOLD_REGULAR", "31"))
FAMILIARITY_THRESHOLD_CLOSE: int = int(os.getenv("FAMILIARITY_THRESHOLD_CLOSE", "101"))

# === ユーザープロファイル拡張設定 (Phase 3B) ===
USER_PROFILE_TAGS_LIMIT: int = int(os.getenv("USER_PROFILE_TAGS_LIMIT", "30"))
USER_PROFILE_FACTS_LIMIT: int = int(os.getenv("USER_PROFILE_FACTS_LIMIT", "30"))
CHANNELS_ACTIVE_LIMIT: int = int(os.getenv("CHANNELS_ACTIVE_LIMIT", "20"))

# === ファクトストア設定 (Phase 3A) ===
FACT_STORE_MAX_FACTS_PER_CHANNEL: int = int(os.getenv("FACT_STORE_MAX_FACTS_PER_CHANNEL", "100"))
FACT_DECAY_HALF_LIFE_DAYS: int = int(os.getenv("FACT_DECAY_HALF_LIFE_DAYS", "30"))
# ユーザーIDが一致するファクトのスコアブースト倍率
FACT_USER_BOOST_FACTOR: float = float(os.getenv("FACT_USER_BOOST_FACTOR", "1.5"))
# ファクト忘却クリーンアップ設定 (Phase 3B)
# effective_relevance_score がこの値を下回るファクトを定期削除する
FACT_STORE_CLEANUP_THRESHOLD: float = float(os.getenv("FACT_STORE_CLEANUP_THRESHOLD", "0.05"))
# 参照頻度ブーストの重み係数（log1p(access_count) * weight がスコアに加算される）
FACT_ACCESS_BOOST_WEIGHT: float = float(os.getenv("FACT_ACCESS_BOOST_WEIGHT", "0.1"))
# 削除ファクトをアーカイブストレージに保存するか否か（デフォルト: ログ記録のみ）
FACT_STORE_ARCHIVE_ENABLED: bool = os.getenv("FACT_STORE_ARCHIVE_ENABLED", "false").lower() == "true"
# アーカイブの最大保持件数（古い順に切り捨て。Firestore ではサイズ上限でも別途切り捨てる）
FACT_ARCHIVE_MAX_ENTRIES: int = int(os.getenv("FACT_ARCHIVE_MAX_ENTRIES", "500"))

# === 反省会エンジン設定 (Phase 3A) ===
REFLECTION_LULL_MINUTES: int = int(os.getenv("REFLECTION_LULL_MINUTES", "10"))
REFLECTION_MIN_MESSAGES: int = int(os.getenv("REFLECTION_MIN_MESSAGES", "10"))
# バッファ量ベースの反省会トリガー閾値。
# CHANNEL_BUFFER_SIZE 以下の値を設定すること（それを超えると絶対に発動しない）。
REFLECTION_MAX_BUFFER_MESSAGES: int = int(os.getenv("REFLECTION_MAX_BUFFER_MESSAGES", "30"))
# 反省会がこの回数連続で失敗したら、そのメッセージ群は諦めてチェックポイントを進める
REFLECTION_MAX_FAILURES: int = int(os.getenv("REFLECTION_MAX_FAILURES", "3"))

# === 記憶系LLM（要約・反省会）の失敗時バックオフ ===
# n回連続失敗後は BASE * 2^(n-1) 秒（上限 MAX）再実行しない
MEMORY_LLM_BACKOFF_BASE_SECONDS: int = int(os.getenv("MEMORY_LLM_BACKOFF_BASE_SECONDS", "300"))
MEMORY_LLM_BACKOFF_MAX_SECONDS: int = int(os.getenv("MEMORY_LLM_BACKOFF_MAX_SECONDS", "3600"))

# === 記憶ストアの読み込み失敗時バックオフ ===
# 読み込みに失敗したキー（チャンネル・プロファイル）は、n回連続失敗後 BASE * 2^(n-1) 秒（上限 MAX）再読み込みしない
STORAGE_LOAD_BACKOFF_BASE_SECONDS: int = int(os.getenv("STORAGE_LOAD_BACKOFF_BASE_SECONDS", "30"))
STORAGE_LOAD_BACKOFF_MAX_SECONDS: int = int(os.getenv("STORAGE_LOAD_BACKOFF_MAX_SECONDS", "600"))

# === Embedding設定 (Phase 3B) ===
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-004")
VECTOR_SEARCH_ENABLED: bool = os.getenv("VECTOR_SEARCH_ENABLED", "false").lower() == "true"
HYBRID_ALPHA: float = float(os.getenv("HYBRID_ALPHA", "0.5"))  # ベクトル/キーワードスコアのバランス係数
# ファクト重複判定のコサイン類似度閾値（両方にEmbeddingがある場合のみ使用）
FACT_DEDUP_SIMILARITY_THRESHOLD: float = float(os.getenv("FACT_DEDUP_SIMILARITY_THRESHOLD", "0.95"))


# === 廃止済みの環境変数 ===
# 設定されていても無視される。起動時に警告して、ConfigMap 等の設定の残骸に気づけるようにする
_VANGUARD_HINT = "VANGUARD_ENABLED に統合されました"
_LIVING_MEMORY_HINT = "LIVING_MEMORY_ENABLED に統合されました"
_MODEL_HINT = "機能別のモデル指定は廃止。BOT_MODEL / BOT_LITE_MODEL を使ってください"
DEPRECATED_ENV_VARS: dict[str, str] = {
    "AUTONOMOUS_RESPONSE_ENABLED": _VANGUARD_HINT,
    "LLM_JUDGE_ENABLED": _VANGUARD_HINT,
    "RESPONSE_DIVERSITY_ENABLED": _VANGUARD_HINT,
    "REACTION_ENABLED": _VANGUARD_HINT,
    "MEMORY_ENABLED": _LIVING_MEMORY_HINT,
    "CHANNEL_CONTEXT_ENABLED": _LIVING_MEMORY_HINT,
    "USER_PROFILE_ENABLED": _LIVING_MEMORY_HINT,
    "USER_PROFILE_TAGS_ENABLED": _LIVING_MEMORY_HINT,
    "REFLECTION_ENABLED": _LIVING_MEMORY_HINT,
    "PROACTIVE_CONVERSATION_ENABLED": "自発会話機能は削除されました（issue #104）",
    "JUDGE_MODEL": _MODEL_HINT,
    "SUMMARIZE_MODEL": _MODEL_HINT,
    "REFLECTION_MODEL": _MODEL_HINT,
    "GEMINI_MODEL": "BOT_MODEL に置き換わりました",
    "CHANNEL_CONFIG_STORAGE_TYPE": "STORAGE_TYPE に統合されました",
    "FIRESTORE_COLLECTION_NAME": "コレクション名は FIRESTORE_NAMESPACE から自動決定されます",
}


def find_deprecated_env_vars() -> list[tuple[str, str]]:
    """設定されている廃止済みの環境変数を返す

    Returns:
        (環境変数名, 移行先の案内) のリスト
    """
    return [(name, hint) for name, hint in DEPRECATED_ENV_VARS.items() if name in os.environ]
