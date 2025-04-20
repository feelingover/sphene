import logging
import traceback
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import DefaultDict, Dict, List, Optional, Tuple, Type

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
    ChatCompletionUserMessageParam,
)

from ai.client import client as aiclient
from config import (
    OPENAI_MODEL,
    PROMPT_STORAGE_TYPE,
    S3_BUCKET_NAME,
    S3_FOLDER_PATH,
    SYSTEM_PROMPT_FILENAME,
    SYSTEM_PROMPT_PATH,
)
from log_utils.logger import logger
from utils.s3_utils import S3Helper
from utils.text_utils import truncate_text

# 定数の定義
MAX_CONVERSATION_AGE_MINUTES = 30
MAX_CONVERSATION_TURNS = 10  # 往復数の上限

# プロンプトのキャッシュ
_prompt_cache: Dict[str, str] = {}


def _load_prompt_from_s3() -> tuple[Optional[str], List[str]]:
    """S3からシステムプロンプトを読み込む

    Returns:
        tuple: (プロンプトの内容, エラーメッセージのリスト)
    """
    errors = []
    prompt_content = None

    if not S3_BUCKET_NAME:
        error_msg = "S3バケット名が設定されていません。ローカルファイルを使用します。"
        logger.warning(error_msg)
        errors.append(error_msg)
        return None, errors

    logger.info(f"S3からシステムプロンプトを読み込み: {SYSTEM_PROMPT_FILENAME}")
    prompt_content = S3Helper.read_file_from_s3(
        S3_BUCKET_NAME, SYSTEM_PROMPT_FILENAME, S3_FOLDER_PATH
    )
    if prompt_content:
        logger.info("S3からプロンプトを読み込みました")
    else:
        error_msg = "S3からプロンプトの読み込みに失敗。ローカルにフォールバック"
        logger.warning(error_msg)
        errors.append(error_msg)

    return prompt_content, errors


def _load_prompt_from_local(
    fail_on_error: bool = False,
) -> tuple[Optional[str], List[str]]:
    """ローカルファイルからシステムプロンプトを読み込む

    Args:
        fail_on_error: 読み込みに失敗した場合に例外をスローするかどうか

    Returns:
        tuple: (プロンプトの内容, エラーメッセージのリスト)

    Raises:
        RuntimeError: fail_on_error=Trueで読み込みに失敗した場合
    """
    errors = []
    prompt_content = None

    if PROMPT_STORAGE_TYPE.lower() == "local":
        prompt_path = Path(SYSTEM_PROMPT_PATH)
    else:
        prompt_path = Path(__file__).parent.parent / "prompts" / SYSTEM_PROMPT_FILENAME

    logger.info(f"ローカルからシステムプロンプトを読み込み: {prompt_path}")
    try:
        prompt_content = prompt_path.read_text(encoding="utf-8").strip()
        logger.info("ローカルからプロンプトを読み込みました")
    except Exception as e:
        error_msg = f"プロンプト読み込みエラー: {str(e)}"
        logger.error(error_msg, exc_info=True)
        errors.append(error_msg)

        if fail_on_error:
            raise RuntimeError(
                f"システムプロンプトの読み込みに失敗しました: {error_msg}"
            )

        # デフォルトの最小限のプロンプト
        prompt_content = "あなたは役立つAIアシスタントです。"
        logger.info("デフォルトプロンプトを使用")

    return prompt_content, errors


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

    # ストレージからプロンプトを読み込む
    prompt_content = None
    errors = []

    # S3から読み込む場合
    if PROMPT_STORAGE_TYPE.lower() == "s3":
        prompt_content, s3_errors = _load_prompt_from_s3()
        errors.extend(s3_errors)

    # ローカルから読み込む場合（S3読み込み失敗時を含む）
    if not prompt_content:
        try:
            prompt_content, local_errors = _load_prompt_from_local(fail_on_error=False)
            errors.extend(local_errors)
        except RuntimeError as e:
            if fail_on_error:
                raise
            logger.error(f"ローカルからの読み込みエラー: {str(e)}", exc_info=True)

    # 両方失敗し、fail_on_errorがTrueの場合は例外をスロー
    if not prompt_content and fail_on_error:
        error_msg = "S3とローカルの両方からプロンプトの読み込みに失敗しました"
        logger.error(error_msg)
        raise RuntimeError(f"{error_msg}: {'; '.join(errors)}")

    # prompt_contentがNoneの場合はデフォルト値を設定
    if prompt_content is None:
        prompt_content = "あなたは役立つAIアシスタントです。"
        logger.info("デフォルトプロンプトを使用")

    # この時点でprompt_contentは必ずstr型なので、明示的に型を保証
    final_prompt: str = (
        prompt_content
        if prompt_content is not None
        else "あなたは役立つAIアシスタントです。"
    )

    # キャッシュに保存
    _prompt_cache[SYSTEM_PROMPT_FILENAME] = final_prompt

    return final_prompt


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
        self.input_list: List[ChatCompletionMessageParam] = [self.system]
        self.logs: List[ChatCompletion] = []
        # 会話の有効期限を設定（30分）
        self.last_interaction: Optional[datetime] = datetime.now()
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
        """長くなった会話履歴を整理する"""
        # システムメッセージ + 往復N回分だけ保持
        max_messages = 1 + (MAX_CONVERSATION_TURNS * 2)

        if len(self.input_list) > max_messages:
            # システムメッセージを保持
            system_message = self.input_list[0]
            # 直近のメッセージだけを残す
            self.input_list = [system_message] + self.input_list[-(max_messages - 1) :]
            logger.info(
                f"会話履歴を整理しました（残りメッセージ数: {len(self.input_list)}）"
            )

    # エラータイプと対応するメッセージ、ログレベルをマッピング
    _OPENAI_ERROR_HANDLERS: Dict[Type[APIError], Tuple[int, str, str]] = {
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
        """OpenAI APIエラーを処理し、ユーザーメッセージを返す"""
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

    def _call_openai_api(self) -> Tuple[bool, str]:
        """OpenAI APIを呼び出し、結果またはエラーメッセージを返す

        Returns:
            Tuple[bool, str]: (成功フラグ, 応答内容またはエラーメッセージ)
        """
        try:
            # OpenAI APIにリクエストを送信
            logger.info(f"OpenAI APIリクエスト送信（モデル: {OPENAI_MODEL}）")
            result = aiclient.chat.completions.create(
                model=OPENAI_MODEL, messages=self.input_list
            )
            self.logs.append(result)

            # 応答を処理
            response_content = result.choices[0].message.content
            if response_content:
                logger.info(
                    f"OpenAI APIレスポンス受信: {truncate_text(response_content)}"
                )
                return True, response_content
            else:
                logger.warning("OpenAI APIからの応答が空です")
                return False, "ごめんね、AIからの応答が空だったみたい…🤔"

        except APIError as e:  # OpenAIのAPI関連エラーをまとめてキャッチ
            user_message = self._handle_openai_error(e)
            return False, user_message
        except Exception as e:  # その他の予期せぬエラー
            tb_str = traceback.format_exc()
            logger.critical(f"API呼び出し中の予期せぬエラー: {str(e)}\n{tb_str}")
            return False, "ごめん！AIとの通信中に予期せぬエラーが発生しちゃった...😢"

    def input_message(self, input_text: Optional[str]) -> Optional[str]:
        """ユーザーからのメッセージを処理し、AIからの応答を返す

        Args:
            input_text: ユーザーからの入力テキスト

        Returns:
            Optional[str]: AIからの応答、エラー時はNone
        """
        if not isinstance(input_text, str) or not input_text.strip():
            logger.warning("受信したメッセージが無効です")
            return None

        try:
            self.update_interaction_time()

            # 型ガード後の変数を定義してからスライシング
            input_str: str = input_text
            preview = truncate_text(input_str)
            logger.info(f"ユーザーメッセージを受信: {preview}")

            # ユーザーメッセージを追加
            user_message: ChatCompletionUserMessageParam = {
                "role": "user",
                "content": input_text,
            }
            self.input_list.append(user_message)

            # OpenAI API呼び出しとエラーハンドリング
            success, content_or_error_msg = self._call_openai_api()

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


# ユーザーごとの会話インスタンスを保持する辞書
user_conversations: DefaultDict[str, Sphene] = defaultdict(
    lambda: Sphene(system_setting=load_system_prompt())
)
