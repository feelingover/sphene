import discord
from discord import app_commands

import config
from ai.conversation import (
    Sphene,
    load_system_prompt,
    reload_system_prompt,
    user_conversations,
)
from log_utils.logger import logger


async def cmd_list_channels(
    bot: discord.Client, interaction: discord.Interaction
) -> None:
    """チャンネル一覧コマンドを処理する

    Args:
        bot: Discordクライアント
        interaction: インタラクションオブジェクト
    """
    channel_info = f"🚫 **{config.BOT_NAME}使用禁止チャンネル一覧**:\n"

    # 禁止チャンネルリストの作成
    for channel_id in config.DENIED_CHANNEL_IDS:
        channel = bot.get_channel(channel_id)
        # チャンネルが存在し、名前属性があるかチェック
        if channel and hasattr(channel, "name"):
            channel_name = getattr(channel, "name")
        else:
            channel_name = f"不明なチャンネル (ID: {channel_id})"
        channel_info += f"• {channel_name} (ID: {channel_id})\n"

    # 禁止チャンネルがない場合の表示 (つまり制限なし)
    if not config.DENIED_CHANNEL_IDS:
        channel_info += (
            "現在、全てのチャンネルで使用可能です（チャンネル制限なし）！🎉\n"
        )

    # 設定方法の説明を追加
    channel_info += "\n制限の設定方法: 環境変数`DENIED_CHANNEL_IDS`に使用を禁止するチャンネルIDをカンマ区切りで設定してね！"

    # メッセージ送信
    await interaction.response.send_message(channel_info)


async def cmd_reset_conversation(interaction: discord.Interaction) -> None:
    """会話履歴リセットコマンドを処理する

    Args:
        interaction: インタラクションオブジェクト
    """
    user_id = str(interaction.user.id)

    if user_id in user_conversations:
        user_conversations[user_id] = Sphene(system_setting=load_system_prompt())
        await interaction.response.send_message(
            "🔄 会話履歴をリセットしたよ！また一から話そうね！"
        )
        logger.info(f"ユーザーID {user_id} の会話履歴を手動リセット")
    else:
        await interaction.response.send_message(
            "🤔 まだ話したことがないみたいだね！これから仲良くしようね！"
        )


async def cmd_reload_prompt(interaction: discord.Interaction) -> None:
    """システムプロンプト再読み込みコマンドを処理する

    Args:
        interaction: インタラクションオブジェクト
    """
    # 応答を遅延送信（処理に時間がかかる可能性があるため）
    await interaction.response.defer(ephemeral=True)

    # 手動再読み込みではfail_on_error=Falseを指定（エラー時にボットを停止しない）
    success = reload_system_prompt(fail_on_error=False)

    if success:
        logger.info(
            f"システムプロンプト再読み込み成功（実行者: {interaction.user.name}）"
        )
        await interaction.followup.send(
            "✅ システムプロンプトを再読み込みしました！\n"
            f"ストレージタイプ: **{config.PROMPT_STORAGE_TYPE}**\n"
            f"プロンプトファイル: **{config.SYSTEM_PROMPT_FILENAME}**"
        )
    else:
        logger.error(
            f"システムプロンプト再読み込み失敗（実行者: {interaction.user.name}）"
        )
        await interaction.followup.send(
            "❌ システムプロンプトの再読み込みに失敗しました。ログを確認してください。"
        )


async def handle_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
) -> None:
    """スラッシュコマンドエラーハンドラ

    Args:
        interaction: インタラクションオブジェクト
        error: エラーオブジェクト
    """
    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message(
            "👮 このコマンドは管理者権限が必要だよ！", ephemeral=True
        )
        return

    logger.error(f"コマンドエラー発生: {str(error)}", exc_info=True)
    await interaction.response.send_message(
        f"😱 コマンド実行中にエラーが発生しちゃった: {str(error)}", ephemeral=True
    )


def setup_commands(bot: discord.Client) -> app_commands.Group:
    """スラッシュコマンドのセットアップ

    Args:
        bot: Discordクライアント

    Returns:
        app_commands.Group: コマンドグループ
    """
    # コマンドグループ
    command_group = app_commands.Group(
        name=config.COMMAND_GROUP_NAME,
        description=f"{config.BOT_NAME}ボットのコマンド",
    )

    # チャンネル一覧コマンド
    @command_group.command(
        name="channels",
        description=f"{config.BOT_NAME}の使用が禁止されているチャンネル一覧を表示します",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def list_channels(interaction: discord.Interaction) -> None:
        await cmd_list_channels(bot, interaction)

    # リセットコマンド
    @command_group.command(
        name="reset", description="あなたとの会話履歴をリセットします"
    )
    async def reset_conversation_command(interaction: discord.Interaction) -> None:
        await cmd_reset_conversation(interaction)

    # システムプロンプト再読み込みコマンド
    @command_group.command(
        name="reload_prompt", description="システムプロンプトを再読み込みします"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def reload_prompt_command(interaction: discord.Interaction) -> None:
        await cmd_reload_prompt(interaction)

    return command_group
