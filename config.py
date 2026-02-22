import os

from dotenv import load_dotenv

load_dotenv()

# ログレベル設定（デフォルトはINFO）
LOG_LEVEL: str = str(os.getenv("LOG_LEVEL", "INFO"))
# ログフォーマット設定（"json" または "text"）
LOG_FORMAT: str = str(os.getenv("LOG_FORMAT", "json"))

GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "google/gemini-2.5-flash")

# Vertex AI設定
VERTEX_AI_PROJECT_ID: str = os.getenv("VERTEX_AI_PROJECT_ID", "")
VERTEX_AI_LOCATION: str = os.getenv("VERTEX_AI_LOCATION", "asia-northeast1")
# Google検索によるGroundingを有効にするか
ENABLE_GOOGLE_SEARCH_GROUNDING: bool = (
    os.getenv("ENABLE_GOOGLE_SEARCH_GROUNDING", "false").lower() == "true"
)

DISCORD_TOKEN: str = str(os.getenv("DISCORD_TOKEN"))
BOT_NAME: str = str(os.getenv("BOT_NAME", "アサヒ"))
COMMAND_GROUP_NAME: str = str(os.getenv("COMMAND_GROUP_NAME", "asahi"))
SYSTEM_PROMPT_FILENAME: str = str(os.getenv("SYSTEM_PROMPT_FILENAME", "system.txt"))

# ストレージタイプ（local または firestore）
STORAGE_TYPE: str = str(os.getenv("STORAGE_TYPE", "local"))

# システムプロンプトのファイルパス
SYSTEM_PROMPT_PATH: str = str(os.getenv("SYSTEM_PROMPT_PATH", "storage/system.txt"))

# Firestoreネームスペース（マルチテナント対応、空=プレフィックスなし）
FIRESTORE_NAMESPACE: str = os.getenv("FIRESTORE_NAMESPACE", "")


def get_collection_name(base_name: str) -> str:
    """ネームスペース付きFirestoreコレクション名を返す"""
    if FIRESTORE_NAMESPACE:
        return f"{FIRESTORE_NAMESPACE}_{base_name}"
    return base_name


FIRESTORE_COLLECTION_CHANNEL_CONFIGS: str = get_collection_name("channel_configs")
FIRESTORE_COLLECTION_USER_PROFILES: str = get_collection_name("user_profiles")
FIRESTORE_COLLECTION_CHANNEL_CONTEXTS: str = get_collection_name("channel_contexts")

# === AI会話設定 ===
MAX_TOOL_CALL_ROUNDS: int = int(os.getenv("MAX_TOOL_CALL_ROUNDS", "5"))

# === 記憶機能設定 ===

# 短期記憶（チャンネルメッセージバッファ）
MEMORY_ENABLED: bool = os.getenv("MEMORY_ENABLED", "false").lower() == "true"
CHANNEL_BUFFER_SIZE: int = int(os.getenv("CHANNEL_BUFFER_SIZE", "50"))
CHANNEL_BUFFER_TTL_MINUTES: int = int(os.getenv("CHANNEL_BUFFER_TTL_MINUTES", "30"))

# 自律応答
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
LLM_JUDGE_ENABLED: bool = (
    os.getenv("LLM_JUDGE_ENABLED", "false").lower() == "true"
)
JUDGE_MODEL: str = os.getenv("JUDGE_MODEL", "")
JUDGE_LLM_THRESHOLD_LOW: int = int(os.getenv("JUDGE_LLM_THRESHOLD_LOW", "20"))
JUDGE_LLM_THRESHOLD_HIGH: int = int(os.getenv("JUDGE_LLM_THRESHOLD_HIGH", "60"))

# === チャンネルコンテキスト設定 ===
CHANNEL_CONTEXT_ENABLED: bool = (
    os.getenv("CHANNEL_CONTEXT_ENABLED", "false").lower() == "true"
)
SUMMARIZE_EVERY_N_MESSAGES: int = int(os.getenv("SUMMARIZE_EVERY_N_MESSAGES", "20"))
SUMMARIZE_EVERY_N_MINUTES: int = int(os.getenv("SUMMARIZE_EVERY_N_MINUTES", "15"))
SUMMARIZE_MODEL: str = os.getenv("SUMMARIZE_MODEL", "")

# === 応答多様性設定 ===
RESPONSE_DIVERSITY_ENABLED: bool = (
    os.getenv("RESPONSE_DIVERSITY_ENABLED", "false").lower() == "true"
)

# === ユーザープロファイル設定 (Phase 2B) ===
USER_PROFILE_ENABLED: bool = os.getenv("USER_PROFILE_ENABLED", "false").lower() == "true"
FAMILIARITY_THRESHOLD_ACQUAINTANCE: int = int(os.getenv("FAMILIARITY_THRESHOLD_ACQUAINTANCE", "6"))
FAMILIARITY_THRESHOLD_REGULAR: int = int(os.getenv("FAMILIARITY_THRESHOLD_REGULAR", "31"))
FAMILIARITY_THRESHOLD_CLOSE: int = int(os.getenv("FAMILIARITY_THRESHOLD_CLOSE", "101"))
