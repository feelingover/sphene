"""
チャンネル設定（チャンネルリスト・評価モード）を管理するモジュール
シングルトンパターンで実装し、複数ファイルからのアクセスでも同じ設定を共有する
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import config
from log_utils.logger import logger

# S3クライアントはboto3を直接使用するように変更

# シングルトンインスタンスを格納する変数
_channel_config_instance = None


class ChannelConfig:
    """
    チャンネルリストと評価モード（許可/拒否）の設定を管理するクラス。
    設定をJSONファイルとして保存・読み込みできる。
    シングルトン実装：クラスごとに一つのインスタンスのみ維持。
    """

    @staticmethod
    def get_instance(
        storage_type: Optional[str] = None, debug_mode: bool = False
    ) -> "ChannelConfig":
        """
        シングルトンインスタンスを取得する

        Args:
            storage_type: 'local' or 's3' or None (Noneの場合はconfig設定を使用)
            debug_mode: テスト時などにTrue、実際のファイル/S3操作をスキップ

        Returns:
            ChannelConfig: シングルトンインスタンス
        """
        global _channel_config_instance

        # テスト時はdebug_mode=Trueでそれぞれ独立したインスタンスを生成する
        if debug_mode:
            logger.debug("ChannelConfig: テスト用の独立インスタンスを生成")
            return ChannelConfig(storage_type, debug_mode, is_singleton_call=True)

        # 通常はシングルトンインスタンスを返す
        if _channel_config_instance is None:
            logger.info("ChannelConfig: シングルトンインスタンスを初期化")
            _channel_config_instance = ChannelConfig(
                storage_type, debug_mode, is_singleton_call=True
            )
        else:
            # 必要に応じて設定を再読み込み
            logger.debug("ChannelConfig: 既存のシングルトンインスタンスを再利用")
            if not _channel_config_instance.debug_mode:
                _channel_config_instance.load_config()

        return _channel_config_instance

    def __init__(
        self,
        storage_type: Optional[str] = None,
        debug_mode: bool = False,
        is_singleton_call: bool = False,
    ):
        """
        初期化 - 直接呼び出し禁止！get_instanceメソッドを使用すること

        Args:
            storage_type: 'local' or 's3' or None (Noneの場合はconfig設定を使用)
            debug_mode: テスト時などにTrue、実際のファイル/S3操作をスキップ
            is_singleton_call: シングルトンからの呼び出しかどうか（内部使用）
        """
        if not (debug_mode or is_singleton_call):
            logger.warning(
                "ChannelConfigの直接インスタンス化は非推奨です。"
                "ChannelConfig.get_instance()を使用してください。"
            )
        """
        Args:
            storage_type: 'local' or 's3' or None (Noneの場合はconfig設定を使用)
            debug_mode: テスト時などにTrue、実際のファイル/S3操作をスキップ
        """
        self.debug_mode = debug_mode
        self.storage_type = storage_type or config.CHANNEL_CONFIG_STORAGE_TYPE
        self.config_data: Dict[str, Any] = {
            "behavior": "deny",  # デフォルトは全体モード
            "channels": [],
            "updated_at": datetime.now().isoformat(),
        }

        # 初期化時のデバッグ情報
        logger.info(
            f"ChannelConfig初期化: storage_type={self.storage_type}, debug_mode={self.debug_mode}"
        )

        # 設定を読み込み
        try:
            self.load_config()
            logger.info(
                f"設定読み込み成功: モード={self.get_behavior()}({self.get_mode_display_name()}), "
                f"チャンネル数={len(self.get_channels())}"
            )
        except Exception as e:
            logger.warning(
                f"チャンネル設定の読み込みに失敗しました。デフォルト設定を使用します: {str(e)}"
            )
            # 環境変数の値からデフォルト設定を作成
            self._initialize_from_env()
            # DENIED_CHANNEL_IDSが存在するかチェックしてログ出力
            denied_channels = getattr(config, "DENIED_CHANNEL_IDS", [])
            logger.info(
                f"環境変数から初期化: モード={self.get_behavior()}({self.get_mode_display_name()}), "
                f"チャンネル数={len(self.get_channels())}, "
                f"DENIED_CHANNEL_IDS={denied_channels}"
            )
            # 設定ファイルを作成
            try:
                self.save_config()
                logger.info("デフォルト設定ファイルを作成しました")
            except Exception as save_error:
                logger.error(
                    f"デフォルト設定ファイルの作成に失敗しました: {str(save_error)}"
                )

    def _initialize_from_env(self) -> None:
        """環境変数の設定値から初期設定を作成"""
        channels = []
        # DENIED_CHANNEL_IDSが存在するかチェックしてから使用
        denied_channel_ids = getattr(config, "DENIED_CHANNEL_IDS", [])
        for channel_id in denied_channel_ids:
            channels.append(
                {
                    "id": channel_id,
                    "name": f"チャンネルID: {channel_id}",  # 初期化時には名前不明
                }
            )

        self.config_data = {
            "behavior": "deny",  # 従来の動作は全体モード（denyモード）
            "channels": channels,
            "updated_at": datetime.now().isoformat(),
        }

    def load_config(self) -> None:
        """設定ファイルを読み込む"""
        if self.debug_mode:
            return

        if self.storage_type == "s3":
            self._load_from_s3()
        else:
            self._load_from_local()

    def _load_from_local(self) -> None:
        """ローカルファイルから設定を読み込む"""
        file_path = config.CHANNEL_CONFIG_PATH
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                self.config_data = json.load(f)
        else:
            raise FileNotFoundError(
                f"チャンネル設定ファイルが見つかりません: {file_path}"
            )

    def _load_from_s3(self) -> None:
        """S3から設定ファイルを読み込む"""
        file_key = self._get_s3_file_key()

        try:
            import boto3

            from config import S3_BUCKET_NAME

            # 直接S3Helperを使うのではなく、S3Helperの実装内容と同じようにboto3を使う
            s3_client = boto3.client("s3")
            response = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=file_key)
            content = response["Body"].read().decode("utf-8")
            if content is None:
                raise Exception("S3からファイル内容を取得できませんでした")
            self.config_data = json.loads(content)
        except Exception as e:
            raise Exception(f"S3からの設定ファイル読み込みに失敗: {str(e)}")

    def _get_s3_file_key(self) -> str:
        """S3のファイルキーを取得"""
        base_path = config.S3_FOLDER_PATH + "/" if config.S3_FOLDER_PATH else ""
        return f"{base_path}{os.path.basename(config.CHANNEL_CONFIG_PATH)}"

    def save_config(self) -> bool:
        """
        設定をファイルに保存する

        Returns:
            bool: 保存が成功したかどうか
        """
        if self.debug_mode:
            return True

        # 更新日時を記録
        self.config_data["updated_at"] = datetime.now().isoformat()

        try:
            if self.storage_type == "s3":
                return self._save_to_s3()
            else:
                return self._save_to_local()
        except Exception as e:
            logger.error(f"チャンネル設定の保存に失敗しました: {str(e)}")
            return False

    def _save_to_local(self) -> bool:
        """ローカルファイルに設定を保存"""
        file_path = config.CHANNEL_CONFIG_PATH
        try:
            # ディレクトリが存在しない場合は作成
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(self.config_data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"ローカルファイルへの保存に失敗: {str(e)}")
            return False

    def _save_to_s3(self) -> bool:
        """S3に設定を保存"""
        try:
            import boto3

            from config import S3_BUCKET_NAME

            s3_client = boto3.client("s3")
            file_key = self._get_s3_file_key()
            content = json.dumps(self.config_data, ensure_ascii=False, indent=2).encode(
                "utf-8"
            )

            s3_client.put_object(Body=content, Bucket=S3_BUCKET_NAME, Key=file_key)
            logger.info(
                f"S3へのファイル保存成功: バケット={S3_BUCKET_NAME}, キー={file_key}"
            )
            return True
        except Exception as e:
            logger.error(f"S3への保存に失敗: {str(e)}")
            return False

    def get_behavior(self) -> str:
        """
        現在の評価モードを取得

        Returns:
            str: "allow" (限定モード) または "deny" (全体モード)
        """
        return self.config_data.get("behavior", "deny")

    def set_behavior(self, behavior: str) -> bool:
        """
        評価モードを設定

        Args:
            behavior: "allow" (限定モード) または "deny" (全体モード)

        Returns:
            bool: 設定と保存が成功したかどうか
        """
        if behavior not in ["allow", "deny"]:
            logger.error(f"無効な評価モード: {behavior}")
            return False

        self.config_data["behavior"] = behavior
        return self.save_config()

    def get_channels(self) -> List[Dict[str, Any]]:
        """
        チャンネルリストを取得

        Returns:
            List[Dict[str, Any]]: チャンネルリスト [{"id": チャンネルID, "name": チャンネル名}, ...]
        """
        return self.config_data.get("channels", [])

    def is_channel_in_list(self, channel_id: int) -> bool:
        """
        指定のチャンネルIDがリストに含まれているかチェック

        Args:
            channel_id: チャンネルID

        Returns:
            bool: リストに含まれているかどうか
        """
        str_channel_id = str(channel_id)  # チャンネルIDを文字列に変換
        for channel in self.get_channels():
            # チャンネルIDを文字列として比較（保存されたIDが文字列の場合もある）
            if str(channel.get("id")) == str_channel_id:
                return True
        return False

    def can_bot_speak(self, channel_id: int) -> bool:
        """
        指定のチャンネルでボットが発言可能かどうかをチェック

        Args:
            channel_id: チャンネルID

        Returns:
            bool: ボットが発言可能かどうか
        """
        behavior = self.get_behavior()
        in_list = self.is_channel_in_list(channel_id)
        result = False

        # 詳細なログ記録
        logger.info(
            f"can_bot_speak: チャンネルID={channel_id}, "
            f"behavior={behavior}, in_list={in_list}, "
            f"チャンネル数={len(self.get_channels())}"
        )

        # リスト内のすべてのチャンネルIDをログ出力
        channels_str = ", ".join(
            [
                f"{str(c.get('id'))}({type(c.get('id')).__name__})"
                for c in self.get_channels()
            ]
        )
        logger.info(f"チャンネルリスト内のID: [{channels_str}]")

        # 限定モード: リストにあるチャンネルのみ許可
        if behavior == "allow":
            result = in_list
            logger.info(
                f"限定モード判定: {result} (リストに{'' if in_list else '不'}一致)"
            )
        # 全体モード: リストにないチャンネルのみ許可
        else:
            result = not in_list
            logger.info(
                f"全体モード判定: {result} (リストに{'' if in_list else '不'}一致)"
            )

        return result

    def add_channel(self, channel_id: int, channel_name: str) -> bool:
        """
        チャンネルをリストに追加

        Args:
            channel_id: チャンネルID
            channel_name: チャンネル名

        Returns:
            bool: 追加と保存が成功したかどうか
        """
        # 既に存在する場合は何もしない
        if self.is_channel_in_list(channel_id):
            return True

        channels = self.get_channels()
        channels.append({"id": channel_id, "name": channel_name})
        self.config_data["channels"] = channels

        return self.save_config()

    def remove_channel(self, channel_id: int) -> bool:
        """
        チャンネルをリストから削除

        Args:
            channel_id: チャンネルID

        Returns:
            bool: 削除と保存が成功したかどうか
        """
        channels = self.get_channels()
        str_channel_id = str(channel_id)  # チャンネルIDを文字列に変換

        # チャンネルIDを文字列として比較して削除
        self.config_data["channels"] = [
            channel for channel in channels if str(channel.get("id")) != str_channel_id
        ]

        return self.save_config()

    def clear_channels(self) -> bool:
        """
        チャンネルリストをクリア

        Returns:
            bool: クリアと保存が成功したかどうか
        """
        self.config_data["channels"] = []
        return self.save_config()

    def get_mode_display_name(self) -> str:
        """
        現在の評価モードの表示名を取得

        Returns:
            str: 「限定モード」または「全体モード」
        """
        behavior = self.get_behavior()
        if behavior == "allow":
            return "限定モード"
        else:
            return "全体モード"

    def get_list_display_name(self) -> str:
        """
        現在のチャンネルリストの表示名を取得

        Returns:
            str: 「許可チャンネルリスト」または「拒否チャンネルリスト」
        """
        behavior = self.get_behavior()
        if behavior == "allow":
            return "許可チャンネルリスト"
        else:
            return "拒否チャンネルリスト"
