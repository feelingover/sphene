"""ルールベースJudgeのテスト"""

# type: ignore
# mypy: ignore-errors

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from memory.judge import (
    JudgeResult,
    RuleBasedJudge,
    _count_unique_authors,
    _detect_conversation_decay,
    _has_bot_mention_in_recent,
    _is_first_after_silence,
    _is_high_frequency,
)
from memory.short_term import ChannelMessage


def _make_message(
    content: str = "テストメッセージ",
    channel_id: int = 100,
    minutes_ago: int = 0,
    author_id: int = 12345,
    author_name: str = "TestUser",
    is_bot: bool = False,
    seconds_ago: int | None = None,
) -> ChannelMessage:
    """テスト用ChannelMessageを生成するヘルパー"""
    if seconds_ago is not None:
        delta = timedelta(seconds=seconds_ago)
    else:
        delta = timedelta(minutes=minutes_ago)
    return ChannelMessage(
        message_id=1,
        channel_id=channel_id,
        author_id=author_id,
        author_name=author_name,
        content=content,
        timestamp=datetime.now(timezone.utc) - delta,
        is_bot=is_bot,
    )


class TestRuleBasedJudge:
    """RuleBasedJudgeのテスト"""

    @patch("memory.judge.config")
    def test_mention_returns_100(self, mock_config):
        """@メンションで即スコア100"""
        mock_config.JUDGE_KEYWORDS = ""
        mock_config.COOLDOWN_SECONDS = 120
        mock_config.JUDGE_SCORE_THRESHOLD = 20
        mock_config.JUDGE_SCORE_FULL_RESPONSE = 60
        mock_config.JUDGE_SCORE_SHORT_ACK = 30
        mock_config.RESPONSE_DIVERSITY_ENABLED = False
        mock_config.BOT_NAME = "テストボット"

        judge = RuleBasedJudge()
        msg = _make_message()
        result = judge.evaluate(
            message=msg,
            recent_messages=[],
            is_mentioned=True,
            is_name_called=False,
            is_reply_to_bot=False,
        )
        assert result.score == 100
        assert result.should_respond is True
        assert "メンション" in result.reason

    @patch("memory.judge.config")
    def test_reply_to_bot_returns_100(self, mock_config):
        """ボットへのリプライで即スコア100"""
        mock_config.JUDGE_KEYWORDS = ""
        mock_config.COOLDOWN_SECONDS = 120
        mock_config.JUDGE_SCORE_THRESHOLD = 20
        mock_config.JUDGE_SCORE_FULL_RESPONSE = 60
        mock_config.JUDGE_SCORE_SHORT_ACK = 30
        mock_config.RESPONSE_DIVERSITY_ENABLED = False
        mock_config.BOT_NAME = "テストボット"

        judge = RuleBasedJudge()
        msg = _make_message()
        result = judge.evaluate(
            message=msg,
            recent_messages=[],
            is_mentioned=False,
            is_name_called=False,
            is_reply_to_bot=True,
        )
        assert result.score == 100
        assert result.should_respond is True
        assert "リプライ" in result.reason

    @patch("memory.judge.config")
    def test_name_called_returns_80(self, mock_config):
        """名前呼びでスコア80"""
        mock_config.JUDGE_KEYWORDS = ""
        mock_config.COOLDOWN_SECONDS = 120
        mock_config.JUDGE_SCORE_THRESHOLD = 20
        mock_config.JUDGE_SCORE_FULL_RESPONSE = 60
        mock_config.JUDGE_SCORE_SHORT_ACK = 30
        mock_config.RESPONSE_DIVERSITY_ENABLED = False
        mock_config.BOT_NAME = "テストボット"

        judge = RuleBasedJudge()
        msg = _make_message()
        result = judge.evaluate(
            message=msg,
            recent_messages=[],
            is_mentioned=False,
            is_name_called=True,
            is_reply_to_bot=False,
        )
        assert result.score == 80
        assert result.should_respond is True
        assert "名前呼び" in result.reason

    @patch("memory.judge.config")
    def test_question_mark_adds_20(self, mock_config):
        """疑問符で+20"""
        mock_config.JUDGE_KEYWORDS = ""
        mock_config.COOLDOWN_SECONDS = 120
        mock_config.JUDGE_SCORE_THRESHOLD = 20
        mock_config.JUDGE_SCORE_FULL_RESPONSE = 60
        mock_config.JUDGE_SCORE_SHORT_ACK = 30
        mock_config.RESPONSE_DIVERSITY_ENABLED = False
        mock_config.BOT_NAME = "テストボット"

        judge = RuleBasedJudge()
        msg = _make_message(content="これってどうなの？")
        result = judge.evaluate(
            message=msg,
            recent_messages=[],
            is_mentioned=False,
            is_name_called=False,
            is_reply_to_bot=False,
        )
        assert result.score == 20
        assert "疑問文" in result.reason

    @patch("memory.judge.config")
    def test_question_mark_ascii(self, mock_config):
        """半角疑問符でも+20"""
        mock_config.JUDGE_KEYWORDS = ""
        mock_config.COOLDOWN_SECONDS = 120
        mock_config.JUDGE_SCORE_THRESHOLD = 20
        mock_config.JUDGE_SCORE_FULL_RESPONSE = 60
        mock_config.JUDGE_SCORE_SHORT_ACK = 30
        mock_config.RESPONSE_DIVERSITY_ENABLED = False
        mock_config.BOT_NAME = "テストボット"

        judge = RuleBasedJudge()
        msg = _make_message(content="How about this?")
        result = judge.evaluate(
            message=msg,
            recent_messages=[],
            is_mentioned=False,
            is_name_called=False,
            is_reply_to_bot=False,
        )
        assert result.score == 20

    @patch("memory.judge.config")
    def test_keyword_match_adds_15(self, mock_config):
        """キーワードマッチで+15"""
        mock_config.JUDGE_KEYWORDS = "Python,Rust,ゲーム"
        mock_config.COOLDOWN_SECONDS = 120
        mock_config.JUDGE_SCORE_THRESHOLD = 20
        mock_config.JUDGE_SCORE_FULL_RESPONSE = 60
        mock_config.JUDGE_SCORE_SHORT_ACK = 30
        mock_config.RESPONSE_DIVERSITY_ENABLED = False
        mock_config.BOT_NAME = "テストボット"

        judge = RuleBasedJudge()
        msg = _make_message(content="Pythonの書き方教えて")
        result = judge.evaluate(
            message=msg,
            recent_messages=[],
            is_mentioned=False,
            is_name_called=False,
            is_reply_to_bot=False,
        )
        assert result.score == 15
        assert "キーワード" in result.reason

    @patch("memory.judge.config")
    def test_question_and_keyword_combined(self, mock_config):
        """疑問符+キーワードの組み合わせ"""
        mock_config.JUDGE_KEYWORDS = "Python"
        mock_config.COOLDOWN_SECONDS = 120
        mock_config.JUDGE_SCORE_THRESHOLD = 20
        mock_config.JUDGE_SCORE_FULL_RESPONSE = 60
        mock_config.JUDGE_SCORE_SHORT_ACK = 30
        mock_config.RESPONSE_DIVERSITY_ENABLED = False
        mock_config.BOT_NAME = "テストボット"

        judge = RuleBasedJudge()
        msg = _make_message(content="Pythonの書き方って？")
        result = judge.evaluate(
            message=msg,
            recent_messages=[],
            is_mentioned=False,
            is_name_called=False,
            is_reply_to_bot=False,
        )
        assert result.score == 35  # 20 + 15

    @patch("memory.judge.config")
    def test_cooldown_subtracts_50(self, mock_config):
        """クールダウン中で-50"""
        mock_config.JUDGE_KEYWORDS = ""
        mock_config.COOLDOWN_SECONDS = 120
        mock_config.ENGAGEMENT_DURATION_SECONDS = 300
        mock_config.ENGAGEMENT_BOOST = 40
        mock_config.JUDGE_SCORE_THRESHOLD = 20
        mock_config.JUDGE_SCORE_FULL_RESPONSE = 60
        mock_config.JUDGE_SCORE_SHORT_ACK = 30
        mock_config.RESPONSE_DIVERSITY_ENABLED = False
        mock_config.BOT_NAME = "テストボット"

        judge = RuleBasedJudge()
        # まずクールダウンを記録
        judge.record_response(100)

        msg = _make_message(content="テスト？", channel_id=100)
        result = judge.evaluate(
            message=msg,
            recent_messages=[],
            is_mentioned=False,
            is_name_called=False,
            is_reply_to_bot=False,
        )
        # エンゲージメント(+40) + 疑問符(+20) - クールダウン(-50) = 10
        assert result.score == 10

    @patch("memory.judge.config")
    def test_cooldown_expires(self, mock_config):
        """クールダウン期限切れ後はペナルティなし"""
        mock_config.JUDGE_KEYWORDS = ""
        mock_config.COOLDOWN_SECONDS = 1  # 1秒
        mock_config.ENGAGEMENT_DURATION_SECONDS = 1  # エンゲージメントも1秒
        mock_config.ENGAGEMENT_BOOST = 40
        mock_config.JUDGE_SCORE_THRESHOLD = 20
        mock_config.JUDGE_SCORE_FULL_RESPONSE = 60
        mock_config.JUDGE_SCORE_SHORT_ACK = 30
        mock_config.RESPONSE_DIVERSITY_ENABLED = False
        mock_config.BOT_NAME = "テストボット"

        judge = RuleBasedJudge()
        # 2秒前に応答したことにする（クールダウンもエンゲージメントも切れ）
        judge._last_response_times[100] = datetime.now(timezone.utc) - timedelta(
            seconds=2
        )

        msg = _make_message(content="テスト？", channel_id=100)
        result = judge.evaluate(
            message=msg,
            recent_messages=[],
            is_mentioned=False,
            is_name_called=False,
            is_reply_to_bot=False,
        )
        assert result.score == 20  # 疑問符のみ、クールダウンもエンゲージメントもなし

    @patch("memory.judge.config")
    def test_no_conditions_score_zero(self, mock_config):
        """条件なしでスコア0"""
        mock_config.JUDGE_KEYWORDS = ""
        mock_config.COOLDOWN_SECONDS = 120
        mock_config.JUDGE_SCORE_THRESHOLD = 20
        mock_config.JUDGE_SCORE_FULL_RESPONSE = 60
        mock_config.JUDGE_SCORE_SHORT_ACK = 30
        mock_config.RESPONSE_DIVERSITY_ENABLED = False
        mock_config.BOT_NAME = "テストボット"

        judge = RuleBasedJudge()
        msg = _make_message(content="普通のメッセージ")
        result = judge.evaluate(
            message=msg,
            recent_messages=[],
            is_mentioned=False,
            is_name_called=False,
            is_reply_to_bot=False,
        )
        assert result.score == 0
        assert result.should_respond is False

    @patch("memory.judge.config")
    def test_score_clamped_to_0_100(self, mock_config):
        """スコアが0-100にクランプされること"""
        mock_config.JUDGE_KEYWORDS = ""
        mock_config.COOLDOWN_SECONDS = 120
        mock_config.ENGAGEMENT_DURATION_SECONDS = 0  # エンゲージメント無効
        mock_config.ENGAGEMENT_BOOST = 40
        mock_config.JUDGE_SCORE_THRESHOLD = 20
        mock_config.JUDGE_SCORE_FULL_RESPONSE = 60
        mock_config.JUDGE_SCORE_SHORT_ACK = 30
        mock_config.RESPONSE_DIVERSITY_ENABLED = False
        mock_config.BOT_NAME = "テストボット"

        judge = RuleBasedJudge()
        # クールダウン中 + 条件なし = -50 -> 0
        judge.record_response(100)
        msg = _make_message(content="テスト", channel_id=100)
        result = judge.evaluate(
            message=msg,
            recent_messages=[],
            is_mentioned=False,
            is_name_called=False,
            is_reply_to_bot=False,
        )
        assert result.score == 0

    @patch("memory.judge.config")
    def test_should_respond_based_on_threshold(self, mock_config):
        """閾値に基づいてshould_respondが決まること"""
        mock_config.JUDGE_KEYWORDS = "test"
        mock_config.COOLDOWN_SECONDS = 120
        mock_config.JUDGE_SCORE_THRESHOLD = 30
        mock_config.RESPONSE_DIVERSITY_ENABLED = False
        mock_config.BOT_NAME = "テストボット"

        judge = RuleBasedJudge()
        # 疑問符(20) + キーワード(15) = 35 >= 30 -> True
        msg = _make_message(content="testってどう？")
        result = judge.evaluate(
            message=msg,
            recent_messages=[],
            is_mentioned=False,
            is_name_called=False,
            is_reply_to_bot=False,
        )
        assert result.score == 35
        assert result.should_respond is True

    @patch("memory.judge.config")
    def test_empty_keywords(self, mock_config):
        """空のキーワード設定"""
        mock_config.JUDGE_KEYWORDS = ""
        mock_config.COOLDOWN_SECONDS = 120
        mock_config.JUDGE_SCORE_THRESHOLD = 20
        mock_config.JUDGE_SCORE_FULL_RESPONSE = 60
        mock_config.JUDGE_SCORE_SHORT_ACK = 30
        mock_config.RESPONSE_DIVERSITY_ENABLED = False
        mock_config.BOT_NAME = "テストボット"

        judge = RuleBasedJudge()
        assert judge._keywords == []

    @patch("memory.judge.config")
    def test_record_response(self, mock_config):
        """record_responseでクールダウンが記録されること"""
        mock_config.JUDGE_KEYWORDS = ""
        mock_config.COOLDOWN_SECONDS = 120
        mock_config.JUDGE_SCORE_THRESHOLD = 20
        mock_config.JUDGE_SCORE_FULL_RESPONSE = 60
        mock_config.JUDGE_SCORE_SHORT_ACK = 30
        mock_config.RESPONSE_DIVERSITY_ENABLED = False
        mock_config.BOT_NAME = "テストボット"

        judge = RuleBasedJudge()
        assert 100 not in judge._last_response_times
        judge.record_response(100)
        assert 100 in judge._last_response_times

    @patch("memory.judge.config")
    def test_engagement_boost_during_engagement(self, mock_config):
        """エンゲージメント期間中にブーストが加算されること"""
        mock_config.JUDGE_KEYWORDS = ""
        mock_config.COOLDOWN_SECONDS = 10
        mock_config.ENGAGEMENT_DURATION_SECONDS = 300
        mock_config.ENGAGEMENT_BOOST = 40
        mock_config.JUDGE_SCORE_THRESHOLD = 20
        mock_config.JUDGE_SCORE_FULL_RESPONSE = 60
        mock_config.JUDGE_SCORE_SHORT_ACK = 30
        mock_config.RESPONSE_DIVERSITY_ENABLED = False
        mock_config.BOT_NAME = "テストボット"

        judge = RuleBasedJudge()
        # クールダウン期間外・エンゲージメント期間内（例: 30秒前に応答）
        judge._last_response_times[100] = datetime.now(timezone.utc) - timedelta(
            seconds=30
        )

        msg = _make_message(content="テスト？", channel_id=100)
        result = judge.evaluate(
            message=msg,
            recent_messages=[],
            is_mentioned=False,
            is_name_called=False,
            is_reply_to_bot=False,
        )
        # エンゲージメント(+40) + 疑問符(+20) = 60
        assert result.score == 60
        assert "エンゲージメント" in result.reason

    @patch("memory.judge.config")
    def test_engagement_and_cooldown_coexist(self, mock_config):
        """クールダウン中でもエンゲージメントブーストが加算されること（相殺）"""
        mock_config.JUDGE_KEYWORDS = ""
        mock_config.COOLDOWN_SECONDS = 120
        mock_config.ENGAGEMENT_DURATION_SECONDS = 300
        mock_config.ENGAGEMENT_BOOST = 40
        mock_config.JUDGE_SCORE_THRESHOLD = 20
        mock_config.JUDGE_SCORE_FULL_RESPONSE = 60
        mock_config.JUDGE_SCORE_SHORT_ACK = 30
        mock_config.RESPONSE_DIVERSITY_ENABLED = False
        mock_config.BOT_NAME = "テストボット"

        judge = RuleBasedJudge()
        # 直後に応答（クールダウン中 かつ エンゲージメント中）
        judge.record_response(100)

        msg = _make_message(content="テスト？", channel_id=100)
        result = judge.evaluate(
            message=msg,
            recent_messages=[],
            is_mentioned=False,
            is_name_called=False,
            is_reply_to_bot=False,
        )
        # エンゲージメント(+40) + 疑問符(+20) - クールダウン(-50) = 10
        assert result.score == 10
        assert "エンゲージメント" in result.reason
        assert "クールダウン" in result.reason

    @patch("memory.judge.config")
    def test_engagement_expires(self, mock_config):
        """エンゲージメント期間が切れたらブーストなし"""
        mock_config.JUDGE_KEYWORDS = ""
        mock_config.COOLDOWN_SECONDS = 10
        mock_config.ENGAGEMENT_DURATION_SECONDS = 300
        mock_config.ENGAGEMENT_BOOST = 40
        mock_config.JUDGE_SCORE_THRESHOLD = 20
        mock_config.JUDGE_SCORE_FULL_RESPONSE = 60
        mock_config.JUDGE_SCORE_SHORT_ACK = 30
        mock_config.RESPONSE_DIVERSITY_ENABLED = False
        mock_config.BOT_NAME = "テストボット"

        judge = RuleBasedJudge()
        # 301秒前に応答 → エンゲージメント期間外
        judge._last_response_times[100] = datetime.now(timezone.utc) - timedelta(
            seconds=301
        )

        msg = _make_message(content="テスト？", channel_id=100)
        result = judge.evaluate(
            message=msg,
            recent_messages=[],
            is_mentioned=False,
            is_name_called=False,
            is_reply_to_bot=False,
        )
        # 疑問符(+20)のみ
        assert result.score == 20
        assert "エンゲージメント" not in result.reason

    @patch("memory.judge.config")
    def test_engagement_no_response_history(self, mock_config):
        """応答履歴がないチャンネルではエンゲージメントなし"""
        mock_config.JUDGE_KEYWORDS = ""
        mock_config.COOLDOWN_SECONDS = 120
        mock_config.ENGAGEMENT_DURATION_SECONDS = 300
        mock_config.ENGAGEMENT_BOOST = 40
        mock_config.JUDGE_SCORE_THRESHOLD = 20
        mock_config.JUDGE_SCORE_FULL_RESPONSE = 60
        mock_config.JUDGE_SCORE_SHORT_ACK = 30
        mock_config.RESPONSE_DIVERSITY_ENABLED = False
        mock_config.BOT_NAME = "テストボット"

        judge = RuleBasedJudge()

        msg = _make_message(content="テスト？", channel_id=999)
        result = judge.evaluate(
            message=msg,
            recent_messages=[],
            is_mentioned=False,
            is_name_called=False,
            is_reply_to_bot=False,
        )
        # 疑問符(+20)のみ
        assert result.score == 20
        assert "エンゲージメント" not in result.reason

    @patch("memory.judge.config")
    def test_engagement_different_channel_no_boost(self, mock_config):
        """別チャンネルの応答履歴はエンゲージメントに影響しない"""
        mock_config.JUDGE_KEYWORDS = ""
        mock_config.COOLDOWN_SECONDS = 10
        mock_config.ENGAGEMENT_DURATION_SECONDS = 300
        mock_config.ENGAGEMENT_BOOST = 40
        mock_config.JUDGE_SCORE_THRESHOLD = 20
        mock_config.JUDGE_SCORE_FULL_RESPONSE = 60
        mock_config.JUDGE_SCORE_SHORT_ACK = 30
        mock_config.RESPONSE_DIVERSITY_ENABLED = False
        mock_config.BOT_NAME = "テストボット"

        judge = RuleBasedJudge()
        # チャンネル200で応答
        judge.record_response(200)

        # チャンネル100のメッセージを評価
        msg = _make_message(content="テスト？", channel_id=100)
        result = judge.evaluate(
            message=msg,
            recent_messages=[],
            is_mentioned=False,
            is_name_called=False,
            is_reply_to_bot=False,
        )
        # 疑問符(+20)のみ、エンゲージメントなし
        assert result.score == 20
        assert "エンゲージメント" not in result.reason

    # === Phase 2A: 新ルールのテスト ===

    @patch("memory.judge.config")
    def test_two_person_conversation_penalty(self, mock_config):
        """2人会話で-20"""
        mock_config.JUDGE_KEYWORDS = ""
        mock_config.COOLDOWN_SECONDS = 120
        mock_config.JUDGE_SCORE_THRESHOLD = 20
        mock_config.JUDGE_SCORE_FULL_RESPONSE = 60
        mock_config.JUDGE_SCORE_SHORT_ACK = 30
        mock_config.RESPONSE_DIVERSITY_ENABLED = False
        mock_config.BOT_NAME = "テストボット"

        judge = RuleBasedJudge()
        recent = [
            _make_message(author_id=1, author_name="User1", content="hello"),
            _make_message(author_id=2, author_name="User2", content="hi"),
            _make_message(author_id=1, author_name="User1", content="how are you?"),
        ]
        msg = _make_message(content="テスト？")
        result = judge.evaluate(
            message=msg,
            recent_messages=recent,
            is_mentioned=False,
            is_name_called=False,
            is_reply_to_bot=False,
        )
        assert "2人会話" in result.reason

    @patch("memory.judge.config")
    def test_no_bot_mention_penalty(self, mock_config):
        """ボット言及なしで-10"""
        mock_config.JUDGE_KEYWORDS = ""
        mock_config.COOLDOWN_SECONDS = 120
        mock_config.JUDGE_SCORE_THRESHOLD = 20
        mock_config.JUDGE_SCORE_FULL_RESPONSE = 60
        mock_config.JUDGE_SCORE_SHORT_ACK = 30
        mock_config.RESPONSE_DIVERSITY_ENABLED = False
        mock_config.BOT_NAME = "テストボット"

        judge = RuleBasedJudge()
        recent = [
            _make_message(author_id=1, author_name="User1", content="hello"),
        ]
        msg = _make_message(content="テスト")
        result = judge.evaluate(
            message=msg,
            recent_messages=recent,
            is_mentioned=False,
            is_name_called=False,
            is_reply_to_bot=False,
        )
        assert "ボット言及なし" in result.reason

    @patch("memory.judge.config")
    def test_bot_mentioned_in_recent_no_penalty(self, mock_config):
        """ボット名が含まれていればペナルティなし"""
        mock_config.JUDGE_KEYWORDS = ""
        mock_config.COOLDOWN_SECONDS = 120
        mock_config.JUDGE_SCORE_THRESHOLD = 20
        mock_config.JUDGE_SCORE_FULL_RESPONSE = 60
        mock_config.JUDGE_SCORE_SHORT_ACK = 30
        mock_config.RESPONSE_DIVERSITY_ENABLED = False
        mock_config.BOT_NAME = "テストボット"

        judge = RuleBasedJudge()
        recent = [
            _make_message(
                author_id=1, author_name="User1",
                content="テストボットに聞いてみよう",
            ),
        ]
        msg = _make_message(content="テスト？")
        result = judge.evaluate(
            message=msg,
            recent_messages=recent,
            is_mentioned=False,
            is_name_called=False,
            is_reply_to_bot=False,
        )
        assert "ボット言及なし" not in result.reason

    @patch("memory.judge.config")
    def test_silence_after_gap(self, mock_config):
        """沈黙後の最初のメッセージで+10"""
        mock_config.JUDGE_KEYWORDS = ""
        mock_config.COOLDOWN_SECONDS = 120
        mock_config.JUDGE_SCORE_THRESHOLD = 20
        mock_config.JUDGE_SCORE_FULL_RESPONSE = 60
        mock_config.JUDGE_SCORE_SHORT_ACK = 30
        mock_config.RESPONSE_DIVERSITY_ENABLED = False
        mock_config.BOT_NAME = "テストボット"

        judge = RuleBasedJudge()
        recent = [
            _make_message(
                author_id=1, author_name="User1",
                content="テストボット おーい", minutes_ago=15,
            ),
            _make_message(
                author_id=2, author_name="User2",
                content="戻ってきた", minutes_ago=0,
            ),
        ]
        msg = _make_message(content="テスト")
        result = judge.evaluate(
            message=msg,
            recent_messages=recent,
            is_mentioned=False,
            is_name_called=False,
            is_reply_to_bot=False,
        )
        assert "沈黙後" in result.reason

    @patch("memory.judge.config")
    def test_response_type_full_response_when_disabled(self, mock_config):
        """RESPONSE_DIVERSITY_ENABLED=Falseなら常にfull_response"""
        mock_config.JUDGE_KEYWORDS = ""
        mock_config.COOLDOWN_SECONDS = 120
        mock_config.JUDGE_SCORE_THRESHOLD = 20
        mock_config.JUDGE_SCORE_FULL_RESPONSE = 60
        mock_config.JUDGE_SCORE_SHORT_ACK = 30
        mock_config.RESPONSE_DIVERSITY_ENABLED = False
        mock_config.BOT_NAME = "テストボット"

        judge = RuleBasedJudge()
        msg = _make_message(content="テスト")
        result = judge.evaluate(
            message=msg,
            recent_messages=[],
            is_mentioned=False,
            is_name_called=False,
            is_reply_to_bot=False,
        )
        assert result.response_type == "full_response"

    @patch("memory.judge.config")
    def test_response_type_mention_always_full(self, mock_config):
        """メンション時は常にfull_response"""
        mock_config.JUDGE_KEYWORDS = ""
        mock_config.COOLDOWN_SECONDS = 120
        mock_config.JUDGE_SCORE_THRESHOLD = 20
        mock_config.JUDGE_SCORE_FULL_RESPONSE = 60
        mock_config.JUDGE_SCORE_SHORT_ACK = 30
        mock_config.RESPONSE_DIVERSITY_ENABLED = True
        mock_config.BOT_NAME = "テストボット"

        judge = RuleBasedJudge()
        msg = _make_message()
        result = judge.evaluate(
            message=msg,
            recent_messages=[],
            is_mentioned=True,
            is_name_called=False,
            is_reply_to_bot=False,
        )
        assert result.response_type == "full_response"

    @patch("memory.judge.config")
    def test_judge_result_default_response_type(self, mock_config):
        """JudgeResultのデフォルトresponse_type"""
        result = JudgeResult(score=50, should_respond=True, reason="test")
        assert result.response_type == "full_response"


class TestHelperFunctions:
    """ヘルパー関数のテスト"""

    def test_count_unique_authors_empty(self):
        """空リストは0人"""
        assert _count_unique_authors([]) == 0

    def test_count_unique_authors_excludes_bot(self):
        """Bot著者は除外"""
        messages = [
            _make_message(author_id=1, is_bot=False),
            _make_message(author_id=2, is_bot=True),
            _make_message(author_id=3, is_bot=False),
        ]
        assert _count_unique_authors(messages) == 2

    def test_count_unique_authors_deduplicates(self):
        """同一著者は1回だけカウント"""
        messages = [
            _make_message(author_id=1, is_bot=False),
            _make_message(author_id=1, is_bot=False),
            _make_message(author_id=2, is_bot=False),
        ]
        assert _count_unique_authors(messages) == 2

    @patch("memory.judge.config")
    def test_has_bot_mention_true(self, mock_config):
        """BOT_NAMEを含むメッセージがあればTrue"""
        mock_config.BOT_NAME = "テストボット"
        messages = [
            _make_message(content="テストボット こんにちは"),
        ]
        assert _has_bot_mention_in_recent(messages) is True

    @patch("memory.judge.config")
    def test_has_bot_mention_false(self, mock_config):
        """BOT_NAMEを含まなければFalse"""
        mock_config.BOT_NAME = "テストボット"
        messages = [
            _make_message(content="こんにちは"),
        ]
        assert _has_bot_mention_in_recent(messages) is False

    @patch("memory.judge.config")
    def test_has_bot_mention_ignores_bot_messages(self, mock_config):
        """Botメッセージは無視"""
        mock_config.BOT_NAME = "テストボット"
        messages = [
            _make_message(content="テストボット です", is_bot=True),
        ]
        assert _has_bot_mention_in_recent(messages) is False

    def test_is_high_frequency_below_threshold(self):
        """10件未満はFalse"""
        messages = [_make_message(seconds_ago=i) for i in range(5)]
        assert _is_high_frequency(messages) is False

    def test_is_high_frequency_true(self):
        """10件が60秒以内ならTrue"""
        # 古い順に並べる（バッファと同じ順序）
        messages = [_make_message(seconds_ago=(9 - i) * 5) for i in range(10)]
        assert _is_high_frequency(messages) is True

    def test_is_high_frequency_false_spread_out(self):
        """10件が60秒超ならFalse"""
        # 古い順に並べる（バッファと同じ順序）
        messages = [_make_message(seconds_ago=(9 - i) * 10) for i in range(10)]
        assert _is_high_frequency(messages) is False

    def test_is_first_after_silence_true(self):
        """10分以上の間隔があればTrue"""
        messages = [
            _make_message(minutes_ago=15),
            _make_message(minutes_ago=0),
        ]
        assert _is_first_after_silence(messages) is True

    def test_is_first_after_silence_false(self):
        """10分未満の間隔ならFalse"""
        messages = [
            _make_message(minutes_ago=5),
            _make_message(minutes_ago=0),
        ]
        assert _is_first_after_silence(messages) is False

    def test_is_first_after_silence_too_few(self):
        """メッセージ1件以下はFalse"""
        assert _is_first_after_silence([_make_message()]) is False
        assert _is_first_after_silence([]) is False

    def test_detect_conversation_decay_no_decay(self):
        """減衰なしは0"""
        messages = [
            _make_message(content="a" * 50) for _ in range(6)
        ]
        assert _detect_conversation_decay(messages) == 0

    def test_detect_conversation_decay_moderate(self):
        """文字数が50-70%に低下で-10"""
        messages = [
            _make_message(content="a" * 100),
            _make_message(content="a" * 100),
            _make_message(content="a" * 100),
            _make_message(content="a" * 60),
            _make_message(content="a" * 60),
            _make_message(content="a" * 60),
        ]
        assert _detect_conversation_decay(messages) == -10

    def test_detect_conversation_decay_severe(self):
        """文字数が50%以下に低下で-15"""
        messages = [
            _make_message(content="a" * 100),
            _make_message(content="a" * 100),
            _make_message(content="a" * 100),
            _make_message(content="a" * 30),
            _make_message(content="a" * 30),
            _make_message(content="a" * 30),
        ]
        assert _detect_conversation_decay(messages) == -15

    def test_detect_conversation_decay_too_few(self):
        """メッセージ数不足は0"""
        messages = [_make_message() for _ in range(3)]
        assert _detect_conversation_decay(messages) == 0
