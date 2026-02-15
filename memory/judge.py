"""ルールベースの自律応答判定"""

from dataclasses import dataclass
from datetime import datetime, timezone

import config
from log_utils.logger import logger
from memory.short_term import ChannelMessage


@dataclass
class JudgeResult:
    """判定結果"""

    score: int  # 0-100
    should_respond: bool
    reason: str  # ログ用の判定理由


class RuleBasedJudge:
    """ルールベースのスコアリングによる自律応答判定"""

    def __init__(self) -> None:
        self._last_response_times: dict[int, datetime] = {}
        self._keywords: list[str] = [
            kw.strip()
            for kw in config.JUDGE_KEYWORDS.split(",")
            if kw.strip()
        ]
        if self._keywords:
            logger.info(f"Judge キーワード設定: {self._keywords}")

    def evaluate(
        self,
        message: ChannelMessage,
        recent_messages: list[ChannelMessage],
        is_mentioned: bool,
        is_name_called: bool,
        is_reply_to_bot: bool,
    ) -> JudgeResult:
        """メッセージを評価してスコアリングする

        Args:
            message: 評価対象メッセージ
            recent_messages: 直近のメッセージリスト
            is_mentioned: @メンションされたか
            is_name_called: BOT_NAMEで呼ばれたか
            is_reply_to_bot: ボットへのリプライか

        Returns:
            JudgeResult: スコアと応答可否
        """
        score = 0
        reasons: list[str] = []

        # @メンション -> 即応答
        if is_mentioned:
            return JudgeResult(score=100, should_respond=True, reason="メンション")

        # ボットへのリプライ -> 即応答
        if is_reply_to_bot:
            return JudgeResult(score=100, should_respond=True, reason="リプライ")

        # 名前呼び -> 即応答
        if is_name_called:
            return JudgeResult(score=80, should_respond=True, reason="名前呼び")

        # エンゲージメント中（クールダウンとは独立に加算）
        if self._is_engaged(message.channel_id):
            score += config.ENGAGEMENT_BOOST
            reasons.append(f"エンゲージメント(+{config.ENGAGEMENT_BOOST})")

        # 疑問符で終わる
        content = message.content.strip()
        if content.endswith("?") or content.endswith("？"):
            score += 20
            reasons.append("疑問文(+20)")

        # キーワードマッチ
        if self._keywords:
            for keyword in self._keywords:
                if keyword in message.content:
                    score += 15
                    reasons.append(f"キーワード'{keyword}'(+15)")
                    break  # 1キーワードにつき1回のみ

        # クールダウンチェック
        if self._is_in_cooldown(message.channel_id):
            score -= 50
            reasons.append("クールダウン中(-50)")

        # スコアを0-100にクランプ
        score = max(0, min(100, score))

        threshold = config.JUDGE_SCORE_THRESHOLD
        should_respond = score >= threshold
        reason = ", ".join(reasons) if reasons else "条件なし"

        logger.debug(
            f"Judge評価: チャンネル={message.channel_id}, "
            f"スコア={score}, 閾値={threshold}, 応答={should_respond}, "
            f"理由=[{reason}]"
        )

        return JudgeResult(score=score, should_respond=should_respond, reason=reason)

    def record_response(self, channel_id: int) -> None:
        """応答した時刻を記録してクールダウンを開始する"""
        self._last_response_times[channel_id] = datetime.now(timezone.utc)
        logger.debug(f"クールダウン記録: チャンネル={channel_id}")

    def _is_engaged(self, channel_id: int) -> bool:
        """チャンネルがエンゲージメント期間中かどうかを判定する"""
        if channel_id not in self._last_response_times:
            return False
        last_time = self._last_response_times[channel_id]
        now = datetime.now(timezone.utc)
        elapsed = (now - last_time).total_seconds()
        return elapsed < config.ENGAGEMENT_DURATION_SECONDS

    def _is_in_cooldown(self, channel_id: int) -> bool:
        """チャンネルがクールダウン中かどうかを判定する"""
        if channel_id not in self._last_response_times:
            return False
        last_time = self._last_response_times[channel_id]
        now = datetime.now(timezone.utc)
        elapsed = (now - last_time).total_seconds()
        return elapsed < config.COOLDOWN_SECONDS


# モジュールレベルのシングルトン
_judge: RuleBasedJudge | None = None


def get_judge() -> RuleBasedJudge:
    """RuleBasedJudgeのシングルトンインスタンスを取得する"""
    global _judge
    if _judge is None:
        _judge = RuleBasedJudge()
        logger.info("RuleBasedJudge初期化完了")
    return _judge
