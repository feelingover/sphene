#!/usr/bin/env python3
"""Firestoreコレクションのネームスペース移行スクリプト

旧コレクション（プレフィックスなし等）から新しいネームスペース付きコレクションへ
ドキュメントをコピーする。

使用例:
    # デフォルトの旧コレクション名から移行（dry-run）
    uv run python scripts/migrate_firestore_namespace.py --namespace prod --dry-run

    # 旧環境変数でカスタム名を使ってた場合
    uv run python scripts/migrate_firestore_namespace.py --namespace prod \
      --src-channel-configs my_custom_channels \
      --src-user-profiles my_custom_profiles \
      --execute

    # 既存ドキュメントを上書き
    uv run python scripts/migrate_firestore_namespace.py --namespace prod \
      --execute --force

必要な環境変数:
    GOOGLE_APPLICATION_CREDENTIALS: GCPサービスアカウントキーのパス（Workload Identity使用時は不要）
"""

import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)8s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

COLLECTION_MAPPINGS = [
    ("channel_configs", "src_channel_configs"),
    ("user_profiles", "src_user_profiles"),
    ("channel_contexts", "src_channel_contexts"),
]


def migrate_collection(
    db: "google.cloud.firestore.Client",  # type: ignore[name-defined]  # noqa: F821
    src_name: str,
    dst_name: str,
    dry_run: bool,
    force: bool,
) -> dict[str, int]:
    """単一コレクションを移行する

    Args:
        db: Firestoreクライアント
        src_name: 移行元コレクション名
        dst_name: 移行先コレクション名
        dry_run: Trueの場合は実際に書き込まない
        force: Trueの場合は既存ドキュメントを上書き

    Returns:
        dict: {"copied": int, "skipped": int, "errors": int}
    """
    stats = {"copied": 0, "skipped": 0, "errors": 0}

    try:
        src_docs = list(db.collection(src_name).stream())
    except Exception as e:
        logger.error(f"  コレクション '{src_name}' の読み取りに失敗: {e}", exc_info=True)
        stats["errors"] += 1
        return stats

    if not src_docs:
        logger.info(f"  コレクション '{src_name}' にドキュメントなし、スキップ")
        return stats

    logger.info(f"  {src_name} → {dst_name}: {len(src_docs)}件のドキュメント")

    for doc in src_docs:
        doc_id = doc.id
        data = doc.to_dict()

        if dry_run:
            logger.info(f"    [dry-run] {dst_name}/{doc_id}")
            stats["copied"] += 1
            continue

        try:
            dst_ref = db.collection(dst_name).document(doc_id)
            if not force:
                existing = dst_ref.get()
                if existing.exists:
                    logger.info(f"    スキップ（既存）: {dst_name}/{doc_id}")
                    stats["skipped"] += 1
                    continue

            dst_ref.set(data)
            logger.info(f"    コピー完了: {dst_name}/{doc_id}")
            stats["copied"] += 1
        except Exception as e:
            logger.error(
                f"    書き込み失敗: {dst_name}/{doc_id} - {e}", exc_info=True
            )
            stats["errors"] += 1

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Firestoreコレクションのネームスペース移行"
    )
    parser.add_argument(
        "--namespace",
        required=True,
        help="移行先のネームスペース（例: prod, dev）",
    )
    parser.add_argument(
        "--src-channel-configs",
        default="channel_configs",
        help="移行元のchannel_configsコレクション名（デフォルト: channel_configs）",
    )
    parser.add_argument(
        "--src-user-profiles",
        default="user_profiles",
        help="移行元のuser_profilesコレクション名（デフォルト: user_profiles）",
    )
    parser.add_argument(
        "--src-channel-contexts",
        default="channel_contexts",
        help="移行元のchannel_contextsコレクション名（デフォルト: channel_contexts）",
    )

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        help="プレビューモード（実際に書き込まない）",
    )
    mode_group.add_argument(
        "--execute",
        action="store_true",
        help="実際にコピーを実行する",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="既存ドキュメントを上書き（デフォルト: スキップ）",
    )
    args = parser.parse_args()

    namespace = args.namespace
    dry_run = args.dry_run

    src_names = {
        "channel_configs": args.src_channel_configs,
        "user_profiles": args.src_user_profiles,
        "channel_contexts": args.src_channel_contexts,
    }

    logger.info("=== Firestore ネームスペース移行 ===")
    logger.info(f"ネームスペース: {namespace}")
    logger.info(f"モード: {'dry-run' if dry_run else 'execute'}")
    if args.force:
        logger.info("上書きモード: 有効")

    try:
        from google.cloud.firestore import Client as FirestoreClient

        db = FirestoreClient()
    except Exception as e:
        logger.error(f"Firestoreクライアントの初期化に失敗: {e}", exc_info=True)
        sys.exit(1)

    total_stats = {"copied": 0, "skipped": 0, "errors": 0}

    for base_name, _ in COLLECTION_MAPPINGS:
        src_name = src_names[base_name]
        dst_name = f"{namespace}_{base_name}"

        logger.info(f"\n--- {base_name} ---")
        stats = migrate_collection(db, src_name, dst_name, dry_run, args.force)

        for key in total_stats:
            total_stats[key] += stats[key]

    logger.info("\n=== 移行サマリー ===")
    logger.info(f"コピー: {total_stats['copied']}件")
    logger.info(f"スキップ: {total_stats['skipped']}件")
    logger.info(f"エラー: {total_stats['errors']}件")

    if total_stats["errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
