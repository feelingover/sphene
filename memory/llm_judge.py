"""LLMによる自律応答の二次判定 (Google Gen AI SDK版)"""

import json
import asyncio
from html import escape

import config
from ai.client import _get_genai_client, get_lite_model_name
from ai.api import generate_content_with_retry as _generate_content_with_retry
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

JSONで回答してください:
{{"respond": true/false, "response_type": "full"|"short"|"react"|"none",
 "react": true/false, "emojis": ["絵文字1", "絵文字2"], "reason": "判定理由"}}

emojis は文脈に合う Unicode 絵文字を 0〜2 個のリストで返してください。
"""


class LLMJudge:
    """曖昧なケースのみLLMで二次判定する"""

    async def evaluate(
        self,
        message_content: str,
        recent_context: str,
        bot_name: str,
    ) -> tuple[bool, str, bool, list[str]]:
        """LLMで応答すべきかとその形式を判定する

        Returns:
            tuple[bool, str, bool, list[str]]:
                (should_respond, response_type, should_react, reaction_emojis)
        """
        try:
            should_respond, response_type, should_react, reaction_emojis = (
                await asyncio.to_thread(
                    self._call_llm, message_content, recent_context, bot_name
                )
            )
            return should_respond, response_type, should_react, reaction_emojis
        except Exception as e:
            logger.error(f"LLM Judge呼び出しエラー: {str(e)}", exc_info=True)
            return False, "react_only", False, []

    def _call_llm(
        self,
        message_content: str,
        recent_context: str,
        bot_name: str,
    ) -> tuple[bool, str, bool, list[str]]:
        """Google Gen AI SDKを同期的に呼び出す"""
        client = _get_genai_client()
        model_name = get_lite_model_name()
        
        safe_message = f"<message>{escape(message_content)}</message>"
        safe_context = f"<context>{escape(recent_context)}</context>"
        prompt = f"{LLM_JUDGE_PROMPT.format(bot_name=bot_name)}\n\n直近の会話:\n{safe_context}\n\n最新メッセージ:\n{safe_message}"

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
                return False, "none", False, []

            result = json.loads(content)
            if isinstance(result, list):
                result = result[0] if result else {}
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

            should_react = bool(result.get("react", False))
            raw_emojis = result.get("emojis", [])
            emojis: list[str] = [e for e in raw_emojis if isinstance(e, str)][:2]

            logger.info(
                f"LLM Judge判定: respond={should_respond}, type={final_type}, "
                f"react={should_react}, emojis={emojis}, "
                f"reason={result.get('reason', '')}"
            )
            return should_respond, final_type, should_react, emojis

        except Exception as e:
            logger.warning(f"LLM Judge処理失敗: {str(e)}")
            return False, "none", False, []


_llm_judge: LLMJudge | None = None


def get_llm_judge() -> LLMJudge:
    """LLMJudgeのシングルトンインスタンスを取得する"""
    global _llm_judge
    if _llm_judge is None:
        _llm_judge = LLMJudge()
        logger.info("LLMJudge初期化完了")
    return _llm_judge
