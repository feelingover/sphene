"""LLMによる自律応答の二次判定 (Google Gen AI SDK版)"""

import json
import asyncio

import config
from ai.client import _get_genai_client, get_model_name
from ai.conversation import _generate_content_with_retry
from google.genai import types
from log_utils.logger import logger

LLM_JUDGE_PROMPT = """\
あなたはDiscordボットの応答判定AIです。
以下のチャンネルの会話の流れと最新メッセージを読んで、
ボット「{bot_name}」が自然に会話に参加すべきかと、その場合の応答形式を判定してください。

応答形式の種類:
- "full": 通常の返信（質問への回答、意見の提示、会話の深掘りなど）
- "short": 短い相槌や同意（「わかる！」「そうなんだね」など）
- "react": 絵文字リアクションのみ（スタンプ的な応答）
- "none": 応答しない（会話を静観する）

JSONで回答してください: {{"respond": true/false, "response_type": "full"|"short"|"react"|"none", "reason": "判定理由"}}
"""


class LLMJudge:
    """曖昧なケースのみLLMで二次判定する"""

    async def evaluate(
        self,
        message_content: str,
        recent_context: str,
        bot_name: str,
    ) -> tuple[bool, str]:
        """LLMで応答すべきかとその形式を判定する

        Returns:
            tuple[bool, str]: (応答すべきか, 応答形式 "full_response"|"short_ack"|"react_only")
        """
        try:
            should_respond, response_type = await asyncio.to_thread(
                self._call_llm, message_content, recent_context, bot_name
            )
            return should_respond, response_type
        except Exception as e:
            logger.error(f"LLM Judge呼び出しエラー: {str(e)}", exc_info=True)
            return False, "react_only"

    def _call_llm(
        self,
        message_content: str,
        recent_context: str,
        bot_name: str,
    ) -> tuple[bool, str]:
        """Google Gen AI SDKを同期的に呼び出す"""
        client = _get_genai_client()
        model_name = config.JUDGE_MODEL or get_model_name()
        
        prompt = f"{LLM_JUDGE_PROMPT.format(bot_name=bot_name)}\n\n直近の会話:\n{recent_context}\n\n最新メッセージ:\n{message_content}"

        logger.debug(f"LLM Judge呼び出し: model={model_name}")

        try:
            response = _generate_content_with_retry(
                client=client,
                model=model_name,
                contents=[types.Content(role="user", parts=[types.Part.from_text(text=prompt)])],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json", # JSONモードを有効化！
                ),
            )

            content = response.text
            if not content:
                return False, "none"

            result = json.loads(content)
            should_respond = bool(result.get("respond", False))
            llm_type = result.get("response_type", "none")
            
            # 内部形式に変換
            type_map = {
                "full": "full_response",
                "short": "short_ack",
                "react": "react_only",
                "none": "none"
            }
            final_type = type_map.get(llm_type, "react_only")
            
            if not should_respond:
                final_type = "none"

            logger.info(
                f"LLM Judge判定: respond={should_respond}, type={final_type}, "
                f"reason={result.get('reason', '')}"
            )
            return should_respond, final_type

        except Exception as e:
            logger.warning(f"LLM Judge処理失敗: {str(e)}")
            return False, "none"


_llm_judge: LLMJudge | None = None


def get_llm_judge() -> LLMJudge:
    """LLMJudgeのシングルトンインスタンスを取得する"""
    global _llm_judge
    if _llm_judge is None:
        _llm_judge = LLMJudge()
        logger.info("LLMJudge初期化完了")
    return _llm_judge
