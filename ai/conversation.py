from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import DefaultDict, List, Optional

from openai.types.chat import (
    ChatCompletion,
    ChatCompletionAssistantMessageParam,
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)

from ai.client import client as aiclient
from config import OPENAI_MODEL, SYSTEM_PROMPT_FILENAME
from log_utils.logger import logger
from utils.text_utils import truncate_text

# 定数の定義
MAX_CONVERSATION_AGE_MINUTES = 30
MAX_CONVERSATION_TURNS = 10  # 往復数の上限


def load_system_prompt() -> str:
    """システムプロンプトをファイルから読み込む

    Returns:
        str: システムプロンプトの内容
    """
    prompt_path = Path(__file__).parent.parent / "prompts" / SYSTEM_PROMPT_FILENAME
    logger.info(f"システムプロンプトを読み込み: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8").strip()


class Sphene:
    """AIチャットボットの会話管理クラス"""

    def __init__(self, system_setting: str) -> None:
        """Spheneインスタンスを初期化

        Args:
            system_setting: システムプロンプト
        """
        self.system: ChatCompletionSystemMessageParam = {
            "role": "system",
            "content": system_setting,
        }
        self.input_list: List[ChatCompletionMessageParam] = [self.system]
        self.logs: List[ChatCompletion] = []
        # 会話の有効期限を設定（30分）
        self.last_interaction: Optional[datetime] = datetime.now()
        logger.info("Spheneインスタンスを初期化")

    def is_expired(self) -> bool:
        """会話が期限切れかどうかを判定

        Returns:
            bool: Trueの場合は期限切れ
        """
        if self.last_interaction is None:
            return False

        expiry_time = self.last_interaction + timedelta(
            minutes=MAX_CONVERSATION_AGE_MINUTES
        )
        return datetime.now() > expiry_time

    def update_interaction_time(self) -> None:
        """最終会話時間を更新"""
        self.last_interaction = datetime.now()

    def trim_conversation_history(self) -> None:
        """長くなった会話履歴を整理する"""
        # システムメッセージ + 往復N回分だけ保持
        max_messages = 1 + (MAX_CONVERSATION_TURNS * 2)

        if len(self.input_list) > max_messages:
            # システムメッセージを保持
            system_message = self.input_list[0]
            # 直近のメッセージだけを残す
            self.input_list = [system_message] + self.input_list[-(max_messages - 1) :]
            logger.info(
                f"会話履歴を整理しました（残りメッセージ数: {len(self.input_list)}）"
            )

    def input_message(self, input_text: Optional[str]) -> Optional[str]:
        """ユーザーからのメッセージを処理し、AIからの応答を返す

        Args:
            input_text: ユーザーからの入力テキスト

        Returns:
            Optional[str]: AIからの応答、エラー時はNone
        """
        if not isinstance(input_text, str) or not input_text.strip():
            logger.warning("受信したメッセージが無効です")
            return None

        self.update_interaction_time()

        # 型ガード後の変数を定義してからスライシング
        input_str: str = input_text
        preview = truncate_text(input_str)
        logger.info(f"ユーザーメッセージを受信: {preview}")

        # ユーザーメッセージを追加
        user_message: ChatCompletionUserMessageParam = {
            "role": "user",
            "content": input_text,
        }
        self.input_list.append(user_message)

        try:
            # OpenAI APIにリクエストを送信
            logger.info(f"OpenAI APIリクエスト送信（モデル: {OPENAI_MODEL}）")
            result = aiclient.chat.completions.create(
                model=OPENAI_MODEL, messages=self.input_list
            )
            self.logs.append(result)

            # 応答を処理
            response_content = result.choices[0].message.content
            if response_content:
                logger.info(
                    f"OpenAI APIレスポンス受信: {truncate_text(response_content)}"
                )
            else:
                logger.warning("OpenAI APIからの応答が空です")
                return None

            # 応答をメッセージリストに追加
            assistant_message: ChatCompletionAssistantMessageParam = {
                "role": "assistant",
                "content": response_content,
            }
            self.input_list.append(assistant_message)

            # 会話履歴の管理
            self.trim_conversation_history()

            return response_content

        except Exception as e:
            logger.error(f"APIリクエスト中にエラーが発生: {str(e)}", exc_info=True)
            return None


# ユーザーごとの会話インスタンスを保持する辞書
user_conversations: DefaultDict[str, Sphene] = defaultdict(
    lambda: Sphene(system_setting=load_system_prompt())
)
