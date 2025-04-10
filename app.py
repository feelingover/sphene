from bot.discord_bot import SpheneBot


def main() -> None:
    """アプリケーションのエントリーポイント"""
    bot = SpheneBot()
    bot.run()


# メイン処理
if __name__ == "__main__":
    main()
