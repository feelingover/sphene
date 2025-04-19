import os
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY: str = str(os.getenv("OPENAI_API_KEY"))
DISCORD_TOKEN: str = str(os.getenv("DISCORD_TOKEN"))
BOT_NAME: str = str(os.getenv("BOT_NAME", "アサヒ"))
COMMAND_GROUP_NAME: str = str(os.getenv("COMMAND_GROUP_NAME", "asahi"))
SYSTEM_PROMPT_FILENAME: str = str(os.getenv("SYSTEM_PROMPT_FILENAME", "system.txt"))
OPENAI_MODEL: str = str(os.getenv("OPENAI_MODEL", "gpt-4o-mini"))

# プロンプトの保存場所設定（local または s3）
PROMPT_STORAGE_TYPE: str = str(os.getenv("PROMPT_STORAGE_TYPE", "local"))
# S3バケット名（S3使用時のみ）
S3_BUCKET_NAME: str = str(os.getenv("S3_BUCKET_NAME", ""))
# S3フォルダパス（オプション）
S3_FOLDER_PATH: Optional[str] = os.getenv("S3_FOLDER_PATH")

# 禁止されたチャンネルのID（環境変数から取得、カンマ区切りで設定）
DENIED_CHANNEL_IDS: List[int] = []
channel_ids_str = os.getenv("DENIED_CHANNEL_IDS", "")
if channel_ids_str:
    DENIED_CHANNEL_IDS = [
        int(channel_id.strip()) for channel_id in channel_ids_str.split(",")
    ]
