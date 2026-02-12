import os

from dotenv import load_dotenv

load_dotenv()

# ログレベル設定（デフォルトはINFO）
LOG_LEVEL: str = str(os.getenv("LOG_LEVEL", "INFO"))

OPENAI_API_KEY: str = str(os.getenv("OPENAI_API_KEY"))
DISCORD_TOKEN: str = str(os.getenv("DISCORD_TOKEN"))
BOT_NAME: str = str(os.getenv("BOT_NAME", "アサヒ"))
COMMAND_GROUP_NAME: str = str(os.getenv("COMMAND_GROUP_NAME", "asahi"))
SYSTEM_PROMPT_FILENAME: str = str(os.getenv("SYSTEM_PROMPT_FILENAME", "system.txt"))
OPENAI_MODEL: str = str(os.getenv("OPENAI_MODEL", "gpt-4o-mini"))

# チャンネル設定の保存場所設定（local または firestore）
CHANNEL_CONFIG_STORAGE_TYPE: str = str(
    os.getenv("CHANNEL_CONFIG_STORAGE_TYPE", "local")
)

# システムプロンプトのファイルパス
SYSTEM_PROMPT_PATH: str = str(os.getenv("SYSTEM_PROMPT_PATH", "storage/system.txt"))

# Firestoreコレクション名（CHANNEL_CONFIG_STORAGE_TYPE=firestore の場合に使用）
FIRESTORE_COLLECTION_NAME: str = str(
    os.getenv("FIRESTORE_COLLECTION_NAME", "channel_configs")
)
