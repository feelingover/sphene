"""ルールベースJudgeのテスト"""

# type: ignore
# mypy: ignore-errors

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from memory.judge import JudgeResult, RuleBasedJudge
from memory.short_term import ChannelMessage


def _make_message(
    content: str = "テストメッセージ",
    channel_id: int = 100,
    minutes_ago: int = 0,
) -> ChannelMessage:
    """テスト用ChannelMessageを生成するヘルパー"""
    return ChannelMessage(
        message_id=1,
        channel_id=channel_id,
        author_id=12345,
        author_name="TestUser",
        content=content,
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )


class TestRuleBasedJudge:
    """RuleBasedJudgeのテスト"""

    @patch("memory.judge.config")
    def test_mention_returns_100(self, mock_config):
        """@メンションで即スコア100"""
        mock_config.JUDGE_KEYWORDS = ""
        mock_config.COOLDOWN_SECONDS = 120
        mock_config.JUDGE_SCORE_THRESHOLD = 60

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
        mock_config.JUDGE_SCORE_THRESHOLD = 60

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
        mock_config.JUDGE_SCORE_THRESHOLD = 60

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
        mock_config.JUDGE_SCORE_THRESHOLD = 60

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
        mock_config.JUDGE_SCORE_THRESHOLD = 60

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
        mock_config.JUDGE_SCORE_THRESHOLD = 60

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
        mock_config.JUDGE_SCORE_THRESHOLD = 60

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
        mock_config.JUDGE_SCORE_THRESHOLD = 60

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
        mock_config.JUDGE_SCORE_THRESHOLD = 60

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
        mock_config.JUDGE_SCORE_THRESHOLD = 60

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
        mock_config.JUDGE_SCORE_THRESHOLD = 60

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
        mock_config.JUDGE_SCORE_THRESHOLD = 60

        judge = RuleBasedJudge()
        assert judge._keywords == []

    @patch("memory.judge.config")
    def test_record_response(self, mock_config):
        """record_responseでクールダウンが記録されること"""
        mock_config.JUDGE_KEYWORDS = ""
        mock_config.COOLDOWN_SECONDS = 120
        mock_config.JUDGE_SCORE_THRESHOLD = 60

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
        mock_config.JUDGE_SCORE_THRESHOLD = 60

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
        mock_config.JUDGE_SCORE_THRESHOLD = 60

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
        mock_config.JUDGE_SCORE_THRESHOLD = 60

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
        mock_config.JUDGE_SCORE_THRESHOLD = 60

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
        mock_config.JUDGE_SCORE_THRESHOLD = 60

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
