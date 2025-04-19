from typing import Optional

import boto3
from botocore.exceptions import ClientError

from log_utils.logger import logger


class S3Helper:
    """S3からファイルを読み込むためのヘルパークラス"""

    @staticmethod
    def read_file_from_s3(
        bucket_name: str, file_key: str, folder_path: Optional[str] = None
    ) -> Optional[str]:
        """S3バケットからファイルを読み込む

        Args:
            bucket_name: S3バケット名
            file_key: 読み込むファイル名
            folder_path: フォルダパス（オプション）

        Returns:
            Optional[str]: ファイルの内容、エラー時はNone
        """
        try:
            s3_client = boto3.client("s3")

            # フォルダパスがある場合は結合
            full_key = (
                f"{folder_path.rstrip('/')}/{file_key}" if folder_path else file_key
            )

            logger.info(
                f"S3からファイルを読み込み: バケット={bucket_name}, キー={full_key}"
            )

            response = s3_client.get_object(Bucket=bucket_name, Key=full_key)
            file_content = response["Body"].read().decode("utf-8")
            content_length = len(file_content)

            # 成功ログを出力
            logger.info(
                f"S3ファイル読み込み成功: バケット={bucket_name}, キー={full_key}, サイズ={content_length}バイト"
            )

            return file_content.strip()

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            if error_code == "NoSuchKey":
                logger.error(f"S3ファイルが見つかりません: {full_key}")
            elif error_code == "NoSuchBucket":
                logger.error(f"S3バケットが見つかりません: {bucket_name}")
            else:
                logger.error(
                    f"S3ファイル読み込み中にエラー発生: {str(e)}", exc_info=True
                )
            return None

        except Exception as e:
            logger.error(f"S3アクセス中に予期せぬエラーが発生: {str(e)}", exc_info=True)
            return None
