"""未解決の話題（open_topics）: 会話に残った「あとで触れる価値のある話題」

要約LLMが会話から抽出し、ChannelContext に保持する。
自発会話（issue #104 PR3）で「あの件どうなった？」と後から触れるための下準備。
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from log_utils.logger import logger
from memory.sanitize import sanitize_llm_text

JST = timezone(timedelta(hours=9), name="JST")

# plan: 予定・挑戦の結果待ち / question: 未回答の質問 / pending: 迷い中・相談中
VALID_KINDS = frozenset({"plan", "question", "pending"})
MAX_OPEN_TOPICS = 5
_MAX_TOPIC_TEXT_LENGTH = 100
_WEEKDAYS_JA = "月火水木金土日"


@dataclass
class OpenTopic:
    """未解決の話題1件

    Attributes:
        id: 話題の識別子（コード側で採番し、継続中は維持する）
        text: 話題の内容
        kind: 種類（plan / question / pending）
        follow_up_after: フォローに適した時刻（UTC）。推定できない場合は None
    """

    id: str
    text: str
    kind: str
    follow_up_after: datetime | None = None

    def to_dict(self) -> dict:
        """シリアライゼーション用の辞書を返す"""
        return {
            "id": self.id,
            "text": self.text,
            "kind": self.kind,
            "follow_up_after": (
                self.follow_up_after.isoformat() if self.follow_up_after else None
            ),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "OpenTopic | None":
        """永続化された辞書から復元する（不正なデータは None）

        Args:
            data: to_dict で保存した辞書

        Returns:
            復元した話題。id / text / kind のいずれかが不正なら None
        """
        if not isinstance(data, dict):
            return None
        topic_id = data.get("id")
        text = data.get("text")
        kind = data.get("kind")
        if not (isinstance(topic_id, str) and topic_id and isinstance(text, str) and text):
            return None
        if kind not in VALID_KINDS:
            return None
        return cls(
            id=topic_id,
            text=text,
            kind=kind,
            follow_up_after=parse_follow_up_after(data.get("follow_up_after")),
        )


def new_topic_id() -> str:
    """新しい話題の id を採番する（短い uuid）"""
    return uuid.uuid4().hex[:8]


def parse_follow_up_after(value: Any) -> datetime | None:
    """follow_up_after を UTC の aware datetime に正規化する

    タイムゾーンなしの値は JST とみなす（プロンプトで JST 基準を指示しているため）。

    Args:
        value: ISO8601 文字列、datetime、または None

    Returns:
        UTC の datetime。解釈できない場合は None
    """
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=JST)
    return parsed.astimezone(timezone.utc)


def load_open_topics(raw: Any) -> list[OpenTopic]:
    """永続化データから話題リストを復元する（旧データ・不正な要素に寛容）

    Args:
        raw: to_dict で保存したリスト（旧データではキーが無く None）

    Returns:
        復元できた話題のリスト
    """
    if not isinstance(raw, list):
        return []
    topics = [OpenTopic.from_dict(item) for item in raw]
    return [t for t in topics if t is not None][:MAX_OPEN_TOPICS]


def parse_open_topics_result(
    raw: Any, previous: list[OpenTopic]
) -> list[OpenTopic] | None:
    """要約LLMが返した open_topics を検証し、id を維持・採番する

    継続中の話題は前回の id を維持する。前回に存在しない id・null・重複した id は
    新しい話題として採番し直す。kind が不正な要素・text が空の要素は捨てる。

    Args:
        raw: LLM 出力の open_topics の値
        previous: 前回の open_topics（id の照合に使う）

    Returns:
        検証済みの話題リスト（最大 MAX_OPEN_TOPICS 件）。
        キーの欠落・型不正の場合は None（前回値を維持させる）
    """
    if not isinstance(raw, list):
        if raw is not None:
            logger.warning(f"要約LLMの open_topics が配列ではない: {type(raw)}")
        return None
    known_ids = {t.id for t in previous}
    used_ids: set[str] = set()
    topics: list[OpenTopic] = []
    for item in raw:
        topic = _parse_topic_item(item, known_ids, used_ids)
        if topic is None:
            continue
        used_ids.add(topic.id)
        topics.append(topic)
        if len(topics) >= MAX_OPEN_TOPICS:
            break
    return topics


def _parse_topic_item(
    item: Any, known_ids: set[str], used_ids: set[str]
) -> OpenTopic | None:
    """LLM 出力の話題1件を検証する（不正なら None）"""
    if not isinstance(item, dict):
        return None
    text = sanitize_llm_text(item.get("text"), _MAX_TOPIC_TEXT_LENGTH)
    kind = item.get("kind")
    if text is None or kind not in VALID_KINDS:
        return None
    raw_id = item.get("id")
    topic_id = raw_id if isinstance(raw_id, str) else None
    if topic_id is None or topic_id not in known_ids or topic_id in used_ids:
        topic_id = new_topic_id()
    return OpenTopic(
        id=topic_id,
        text=text,
        kind=kind,
        follow_up_after=parse_follow_up_after(item.get("follow_up_after")),
    )


def format_open_topics_for_prompt(topics: list[OpenTopic]) -> str:
    """前回の open_topics を要約プロンプト用の JSON 文字列にする（時刻は JST）

    Args:
        topics: 前回の open_topics

    Returns:
        JSON 配列の文字列（話題がなければ "[]"）
    """
    items = [
        {
            "id": t.id,
            "text": t.text,
            "kind": t.kind,
            "follow_up_after": (
                t.follow_up_after.astimezone(JST).isoformat(timespec="minutes")
                if t.follow_up_after
                else None
            ),
        }
        for t in topics
    ]
    return json.dumps(items, ensure_ascii=False)


def format_now_jst(now: datetime | None = None) -> str:
    """現在時刻を JST の ISO8601（曜日付き）で返す

    Args:
        now: 基準時刻（テスト用。省略時は現在時刻）

    Returns:
        例: "2026-11-24T21:30+09:00（火）"
    """
    current = (now or datetime.now(timezone.utc)).astimezone(JST)
    return f"{current.isoformat(timespec='minutes')}（{_WEEKDAYS_JA[current.weekday()]}）"
