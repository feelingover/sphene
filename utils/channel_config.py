"""
チャンネル設定（チャンネルリスト・評価モード）を管理するモジュール
ギルド毎に独立した設定ファイルを管理する
"""

import json
import os
from datetime import datetime
from typing import Any, Optional

import config
from log_utils.logger import logger
from utils.aws_clients import get_s3_client

# シングルトンインスタンスを格納する変数
_channel_config_manager_instance = None


class ChannelConfigManager:
    """
    ギルド毎のチャンネル設定を管理するクラス
    シングルトンパターンで実装
    """

    @staticmethod
    def get_instance(debug_mode: bool = False) -> "ChannelConfigManager":
        """
        シングルトンインスタンスを取得する

        Args:
            debug_mode: テスト時などにTrue、実際のファイル/S3操作をスキップ

        Returns:
            ChannelConfigManager: シングルトンインスタンス
        """
        global _channel_config_manager_instance

        # テスト時はdebug_mode=Trueでそれぞれ独立したインスタンスを生成する
        if debug_mode:
            logger.debug("ChannelConfigManager: テスト用の独立インスタンスを生成")
            return ChannelConfigManager(debug_mode=True)

        # 通常はシングルトンインスタンスを返す
        if _channel_config_manager_instance is None:
            logger.info("ChannelConfigManager: シングルトンインスタンスを初期化")
            _channel_config_manager_instance = ChannelConfigManager()

        return _channel_config_manager_instance

    def __init__(self, debug_mode: bool = False):
        """初期化"""
        self.debug_mode = debug_mode
        self.guild_configs: dict[str, "ChannelConfig"] = {}  # {guild_id: ChannelConfig}

    def get_config(self, guild_id: Any) -> "ChannelConfig":
        """
        指定ギルドの設定を取得（なければ作成）

        Args:
            guild_id: ギルドID（文字列または整数）

        Returns:
            ChannelConfig: ギルドの設定インスタンス
        """
        guild_id = str(guild_id)  # 文字列に変換

        if guild_id not in self.guild_configs:
            logger.info(f"ギルドID {guild_id} の設定を新規作成")
            self.guild_configs[guild_id] = ChannelConfig(
                guild_id=guild_id, debug_mode=self.debug_mode
            )

        return self.guild_configs[guild_id]

    def create_guild_config(self, guild_id: Any) -> "ChannelConfig":
        """
        新ギルドの設定を作成

        Args:
            guild_id: ギルドID（文字列または整数）

        Returns:
            ChannelConfig: 作成した設定インスタンス
        """
        guild_id = str(guild_id)
        config = ChannelConfig(guild_id=guild_id, debug_mode=self.debug_mode)
        config.save_config()
        self.guild_configs[guild_id] = config
        logger.info(f"ギルドID {guild_id} の設定ファイルを作成")
        return config

    def delete_guild_config(self, guild_id: Any) -> bool:
        """
        ギルドの設定を削除

        Args:
            guild_id: ギルドID（文字列または整数）

        Returns:
            bool: 削除が成功したかどうか
        """
        guild_id = str(guild_id)
        success = True

        # メモリから削除
        if guild_id in self.guild_configs:
            logger.info(f"ギルドID {guild_id} の設定をメモリから削除")
            del self.guild_configs[guild_id]

        # ファイルから削除
        if not self.debug_mode:
            storage_type = config.CHANNEL_CONFIG_STORAGE_TYPE
            if storage_type == "s3":
                success = self._delete_s3_file(guild_id)
            else:
                success = self._delete_local_file(guild_id)

        return success

    def _delete_local_file(self, guild_id: str) -> bool:
        """
        ローカルの設定ファイルを削除

        Args:
            guild_id: ギルドID

        Returns:
            bool: 削除が成功したかどうか
        """
        import os

        file_path = f"storage/channel_list.{guild_id}.json"

        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"ギルド設定ファイル削除: {file_path}")
                return True
            return True  # ファイルが存在しなくても成功とみなす
        except Exception as e:
            logger.error(f"ギルド設定ファイル削除エラー: {str(e)}")
            return False

    def _delete_s3_file(self, guild_id: str) -> bool:
        """
        S3の設定ファイルを削除

        Args:
            guild_id: ギルドID

        Returns:
            bool: 削除が成功したかどうか
        """
        try:
            from config import S3_BUCKET_NAME

            # S3クライアント
            s3_client = get_s3_client()

            # ファイルキー
            base_path = config.S3_FOLDER_PATH + "/" if config.S3_FOLDER_PATH else ""
            file_key = f"{base_path}channel_list.{guild_id}.json"

            # ファイル削除
            s3_client.delete_object(Bucket=S3_BUCKET_NAME, Key=file_key)
            logger.info(f"S3ギルド設定ファイル削除: {file_key}")
            return True
        except Exception as e:
            logger.error(f"S3ギルド設定ファイル削除エラー: {str(e)}")
            return False


class ChannelConfig:
    """
    特定ギルドのチャンネルリストと評価モードの設定を管理するクラス
    設定をJSONファイルとして保存・読み込みできる
    """

    def __init__(
        self,
        guild_id: Any,
        storage_type: Optional[str] = None,
        debug_mode: bool = False,
    ):
        """
        初期化

        Args:
            guild_id: ギルドID
            storage_type: 'local' or 's3' or None (Noneの場合はconfig設定を使用)
            debug_mode: テスト時などにTrue、実際のファイル/S3操作をスキップ
        """
        self.guild_id = str(guild_id)  # 文字列に変換して保存
        self.debug_mode = debug_mode
        self.storage_type = storage_type or config.CHANNEL_CONFIG_STORAGE_TYPE
        self.config_data: dict[str, Any] = {
            "behavior": "deny",  # デフォルトは全体モード
            "channels": [],
            "updated_at": datetime.now().isoformat(),
        }

        # 初期化時のデバッグ情報
        logger.info(
            f"ChannelConfig初期化: ギルドID={self.guild_id}, "
            f"storage_type={self.storage_type}, debug_mode={self.debug_mode}"
        )

        # 設定を読み込み
        try:
            self.load_config()
            logger.info(
                f"ギルドID {self.guild_id} の設定読み込み成功: "
                f"モード={self.get_behavior()}({self.get_mode_display_name()}), "
                f"チャンネル数={len(self.get_channels())}"
            )
        except Exception as e:
            logger.warning(
                f"ギルドID {self.guild_id} の設定読み込みに失敗しました。"
                f"デフォルト設定を使用します: {str(e)}"
            )
            # 初期設定のままとする（すでに初期化済み）

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
        file_path = self._get_config_file_path()
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
            from config import S3_BUCKET_NAME

            # S3クライアント
            s3_client = get_s3_client()
            response = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=file_key)
            content = response["Body"].read().decode("utf-8")
            if content is None:
                raise Exception("S3からファイル内容を取得できませんでした")
            self.config_data = json.loads(content)
        except Exception as e:
            raise Exception(f"S3からの設定ファイル読み込みに失敗: {str(e)}")

    def _get_config_file_path(self) -> str:
        """設定ファイルのパスを取得"""
        return f"storage/channel_list.{self.guild_id}.json"

    def _get_s3_file_key(self) -> str:
        """S3のファイルキーを取得"""
        base_path = config.S3_FOLDER_PATH + "/" if config.S3_FOLDER_PATH else ""
        return f"{base_path}channel_list.{self.guild_id}.json"

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
        file_path = self._get_config_file_path()
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
            from config import S3_BUCKET_NAME

            s3_client = get_s3_client()
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

    def get_channels(self) -> list[dict[str, Any]]:
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
            f"can_bot_speak: ギルドID={self.guild_id}, チャンネルID={channel_id}, "
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
