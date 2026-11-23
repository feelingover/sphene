import config
from bot.discord_bot import SpheneBot
from log_utils.logger import logger


def _warn_deprecated_env_vars() -> None:
    """廃止済みの環境変数が設定されていれば警告する（値は無視される）"""
    for name, hint in config.find_deprecated_env_vars():
        logger.warning(f"廃止済みの環境変数 {name} が設定されています（無視されます）: {hint}")


def main() -> None:
    """アプリケーションのエントリーポイント"""
    _warn_deprecated_env_vars()
    bot = SpheneBot()
    bot.run()


# メイン処理
if __name__ == "__main__":
    main()
