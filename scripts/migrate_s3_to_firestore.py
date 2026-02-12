#!/usr/bin/env python3
"""S3からFirestoreへのチャンネル設定マイグレーションスクリプト

boto3はアプリ本体から削除済みのため、以下のように実行する:
    uv run --with boto3 python scripts/migrate_s3_to_firestore.py

ドライランモード（実際に書き込まない）:
    uv run --with boto3 python scripts/migrate_s3_to_firestore.py --dry-run

必要な環境変数:
    S3_BUCKET_NAME: S3バケット名
    S3_FOLDER_PATH: S3フォルダパス（オプション）
    FIRESTORE_COLLECTION_NAME: Firestoreコレクション名（デフォルト: channel_configs）
    GOOGLE_APPLICATION_CREDENTIALS: GCPサービスアカウントキーのパス（Workload Identity使用時は不要）
"""

import argparse
import json
import logging
import os
import re
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)8s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def get_s3_channel_configs(
    bucket_name: str, folder_path: str | None
) -> dict[str, dict]:
    """S3から全ギルドのチャンネル設定を取得する

    Args:
        bucket_name: S3バケット名
        folder_path: S3フォルダパス（オプション）

    Returns:
        dict[str, dict]: {guild_id: config_data} のマッピング
    """
    import boto3

    s3_client = boto3.client("s3")
    prefix = f"{folder_path.rstrip('/')}/" if folder_path else ""
    pattern = re.compile(r"channel_list\.([a-zA-Z0-9_\-]+)\.json$")

    configs: dict[str, dict] = {}

    logger.info(f"S3バケットをスキャン: bucket={bucket_name}, prefix={prefix}")

    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            filename = key.split("/")[-1]
            match = pattern.match(filename)
            if not match:
                continue

            guild_id = match.group(1)
            try:
                response = s3_client.get_object(Bucket=bucket_name, Key=key)
                content = response["Body"].read().decode("utf-8")
                config_data = json.loads(content)
                configs[guild_id] = config_data
                logger.info(f"  取得成功: {key} (guild_id={guild_id})")
            except Exception as e:
                logger.error(f"  取得失敗: {key} - {e}", exc_info=True)

    logger.info(f"S3から {len(configs)} 件のチャンネル設定を取得")
    return configs


def write_to_firestore(
    configs: dict[str, dict], collection_name: str, dry_run: bool = False
) -> None:
    """Firestoreにチャンネル設定を書き込む

    Args:
        configs: {guild_id: config_data} のマッピング
        collection_name: Firestoreコレクション名
        dry_run: Trueの場合は実際に書き込まず内容を表示
    """
    if dry_run:
        logger.info("[ドライラン] Firestoreへの書き込みをシミュレート")
        for guild_id, data in configs.items():
            logger.info(
                f"  [ドライラン] {collection_name}/{guild_id}: "
                f"behavior={data.get('behavior')}, "
                f"channels={len(data.get('channels', []))}件"
            )
        return

    from google.cloud.firestore import Client as FirestoreClient

    db = FirestoreClient()
    success_count = 0
    error_count = 0

    for guild_id, data in configs.items():
        try:
            db.collection(collection_name).document(guild_id).set(data)
            logger.info(f"  書き込み成功: {collection_name}/{guild_id}")
            success_count += 1
        except Exception as e:
            logger.error(
                f"  書き込み失敗: {collection_name}/{guild_id} - {e}",
                exc_info=True,
            )
            error_count += 1

    logger.info(
        f"Firestore書き込み完了: 成功={success_count}, 失敗={error_count}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="S3からFirestoreへチャンネル設定をマイグレーション"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実際に書き込まず内容を表示する",
    )
    args = parser.parse_args()

    bucket_name = os.getenv("S3_BUCKET_NAME")
    if not bucket_name:
        logger.error("環境変数 S3_BUCKET_NAME が設定されていません")
        sys.exit(1)

    folder_path = os.getenv("S3_FOLDER_PATH")
    collection_name = os.getenv("FIRESTORE_COLLECTION_NAME", "channel_configs")

    logger.info("=== S3 → Firestore マイグレーション開始 ===")
    logger.info(f"S3: bucket={bucket_name}, folder={folder_path}")
    logger.info(f"Firestore: collection={collection_name}")
    if args.dry_run:
        logger.info("モード: ドライラン（書き込みなし）")

    # S3から設定を取得
    configs = get_s3_channel_configs(bucket_name, folder_path)
    if not configs:
        logger.info("マイグレーション対象の設定が見つかりませんでした")
        return

    # Firestoreに書き込み
    write_to_firestore(configs, collection_name, dry_run=args.dry_run)

    logger.info("=== マイグレーション完了 ===")


if __name__ == "__main__":
    main()
