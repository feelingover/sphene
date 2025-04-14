import os
from typing import List

from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY: str = str(os.getenv("OPENAI_API_KEY"))
DISCORD_TOKEN: str = str(os.getenv("DISCORD_TOKEN"))
BOT_NAME: str = str(os.getenv("BOT_NAME", "アサヒ"))
COMMAND_GROUP_NAME: str = str(os.getenv("COMMAND_GROUP_NAME", "asahi"))

# 禁止されたチャンネルのID（環境変数から取得、カンマ区切りで設定）
DENIED_CHANNEL_IDS: List[int] = []
channel_ids_str = os.getenv("DENIED_CHANNEL_IDS", "")
if channel_ids_str:
    DENIED_CHANNEL_IDS = [
        int(channel_id.strip()) for channel_id in channel_ids_str.split(",")
    ]
