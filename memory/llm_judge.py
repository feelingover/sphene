"""LLMによる自律応答の二次判定"""

import json

import config
from ai.client import get_client
from log_utils.logger import logger

LLM_JUDGE_PROMPT = """\
あなたはDiscordボットの応答判定AIです。
以下のチャンネルの会話の流れと最新メッセージを読んで、
ボット「{bot_name}」が自然に会話に参加すべきかを判定してください。

判定基準:
- ボットの得意分野や知識が役立ちそうか
- 会話が行き詰まっていて助けになれるか
- 話題に自然に参加できるか
- 割り込むと邪魔になりそうな場合は参加しない

直近の会話:
{context}

最新メッセージ:
{message}

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
        """LLMで応答すべきか判定する

        Args:
            message_content: 判定対象のメッセージ内容
            recent_context: 直近のチャンネルコンテキスト
            bot_name: ボットの名前

        Returns:
            bool: True = 応答する
        """
        import asyncio

        try:
            result = await asyncio.to_thread(
                self._call_llm, message_content, recent_context, bot_name
            )
            return result
        except Exception as e:
            logger.error(f"LLM Judge呼び出しエラー: {str(e)}", exc_info=True)
            return False  # 失敗時は応答しない（安全側にフォールバック）

    def _call_llm(
        self,
        message_content: str,
        recent_context: str,
        bot_name: str,
    ) -> bool:
        """LLM APIを同期的に呼び出す"""
        model = config.JUDGE_MODEL or config.OPENAI_MODEL
        prompt = LLM_JUDGE_PROMPT.format(
            bot_name=bot_name,
            context=recent_context or "(会話履歴なし)",
            message=message_content,
        )

        logger.debug(f"LLM Judge呼び出し: model={model}")

        response = get_client().chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=1024,
        )

        choice = response.choices[0]
        message = choice.message
        content = message.content if message else None
        if not content:
            logger.warning(
                f"LLM Judgeからの応答が空です: "
                f"finish_reason={choice.finish_reason}, "
                f"message={message}"
            )
            return False

        logger.debug(f"LLM Judge応答: {content}")

        try:
            result = json.loads(content)
            should_respond = bool(result.get("respond", False))
            reason = result.get("reason", "")
            logger.info(
                f"LLM Judge判定: respond={should_respond}, reason={reason}"
            )
            return should_respond
        except (json.JSONDecodeError, KeyError) as e:
            # JSONパースに失敗した場合、テキストから判定を試みる
            logger.warning(
                f"LLM Judge応答のJSONパース失敗: {str(e)}, 応答: {content}"
            )
            # "true" が含まれるかで簡易判定
            return "true" in content.lower()


# モジュールレベルのシングルトン
_llm_judge: LLMJudge | None = None


def get_llm_judge() -> LLMJudge:
    """LLMJudgeのシングルトンインスタンスを取得する"""
    global _llm_judge
    if _llm_judge is None:
        _llm_judge = LLMJudge()
        logger.info("LLMJudge初期化完了")
    return _llm_judge
