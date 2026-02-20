"""ルールベースの自律応答判定"""

from dataclasses import dataclass, field
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
    response_type: str = "full_response"  # "full_response" | "short_ack" | "react_only"


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
            return JudgeResult(
                score=100, should_respond=True, reason="メンション",
                response_type="full_response",
            )

        # ボットへのリプライ -> 即応答
        if is_reply_to_bot:
            return JudgeResult(
                score=100, should_respond=True, reason="リプライ",
                response_type="full_response",
            )

        # 名前呼び -> 即応答
        if is_name_called:
            return JudgeResult(
                score=80, should_respond=True, reason="名前呼び",
                response_type="full_response",
            )

        # エンゲージメント中（クールダウンとは独立に加算）
        is_engaged = self._is_engaged(message.channel_id)
        if is_engaged:
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

        # === Phase 2A 新ルール（recent_messagesがある場合のみ適用） ===
        if recent_messages:
            # 2人会話: ユニーク非bot著者が2人のみ
            if _count_unique_authors(recent_messages) == 2:
                score -= 20
                reasons.append("2人会話(-20)")

            # ボット言及なし: 直近メッセージにBOT_NAMEを含む非botメッセージがない
            if not _has_bot_mention_in_recent(recent_messages):
                score -= 10
                reasons.append("ボット言及なし(-10)")

            # 高頻度メッセージ: 直近10件が60秒以内
            if _is_high_frequency(recent_messages):
                score -= 10
                reasons.append("高頻度(-10)")

            # 得意話題: キーワードマッチ（recent_messagesに対して）
            if self._is_expert_topic(recent_messages):
                score += 15
                reasons.append("得意話題(+15)")

            # 沈黙後の最初のメッセージ
            if _is_first_after_silence(recent_messages):
                score += 10
                reasons.append("沈黙後(+10)")

            # 会話減衰: 直近メッセージの平均文字数が減少
            decay = _detect_conversation_decay(recent_messages)
            if decay != 0:
                score += decay
                reasons.append(f"会話減衰({decay:+d})")

        # クールダウンチェック
        if self._is_in_cooldown(message.channel_id):
            score -= 50
            reasons.append("クールダウン中(-50)")

        # スコアを0-100にクランプ
        score = max(0, min(100, score))

        threshold = config.JUDGE_SCORE_THRESHOLD
        should_respond = score >= threshold
        reason = ", ".join(reasons) if reasons else "条件なし"

        # 応答タイプの決定
        response_type = self._determine_response_type(score, is_engaged)

        logger.debug(
            f"Judge評価: チャンネル={message.channel_id}, "
            f"スコア={score}, 閾値={threshold}, 応答={should_respond}, "
            f"タイプ={response_type}, 理由=[{reason}]"
        )

        return JudgeResult(
            score=score,
            should_respond=should_respond,
            reason=reason,
            response_type=response_type,
        )

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

    def _is_expert_topic(self, recent_messages: list[ChannelMessage]) -> bool:
        """直近メッセージにキーワードが含まれるかチェックする"""
        if not self._keywords:
            return False
        combined = " ".join(
            msg.content for msg in recent_messages if not msg.is_bot
        )
        return any(kw in combined for kw in self._keywords)

    def _determine_response_type(self, score: int, is_engaged: bool) -> str:
        """スコアに基づいて応答タイプを決定する"""
        if not config.RESPONSE_DIVERSITY_ENABLED:
            return "full_response"
        
        full_threshold = config.JUDGE_SCORE_FULL_RESPONSE
        short_threshold = config.JUDGE_SCORE_SHORT_ACK
        
        if score >= full_threshold:
            return "full_response"
        if score >= short_threshold and not is_engaged:
            return "short_ack"
        if score < short_threshold:
            return "react_only"
        
        return "full_response"


def _count_unique_authors(messages: list[ChannelMessage]) -> int:
    """メッセージリスト内のユニーク非bot著者数を返す"""
    return len({msg.author_id for msg in messages if not msg.is_bot})


def _has_bot_mention_in_recent(messages: list[ChannelMessage]) -> bool:
    """直近メッセージにBOT_NAMEを含む非botメッセージがあるか"""
    bot_name = config.BOT_NAME
    return any(
        bot_name in msg.content for msg in messages if not msg.is_bot
    )


def _is_high_frequency(
    messages: list[ChannelMessage],
    window_seconds: int = 60,
    threshold: int = 10,
) -> bool:
    """直近N件がwindow_seconds以内に集中しているか"""
    non_bot = [msg for msg in messages if not msg.is_bot]
    if len(non_bot) < threshold:
        return False
    recent = non_bot[-threshold:]
    first_ts = recent[0].timestamp.replace(tzinfo=timezone.utc)
    last_ts = recent[-1].timestamp.replace(tzinfo=timezone.utc)
    return (last_ts - first_ts).total_seconds() <= window_seconds


def _is_first_after_silence(
    messages: list[ChannelMessage],
    silence_minutes: int = 10,
) -> bool:
    """直前メッセージとの間隔がsilence_minutes以上あるか"""
    non_bot = [msg for msg in messages if not msg.is_bot]
    if len(non_bot) < 2:
        return False
    prev = non_bot[-2]
    curr = non_bot[-1]
    prev_ts = prev.timestamp.replace(tzinfo=timezone.utc)
    curr_ts = curr.timestamp.replace(tzinfo=timezone.utc)
    return (curr_ts - prev_ts).total_seconds() >= silence_minutes * 60


def _detect_conversation_decay(
    messages: list[ChannelMessage],
    window: int = 6,
) -> int:
    """直近メッセージの平均文字数の減衰を検出する

    Returns:
        -10 ~ -15 (減衰あり) or 0 (減衰なし)
    """
    non_bot = [msg for msg in messages if not msg.is_bot]
    if len(non_bot) < window:
        return 0

    recent = non_bot[-window:]
    half = window // 2
    first_half = recent[:half]
    second_half = recent[half:]

    avg_first = sum(len(m.content) for m in first_half) / len(first_half)
    avg_second = sum(len(m.content) for m in second_half) / len(second_half)

    if avg_first == 0:
        return 0

    ratio = avg_second / avg_first
    if ratio <= 0.5:
        return -15
    elif ratio <= 0.7:
        return -10
    return 0


# モジュールレベルのシングルトン
_judge: RuleBasedJudge | None = None


def get_judge() -> RuleBasedJudge:
    """RuleBasedJudgeのシングルトンインスタンスを取得する"""
    global _judge
    if _judge is None:
        _judge = RuleBasedJudge()
        logger.info("RuleBasedJudge初期化完了")
    return _judge
