import base64
import json
import logging
import time
import traceback
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Type

import requests

# OpenAI エラータイプをインポート
from openai import (
    APIConnectionError,
    APIError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionAssistantMessageParam,
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionToolMessageParam,
)

from ai.client import get_client
from config import (
    OPENAI_MODEL,
    SYSTEM_PROMPT_FILENAME,
    SYSTEM_PROMPT_PATH,
)
from ai.tools import TOOL_DEFINITIONS, TOOL_FUNCTIONS
from log_utils.logger import logger
from utils.text_utils import truncate_text

# 定数の定義
MAX_CONVERSATION_AGE_MINUTES = 30
MAX_CONVERSATION_TURNS = 10  # 往復数の上限
MAX_TOOL_CALL_ROUNDS = 3  # ツール呼び出しの最大ラウンド数（無限ループ防止）

# プロンプトのキャッシュ
_prompt_cache: dict[str, str] = {}


def _load_prompt_from_local(
    fail_on_error: bool = False,
) -> str | None:
    """ローカルファイルからシステムプロンプトを読み込む

    Args:
        fail_on_error: 読み込みに失敗した場合に例外をスローするかどうか

    Returns:
        str | None: プロンプトの内容

    Raises:
        RuntimeError: fail_on_error=Trueで読み込みに失敗した場合
    """
    prompt_path = Path(SYSTEM_PROMPT_PATH)

    logger.info(f"ローカルからシステムプロンプトを読み込み: {prompt_path}")
    try:
        prompt_content = prompt_path.read_text(encoding="utf-8").strip()
        logger.info("ローカルからプロンプトを読み込みました")
        return prompt_content if prompt_content else None
    except Exception as e:
        error_msg = f"プロンプト読み込みエラー: {str(e)}"
        logger.error(error_msg, exc_info=True)

        if fail_on_error:
            raise RuntimeError(
                f"システムプロンプトの読み込みに失敗しました: {error_msg}"
            ) from e

        return None


def _get_default_prompt() -> str:
    """デフォルトプロンプトを取得

    Returns:
        str: デフォルトプロンプト
    """
    return "あなたは役立つAIアシスタントです。"


def load_system_prompt(force_reload: bool = False, fail_on_error: bool = False) -> str:
    """システムプロンプトをファイルから読み込む
    初回のみストレージからロードし、以降はキャッシュから取得する

    Args:
        force_reload: キャッシュを無視して強制的に再読込する場合はTrue
        fail_on_error: 読み込みに失敗した場合に例外をスローするかどうか

    Returns:
        str: システムプロンプトの内容

    Raises:
        RuntimeError: fail_on_error=Trueで読み込みに失敗した場合
    """
    # キャッシュがあり、強制再読込でない場合はキャッシュから返す
    if SYSTEM_PROMPT_FILENAME in _prompt_cache and not force_reload:
        logger.info(f"キャッシュからシステムプロンプト利用: {SYSTEM_PROMPT_FILENAME}")
        return _prompt_cache[SYSTEM_PROMPT_FILENAME]

    # プロンプト読み込み
    prompt_content = _load_prompt_from_local(fail_on_error)

    # デフォルトフォールバック
    if not prompt_content:
        prompt_content = _get_default_prompt()
        logger.info("デフォルトプロンプトを使用")

    # キャッシュに保存
    _prompt_cache[SYSTEM_PROMPT_FILENAME] = prompt_content

    return prompt_content


def reload_system_prompt(fail_on_error: bool = False) -> bool:
    """システムプロンプトを強制的に再読み込みする

    Args:
        fail_on_error: 読み込みに失敗した場合に例外をスローするかどうか

    Returns:
        bool: 成功した場合はTrue

    Raises:
        RuntimeError: fail_on_error=Trueで読み込みに失敗した場合
    """
    try:
        load_system_prompt(force_reload=True, fail_on_error=fail_on_error)
        return True
    except Exception as e:
        logger.error(f"プロンプト再読み込みエラー: {str(e)}", exc_info=True)
        if fail_on_error:
            raise
        return False


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
        self.input_list: list[ChatCompletionMessageParam] = [self.system]
        self.logs: list[ChatCompletion] = []
        # 会話の有効期限を設定（30分）
        self.last_interaction: datetime | None = datetime.now()
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
        """長くなった会話履歴を整理する

        ツール呼び出しメッセージのシーケンスが壊れないよう、
        安全な切断ポイントを見つけてトリミングする。
        """
        # システムメッセージ + 往復N回分だけ保持
        max_messages = 1 + (MAX_CONVERSATION_TURNS * 2)

        if len(self.input_list) <= max_messages:
            return

        # システムメッセージを保持
        system_message = self.input_list[0]
        # 直近のメッセージだけを残す
        recent_messages = self.input_list[-(max_messages - 1) :]

        # 先頭がtoolメッセージやtool_calls付きassistantの場合、
        # 安全な開始位置（userメッセージ）まで進める
        start_idx = 0
        for i, msg in enumerate(recent_messages):
            role = msg.get("role", "")
            if role == "user":
                start_idx = i
                break
            if role == "assistant" and "tool_calls" not in msg:
                start_idx = i
                break

        self.input_list = [system_message] + recent_messages[start_idx:]
        logger.info(
            f"会話履歴を整理しました（残りメッセージ数: {len(self.input_list)}）"
        )

    # エラータイプと対応するメッセージ、ログレベルをマッピング
    _OPENAI_ERROR_HANDLERS: dict[Type[APIError], tuple[int, str, str]] = {
        AuthenticationError: (
            logging.ERROR,
            "OpenAI API認証エラー: {}",
            "ごめんね、AIとの接続設定で問題が発生しているみたい…😢 管理者に連絡してみてね。",
        ),
        PermissionDeniedError: (
            logging.ERROR,
            "OpenAI API権限エラー: {}",
            "ごめんね、AIを使うための権限がないみたい…😢 管理者に確認してみてね。",
        ),
        NotFoundError: (
            logging.ERROR,
            "OpenAI APIモデルが見つからないエラー: {}",
            f"ごめんね、指定されたAIモデル「{OPENAI_MODEL}」が見つからないみたい…😢",
        ),
        RateLimitError: (
            logging.WARNING,  # レート制限は警告レベル
            "OpenAI APIレート制限エラー: {}",
            "ごめんね、今ちょっとAIが混み合ってるみたい…💦 少し時間を置いてからもう一度話しかけてみてね！",
        ),
        APIConnectionError: (  # 接続エラーはAPIErrorのサブクラスだが個別処理
            logging.ERROR,
            "OpenAI API接続エラー: {}",
            "ごめんね、AIとの接続で問題が発生しちゃった…😢 ネットワークを確認してもう一度試してみてね。",
        ),
        APITimeoutError: (  # タイムアウトも個別処理
            logging.ERROR,
            "OpenAI APIタイムアウトエラー: {}",
            "ごめんね、AIからの応答が時間内に返ってこなかったみたい…😢 もう一度試してみてくれる？",
        ),
        InternalServerError: (
            logging.ERROR,
            "OpenAI APIサーバーエラー: {}",
            "ごめんね、AI側で一時的な問題が発生しているみたい…😢 しばらくしてからもう一度試してみてね。",
        ),
        APIStatusError: (  # その他のステータスエラー
            logging.ERROR,
            "OpenAI APIステータスエラー (Code: {}): {}",
            "ごめんね、AIとの通信で予期せぬエラーが発生しちゃった…😢",
        ),
        APIResponseValidationError: (
            logging.ERROR,
            "OpenAI APIレスポンス検証エラー: {}",
            "ごめんね、AIからの応答がおかしかったみたい…🤔 もう一度試してみてね。",
        ),
        BadRequestError: (
            logging.ERROR,
            "OpenAI APIリクエストエラー: {}",
            "ごめんね、AIへのリクエスト内容に問題があったみたい…😢 メッセージを変えて試してみてね。",
        ),
        # APIError は上記以外のAPI関連エラーをキャッチ
        APIError: (
            logging.ERROR,
            "OpenAI API関連エラー: {}",
            "ごめんね、AIとのやり取りでエラーが発生しちゃった…😢",
        ),
    }

    def _handle_openai_error(self, error: Exception) -> str:
        """OpenAI APIエラーを処理し、ユーザーメッセージを返す

        Args:
            error: 処理するエラー

        Returns:
            str: ユーザーに表示するエラーメッセージ
        """
        error_body = getattr(error, "body", str(error))
        status_code = getattr(error, "status_code", None)

        for error_type, (
            level,
            log_template,
            user_msg,
        ) in self._OPENAI_ERROR_HANDLERS.items():
            if isinstance(error, error_type):
                log_args = [error_body]
                if error_type is APIStatusError and status_code is not None:
                    log_args.insert(0, status_code)  # ステータスコードを先頭に追加
                logger.log(level, log_template.format(*log_args), exc_info=True)
                return user_msg

        # マッピングにない予期せぬエラー
        tb_str = traceback.format_exc()
        logger.critical(
            f"API呼び出し中の予期せぬエラー型 ({type(error).__name__}): {str(error)}\n{tb_str}"
        )
        return "ごめん！AIとの通信中に予期せぬエラーが発生しちゃった...😢"

    def _execute_tool_calls(
        self, tool_calls: list,
    ) -> list[ChatCompletionToolMessageParam]:
        """ツール呼び出しを実行し、結果メッセージを返す

        Args:
            tool_calls: OpenAI APIから返されたtool_callsリスト

        Returns:
            ツール結果メッセージのリスト
        """
        tool_messages: list[ChatCompletionToolMessageParam] = []

        for tool_call in tool_calls:
            function_name = tool_call.function.name
            tool_call_id = tool_call.id

            logger.info(f"ツール呼び出し: {function_name}, ID: {tool_call_id}")

            func = TOOL_FUNCTIONS.get(function_name)
            if func is None:
                logger.warning(f"未知のツール関数: {function_name}")
                result_content = json.dumps(
                    {"error": f"未知の関数: {function_name}"},
                    ensure_ascii=False,
                )
            else:
                try:
                    arguments = json.loads(tool_call.function.arguments)
                    logger.debug(f"ツール引数: {function_name}({arguments})")
                    result_content = func(**arguments)
                except json.JSONDecodeError as e:
                    logger.error(
                        f"ツール引数のJSONパースエラー: {function_name}: {str(e)}",
                        exc_info=True,
                    )
                    result_content = json.dumps(
                        {"error": "引数のパースに失敗しました"},
                        ensure_ascii=False,
                    )
                except Exception as e:
                    logger.error(
                        f"ツール実行エラー: {function_name}: {str(e)}",
                        exc_info=True,
                    )
                    result_content = json.dumps(
                        {"error": "ツールの実行中にエラーが発生しました"},
                        ensure_ascii=False,
                    )

            tool_message: ChatCompletionToolMessageParam = {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": result_content,
            }
            tool_messages.append(tool_message)

        return tool_messages

    def _call_with_tool_loop(self) -> tuple[bool, str]:
        """OpenAI APIを呼び出し、ツール呼び出しがあればループ処理する

        Returns:
            tuple[bool, str]: (成功フラグ, 応答内容またはエラーメッセージ)

        Raises:
            OpenAI API関連の例外は呼び出し元に伝播する
        """
        for round_num in range(MAX_TOOL_CALL_ROUNDS + 1):
            result = get_client().chat.completions.create(
                model=OPENAI_MODEL,
                messages=self.input_list,
                tools=TOOL_DEFINITIONS,
            )
            self.logs.append(result)

            message = result.choices[0].message

            # ツール呼び出しがある場合
            if message.tool_calls:
                logger.info(
                    f"ツール呼び出し検出（ラウンド {round_num + 1}）: "
                    f"{len(message.tool_calls)}件"
                )

                # アシスタントメッセージ（tool_calls付き）を履歴に追加
                assistant_tool_message: ChatCompletionAssistantMessageParam = {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,  # type: ignore[union-attr]
                                "arguments": tc.function.arguments,  # type: ignore[union-attr]
                            },
                        }
                        for tc in message.tool_calls
                    ],
                }
                self.input_list.append(assistant_tool_message)

                # ツールを実行して結果を追加
                tool_messages = self._execute_tool_calls(message.tool_calls)
                for tool_msg in tool_messages:
                    self.input_list.append(tool_msg)

                continue

            # ツール呼び出しなし → 最終応答
            response_content = message.content
            if response_content:
                logger.debug(
                    f"OpenAI APIレスポンス受信: {truncate_text(response_content)}"
                )
                return True, response_content
            else:
                logger.warning("OpenAI APIからの応答が空です")
                return False, "ごめんね、AIからの応答が空だったみたい…🤔"

        # MAX_TOOL_CALL_ROUNDSを超えた場合
        logger.warning(
            f"ツール呼び出しが最大ラウンド数({MAX_TOOL_CALL_ROUNDS})を超過"
        )
        return False, "ごめんね、処理が複雑すぎてうまくいかなかったみたい…😢"

    def _call_openai_api(
        self, with_images: bool = False, max_retries: int = 2
    ) -> tuple[bool, str]:
        """OpenAI APIを呼び出し、ツール呼び出しを処理し、結果を返す

        ツール呼び出しが含まれる場合は自動的に実行し、結果を添えて再度APIを呼ぶ。
        一時的なエラー（接続エラー、タイムアウト、レート制限）の場合は
        指数バックオフで自動的に再試行します。

        Args:
            with_images: 画像が含まれているかどうか（マルチモーダルリクエスト）
            max_retries: 一時的なエラー時の最大再試行回数（デフォルト: 2）

        Returns:
            tuple[bool, str]: (成功フラグ, 応答内容またはエラーメッセージ)
                - 成功時: (True, AI応答テキスト)
                - 失敗時: (False, ユーザー向けエラーメッセージ)

        Note:
            再試行可能なエラー: APIConnectionError, APITimeoutError, RateLimitError
            待機時間: 2^試行回数 秒（1回目=0.5秒、2回目=1秒、3回目=2秒）
        """
        # 再試行対象のエラータイプ
        retry_error_types = (APIConnectionError, APITimeoutError, RateLimitError)

        for attempt in range(max_retries + 1):  # 初回 + 最大再試行回数
            try:
                # ログメッセージ構築
                if with_images:
                    log_msg = f"OpenAI APIリクエスト送信（モデル: {OPENAI_MODEL}, マルチモーダル）"
                else:
                    log_msg = f"OpenAI APIリクエスト送信（モデル: {OPENAI_MODEL}, テキストのみ）"

                if attempt > 0:
                    logger.info(f"再試行 {attempt}/{max_retries}: {log_msg}")
                else:
                    logger.info(log_msg)

                # ツール呼び出しループ（内部でAPI呼び出し・ツール実行を処理）
                return self._call_with_tool_loop()

            except retry_error_types as e:  # 再試行可能なエラー
                if attempt < max_retries:
                    # 指数バックオフ（徐々に待機時間を増やす）
                    wait_time = (2**attempt) * 0.5  # 0.5秒, 1秒, 2秒...
                    logger.warning(
                        f"一時的なエラーが発生したため再試行します（{attempt + 1}/{max_retries}）: "
                        f"{e.__class__.__name__}: {str(e)}. {wait_time}秒後に再試行"
                    )

                    time.sleep(wait_time)
                    continue
                else:
                    # 再試行回数を超えた場合はエラー処理
                    user_message = self._handle_openai_error(e)
                    return False, user_message
            except APIError as e:  # その他のOpenAI API関連エラー
                user_message = self._handle_openai_error(e)
                return False, user_message
            except Exception as e:  # その他の予期せぬエラー
                tb_str = traceback.format_exc()
                logger.critical(f"API呼び出し中の予期せぬエラー: {str(e)}\n{tb_str}")
                return (
                    False,
                    "ごめん！AIとの通信中に予期せぬエラーが発生しちゃった...😢",
                )

        # フォールバック（理論上到達しない）
        logger.error("OpenAI API呼び出しが不完全終了：全試行完了したが結果が不明")
        return False, "ごめん！AIとの通信中に問題が発生しちゃった...😢"

    def input_message(
        self, input_text: str | None, image_urls: list[str] | None = None
    ) -> str | None:
        """ユーザーからのメッセージを処理し、AIからの応答を返す

        Args:
            input_text: ユーザーからの入力テキスト
            image_urls: 添付画像のURLリスト

        Returns:
            str | None: AIからの応答、エラー時はNone
        """
        if not isinstance(input_text, str) or not input_text.strip():
            logger.warning("受信したメッセージが無効です")
            return None

        try:
            self.update_interaction_time()
            # 型ガードを行う
            input_str: str = input_text if isinstance(input_text, str) else ""
            preview = truncate_text(input_str)

            # 画像URLリストの安全な処理
            safe_image_urls: list[str] = (
                image_urls if isinstance(image_urls, list) else []
            )
            with_images = len(safe_image_urls) > 0

            # 画像付きかテキストのみかでログメッセージを変更
            if with_images:
                logger.debug(
                    f"画像付きユーザーメッセージを受信: {preview}, 画像数: {len(safe_image_urls)}"
                )
                # 画像処理
                processed_images = self._process_images(safe_image_urls)
                if processed_images:
                    # テキスト + 画像のマルチモーダルメッセージを作成
                    # マルチモーダルコンテンツは型チェックが厳密なため明示的に無視する
                    content: list[dict[str, Any]] = [{"type": "text", "text": input_text}]  # type: ignore
                    for img in processed_images:
                        content.append(img)  # type: ignore

                    # 型チェックを通すためにキャストする
                    user_message: ChatCompletionMessageParam = {
                        "role": "user",
                        "content": content,  # type: ignore
                    }
                else:
                    # 画像処理に失敗した場合はテキストのみで処理
                    logger.warning("画像処理に失敗したため、テキストのみで処理します")
                    user_message = {"role": "user", "content": input_text}
            else:
                # 通常のテキストメッセージ
                logger.debug(f"テキストのみのユーザーメッセージを受信: {preview}")
                user_message = {"role": "user", "content": input_text}

            # ユーザーメッセージを追加
            self.input_list.append(user_message)

            # OpenAI API呼び出しとエラーハンドリング
            success, content_or_error_msg = self._call_openai_api(
                with_images=with_images
            )

            if success:
                # 成功した場合、応答を履歴に追加して返す
                assistant_message: ChatCompletionAssistantMessageParam = {
                    "role": "assistant",
                    "content": content_or_error_msg,  # 成功時は応答内容
                }
                self.input_list.append(assistant_message)
                self.trim_conversation_history()
                return content_or_error_msg
            else:
                # 失敗した場合、エラーメッセージを返す
                # 失敗時はAPI呼び出し側でログ出力済み
                return content_or_error_msg  # 失敗時はエラーメッセージ

        except Exception as e:
            # API呼び出し以外の予期せぬエラー
            tb_str = traceback.format_exc()
            logger.critical(f"input_message処理中に予期せぬエラー: {str(e)}\n{tb_str}")
            return "ごめん！処理中に予期せぬエラーが発生しちゃった...😢"

    def _process_images(self, image_urls: list[str]) -> list[dict[str, Any]]:
        """画像URLを処理してOpenAI API用のフォーマットに変換

        各画像URLに対してHEADリクエストを送信し、アクセス可能かを確認:
        - アクセス可能（200 OK）: URL方式で送信
        - アクセス不可: Base64エンコードして送信（フォールバック）

        Args:
            image_urls: 画像のURLリスト

        Returns:
            list[dict[str, Any]]: OpenAI APIフォーマットの画像リスト
                各要素: {"type": "image_url", "image_url": {"url": <URLまたはData URI>}}

        Note:
            失敗した画像はスキップされ、エラーログが記録されます
        """
        processed_images = []

        for url in image_urls:
            try:
                # まずURLとして直接アクセス可能か確認
                response = requests.head(url, timeout=3)
                if response.status_code == 200:
                    # 成功したら直接URL方式
                    logger.debug(f"画像処理: URLとして使用 - {url}")
                    processed_images.append(
                        {"type": "image_url", "image_url": {"url": url}}
                    )
                else:
                    # ステータスコードが200以外ならBase64方式にフォールバック
                    logger.debug(
                        f"画像URLアクセス失敗 (ステータスコード: {response.status_code}) - Base64変換実行"
                    )
                    image_data = self._download_and_encode_image(url)
                    processed_images.append(
                        {"type": "image_url", "image_url": {"url": image_data}}
                    )
            except Exception as e:
                # リクエスト失敗時もBase64方式にフォールバック
                try:
                    logger.debug(f"画像URL直接アクセス失敗 ({str(e)}) - Base64変換実行")
                    image_data = self._download_and_encode_image(url)
                    processed_images.append(
                        {"type": "image_url", "image_url": {"url": image_data}}
                    )
                except Exception as e2:
                    logger.error(f"画像処理完全失敗: {url} - {str(e2)}", exc_info=True)

        return processed_images

    def _download_and_encode_image(self, url: str) -> str:
        """画像をダウンロードしてBase64エンコードする

        Args:
            url: 画像のURL

        Returns:
            str: Base64エンコードされた画像データ
        """
        response = requests.get(url, timeout=5)
        response.raise_for_status()

        image_data = response.content
        image_b64 = base64.b64encode(image_data).decode("utf-8")

        # MIMEタイプを検出（ヘッダーから取得またはURLから推測）
        content_type = response.headers.get("Content-Type")
        if not content_type or not content_type.startswith("image/"):
            # URLからMIMEタイプを推測
            if url.lower().endswith(".jpg") or url.lower().endswith(".jpeg"):
                content_type = "image/jpeg"
            elif url.lower().endswith(".png"):
                content_type = "image/png"
            elif url.lower().endswith(".gif"):
                content_type = "image/gif"
            elif url.lower().endswith(".webp"):
                content_type = "image/webp"
            else:
                content_type = "image/jpeg"  # デフォルト

        logger.debug(f"画像処理: Base64変換を使用 - MIME: {content_type}")
        return f"data:{content_type};base64,{image_b64}"


# ユーザーごとの会話インスタンスを保持する辞書
user_conversations: defaultdict[str, Sphene] = defaultdict(
    lambda: Sphene(system_setting=load_system_prompt())
)


def generate_contextual_response(
    channel_context: str,
    trigger_message: str,
    system_prompt: str | None = None,
) -> str | None:
    """チャンネルコンテキスト付きの1-shot応答を生成する

    既存のuser_conversationsとは独立して動作する。
    会話履歴は持たず、チャンネルの流れから1回だけ応答する。

    Args:
        channel_context: チャンネルの直近メッセージのコンテキスト
        trigger_message: 応答のトリガーとなったメッセージ
        system_prompt: システムプロンプト（Noneの場合はキャッシュから取得）

    Returns:
        str | None: AI応答、エラー時はNone
    """
    try:
        if system_prompt is None:
            system_prompt = load_system_prompt()

        # コンテキスト付きのシステムプロンプトを構築
        contextual_prompt = (
            f"{system_prompt}\n\n"
            f"--- チャンネルの直近の会話 ---\n{channel_context}\n---\n\n"
            f"上記の会話の流れを踏まえて、自然に会話に参加してください。"
            f"リプライではなく、会話の一参加者として自然に発言してください。"
        )

        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": contextual_prompt},
            {"role": "user", "content": trigger_message},
        ]

        logger.info("コンテキスト応答を生成中")
        result = get_client().chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
        )

        content = result.choices[0].message.content
        if content:
            logger.debug(f"コンテキスト応答生成完了: {truncate_text(content)}")
            return content
        else:
            logger.warning("コンテキスト応答が空です")
            return None

    except Exception as e:
        # Spheneの_handle_openai_errorと同じパターンでログ出力
        logger.error(f"コンテキスト応答生成エラー: {str(e)}", exc_info=True)
        return None


def cleanup_expired_conversations() -> int:
    """期限切れの会話をメモリから削除する

    Returns:
        int: 削除されたエントリ数
    """
    expired_ids = [
        user_id for user_id, api in user_conversations.items() if api.is_expired()
    ]
    for user_id in expired_ids:
        del user_conversations[user_id]

    if expired_ids:
        logger.info(f"期限切れの会話をクリーンアップしました: {len(expired_ids)}件")
    return len(expired_ids)
