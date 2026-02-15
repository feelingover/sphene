"""LLMによる自律応答の二次判定 (Google Gen AI SDK版)"""

import json
import asyncio

import config
from ai.client import _get_genai_client, get_model_name
from google.genai import types
from log_utils.logger import logger

LLM_JUDGE_PROMPT = """\
あなたはDiscordボットの応答判定AIです。
以下のチャンネルの会話の流れと最新メッセージを読んで、
ボット「{bot_name}」が自然に会話に参加すべきかを判定してください。

JSONで回答してください: {{"respond": true/false, "reason": "判定理由"}}
"""


class LLMJudge:
    """曖昧なケースのみLLMで二次判定する"""

    async def evaluate(
        self,
        message_content: str,
        recent_context: str,
        bot_name: str,
    ) -> bool:
        """LLMで応答すべきか判定する"""
        try:
            result = await asyncio.to_thread(
                self._call_llm, message_content, recent_context, bot_name
            )
            return result
        except Exception as e:
            logger.error(f"LLM Judge呼び出しエラー: {str(e)}", exc_info=True)
            return False

    def _call_llm(
        self,
        message_content: str,
        recent_context: str,
        bot_name: str,
    ) -> bool:
        """Google Gen AI SDKを同期的に呼び出す"""
        client = _get_genai_client()
        model_name = config.JUDGE_MODEL or get_model_name()
        
        prompt = f"{LLM_JUDGE_PROMPT.format(bot_name=bot_name)}\n\n直近の会話:\n{recent_context}\n\n最新メッセージ:\n{message_content}"

        logger.debug(f"LLM Judge呼び出し: model={model_name}")

        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json", # JSONモードを有効化！
                ),
            )

            content = response.text
            if not content:
                return False

            result = json.loads(content)
            should_respond = bool(result.get("respond", False))
            logger.info(f"LLM Judge判定: respond={should_respond}, reason={result.get('reason', '')}")
            return should_respond

        except Exception as e:
            logger.warning(f"LLM Judge処理失敗: {str(e)}")
            return False


_llm_judge: LLMJudge | None = None


def get_llm_judge() -> LLMJudge:
    """LLMJudgeのシングルトンインスタンスを取得する"""
    global _llm_judge
    if _llm_judge is None:
        _llm_judge = LLMJudge()
        logger.info("LLMJudge初期化完了")
    return _llm_judge
