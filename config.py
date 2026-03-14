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

BOT_MODEL: str = os.getenv("BOT_MODEL", "google/gemini-2.5-flash")
BOT_LITE_MODEL: str = os.getenv("BOT_LITE_MODEL", "google/gemini-2.5-flash")

# Vertex AI設定
VERTEX_AI_PROJECT_ID: str = os.getenv("VERTEX_AI_PROJECT_ID", "")
VERTEX_AI_LOCATION: str = os.getenv("VERTEX_AI_LOCATION", "asia-northeast1")
# Router LLM設定 (issue #94)
# ユーザーの意図を軽量LLMで判定し、grounding/function_calling/noneを動的選択する
ROUTER_ENABLED: bool = os.getenv("ROUTER_ENABLED", "true").lower() == "true"

DISCORD_TOKEN: str = str(os.getenv("DISCORD_TOKEN"))
BOT_NAME: str = str(os.getenv("BOT_NAME", "スフェーン"))
COMMAND_GROUP_NAME: str = str(os.getenv("COMMAND_GROUP_NAME", INSTANCE_NAME))
SYSTEM_PROMPT_FILENAME: str = str(os.getenv("SYSTEM_PROMPT_FILENAME", "system.txt"))

# ストレージタイプ（local または firestore）
STORAGE_TYPE: str = str(os.getenv("STORAGE_TYPE", "local"))

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
MAX_TOOL_CALL_ROUNDS: int = int(os.getenv("MAX_TOOL_CALL_ROUNDS", "5"))

# === 記憶機能設定 ===

# 短期記憶（チャンネルメッセージバッファ）
CHANNEL_BUFFER_SIZE: int = int(os.getenv("CHANNEL_BUFFER_SIZE", "50"))
CHANNEL_BUFFER_TTL_MINUTES: int = int(os.getenv("CHANNEL_BUFFER_TTL_MINUTES", "30"))

# 自律応答
# 依存: LLM_JUDGE_ENABLED はこのフラグが True のときのみ有効
AUTONOMOUS_RESPONSE_ENABLED: bool = (
    os.getenv("AUTONOMOUS_RESPONSE_ENABLED", "false").lower() == "true"
)
JUDGE_SCORE_THRESHOLD: int = int(os.getenv("JUDGE_SCORE_THRESHOLD", "20"))
JUDGE_SCORE_FULL_RESPONSE: int = int(os.getenv("JUDGE_SCORE_FULL_RESPONSE", "60"))
JUDGE_SCORE_SHORT_ACK: int = int(os.getenv("JUDGE_SCORE_SHORT_ACK", "30"))
COOLDOWN_SECONDS: int = int(os.getenv("COOLDOWN_SECONDS", "120"))
ENGAGEMENT_DURATION_SECONDS: int = int(os.getenv("ENGAGEMENT_DURATION_SECONDS", "300"))
ENGAGEMENT_BOOST: int = int(os.getenv("ENGAGEMENT_BOOST", "40"))
JUDGE_KEYWORDS: str = os.getenv("JUDGE_KEYWORDS", "")

# LLM Judge（二次判定）
# 依存: AUTONOMOUS_RESPONSE_ENABLED=True が必要
LLM_JUDGE_ENABLED: bool = (
    os.getenv("LLM_JUDGE_ENABLED", "false").lower() == "true"
)
JUDGE_LLM_THRESHOLD_LOW: int = int(os.getenv("JUDGE_LLM_THRESHOLD_LOW", "20"))
JUDGE_LLM_THRESHOLD_HIGH: int = int(os.getenv("JUDGE_LLM_THRESHOLD_HIGH", "60"))

# === チャンネルコンテキスト設定 ===
CHANNEL_CONTEXT_ENABLED: bool = (
    os.getenv("CHANNEL_CONTEXT_ENABLED", "false").lower() == "true"
)
SUMMARIZE_EVERY_N_MESSAGES: int = int(os.getenv("SUMMARIZE_EVERY_N_MESSAGES", "20"))
SUMMARIZE_EVERY_N_MINUTES: int = int(os.getenv("SUMMARIZE_EVERY_N_MINUTES", "15"))

# === 応答多様性設定 ===
RESPONSE_DIVERSITY_ENABLED: bool = (
    os.getenv("RESPONSE_DIVERSITY_ENABLED", "false").lower() == "true"
)

# === リアクション機能設定 ===
REACTION_ENABLED: bool = os.getenv("REACTION_ENABLED", "false").lower() == "true"
# should_react=True になる最低スコア閾値（JUDGE_SCORE_THRESHOLD より低く設定する）
JUDGE_REACT_THRESHOLD: int = int(os.getenv("JUDGE_REACT_THRESHOLD", "5"))

# === ユーザープロファイル設定 (Phase 2B) ===
USER_PROFILE_ENABLED: bool = os.getenv("USER_PROFILE_ENABLED", "false").lower() == "true"
FAMILIARITY_THRESHOLD_ACQUAINTANCE: int = int(os.getenv("FAMILIARITY_THRESHOLD_ACQUAINTANCE", "6"))
FAMILIARITY_THRESHOLD_REGULAR: int = int(os.getenv("FAMILIARITY_THRESHOLD_REGULAR", "31"))
FAMILIARITY_THRESHOLD_CLOSE: int = int(os.getenv("FAMILIARITY_THRESHOLD_CLOSE", "101"))

# === ユーザープロファイル拡張設定 (Phase 3B) ===
USER_PROFILE_TAGS_ENABLED: bool = os.getenv("USER_PROFILE_TAGS_ENABLED", "false").lower() == "true"
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
# アーカイブの最大保持件数（古い順に切り捨て。Firestore 1MB 上限対策）
FACT_ARCHIVE_MAX_ENTRIES: int = int(os.getenv("FACT_ARCHIVE_MAX_ENTRIES", "500"))

# === 反省会エンジン設定 (Phase 3A) ===
REFLECTION_ENABLED: bool = os.getenv("REFLECTION_ENABLED", "false").lower() == "true"
REFLECTION_LULL_MINUTES: int = int(os.getenv("REFLECTION_LULL_MINUTES", "10"))
REFLECTION_MIN_MESSAGES: int = int(os.getenv("REFLECTION_MIN_MESSAGES", "10"))
# バッファ量ベースの反省会トリガー閾値。
# CHANNEL_BUFFER_SIZE 以下の値を設定すること（それを超えると絶対に発動しない）。
REFLECTION_MAX_BUFFER_MESSAGES: int = int(os.getenv("REFLECTION_MAX_BUFFER_MESSAGES", "30"))

# === Embedding設定 (Phase 3B) ===
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-004")
VECTOR_SEARCH_ENABLED: bool = os.getenv("VECTOR_SEARCH_ENABLED", "false").lower() == "true"
HYBRID_ALPHA: float = float(os.getenv("HYBRID_ALPHA", "0.5"))  # ベクトル/キーワードスコアのバランス係数

# === 自発的会話設定 (Phase 3A) ===
PROACTIVE_CONVERSATION_ENABLED: bool = (
    os.getenv("PROACTIVE_CONVERSATION_ENABLED", "false").lower() == "true"
)
# 自発的会話をトリガーする沈黙時間（分）。REFLECTION_LULL_MINUTES と独立して設定可能。
PROACTIVE_SILENCE_MINUTES: int = int(os.getenv("PROACTIVE_SILENCE_MINUTES", "10"))

# フィーチャーフラグの依存関係チェック（起動時バリデーション）
if LLM_JUDGE_ENABLED and not AUTONOMOUS_RESPONSE_ENABLED:
    raise ValueError("LLM_JUDGE_ENABLED requires AUTONOMOUS_RESPONSE_ENABLED=True")

if PROACTIVE_CONVERSATION_ENABLED and not REFLECTION_ENABLED:
    raise ValueError("PROACTIVE_CONVERSATION_ENABLED requires REFLECTION_ENABLED=True")
