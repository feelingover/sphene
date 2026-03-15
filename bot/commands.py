import discord
from discord import app_commands, ui

import config
from ai.conversation import channel_conversations
from log_utils.logger import logger
from utils.channel_config import ChannelConfigManager

# チャンネル設定マネージャーのシングルトンインスタンスを取得
config_manager = ChannelConfigManager.get_instance()


class ModeSelect(ui.Select):
    """評価モード選択ドロップダウン"""

    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        options = [
            discord.SelectOption(
                label="限定モード",
                description="ボットの発言はリストに含まれるチャンネルのみ許可",
                value="allow",
            ),
            discord.SelectOption(
                label="全体モード",
                description="ボットの発言はリストに含まれるチャンネル以外で許可",
                value="deny",
            ),
        ]
        super().__init__(
            placeholder="モードを選択してください",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """モード選択時の処理"""
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("👮 このコマンドは管理者権限が必要だよ！", ephemeral=True)
            return
        # 保存済みのguild_idを使用
        channel_config = config_manager.get_config(self.guild_id)

        selected_mode = self.values[0]
        success = channel_config.set_behavior(selected_mode)

        if success:
            # 設定保存後にリストを再読み込み
            channel_config.load_config()
            mode_name = "限定モード" if selected_mode == "allow" else "全体モード"
            await interaction.response.send_message(
                f"✅ 評価モードを「{mode_name}」に変更しました！\n"
                f"現在のリストは「{channel_config.get_list_display_name()}」として扱われます"
            )
        else:
            await interaction.response.send_message("❌ 評価モードの変更に失敗しました")


class TranslationSelect(ui.Select):
    """翻訳機能の有効/無効選択ドロップダウン"""

    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        options = [
            discord.SelectOption(
                label="有効",
                description="国旗リアクションによる翻訳機能を有効にする",
                value="true",
            ),
            discord.SelectOption(
                label="無効",
                description="国旗リアクションによる翻訳機能を無効にする",
                value="false",
            ),
        ]
        super().__init__(
            placeholder="翻訳機能の状態を選択してください",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """翻訳設定選択時の処理"""
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("👮 このコマンドは管理者権限が必要だよ！", ephemeral=True)
            return
        # 保存済みのguild_idを使用
        channel_config = config_manager.get_config(self.guild_id)

        selected_value = (
            self.values[0] == "true"
        )  # "true" または "false" を boolean に変換
        success = channel_config.set_translation_enabled(selected_value)

        if success:
            # 設定保存後にリストを再読み込み
            channel_config.load_config()
            status = "有効" if selected_value else "無効"
            await interaction.response.send_message(
                f"✅ 翻訳機能を「{status}」に設定しました！"
            )
        else:
            await interaction.response.send_message(
                "❌ 翻訳機能の設定変更に失敗しました"
            )


class ModeView(ui.View):
    """評価モード選択ビュー"""

    def __init__(self, guild_id: int) -> None:
        super().__init__(timeout=60)  # 60秒でタイムアウト
        self.add_item(ModeSelect(guild_id))


class TranslationView(ui.View):
    """翻訳機能設定ビュー"""

    def __init__(self, guild_id: int) -> None:
        super().__init__(timeout=60)  # 60秒でタイムアウト
        self.add_item(TranslationSelect(guild_id))


class ClearConfirmView(ui.View):
    """チャンネルリストクリア確認ビュー"""

    def __init__(self, guild_id: int) -> None:
        super().__init__(timeout=60)  # 60秒でタイムアウト
        self.guild_id = guild_id

    @discord.ui.button(label="はい", style=discord.ButtonStyle.danger)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """確認ボタンのコールバック"""
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("👮 このコマンドは管理者権限が必要だよ！", ephemeral=True)
            return
        # 保存済みのguild_idを使用
        channel_config = config_manager.get_config(self.guild_id)

        success = channel_config.clear_channels()

        if success:
            # 設定保存後にリストを再読み込み
            channel_config.load_config()
            await interaction.response.send_message(
                f"✅ {channel_config.get_list_display_name()}をクリアしました！"
            )
        else:
            await interaction.response.send_message("❌ リストのクリアに失敗しました")

    @discord.ui.button(label="いいえ", style=discord.ButtonStyle.secondary)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """キャンセルボタンのコールバック"""
        await interaction.response.send_message("✅ キャンセルしました")


async def cmd_mode(interaction: discord.Interaction) -> None:
    """評価モード切替コマンドを処理する

    Args:
        interaction: インタラクションオブジェクト
    """
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ このコマンドはサーバー内でのみ使用できます"
        )
        return

    # ギルド固有の設定を取得
    guild_id = interaction.guild.id
    channel_config = config_manager.get_config(guild_id)

    # 現在のモード情報表示
    current_mode = channel_config.get_mode_display_name()
    list_type = channel_config.get_list_display_name()

    await interaction.response.send_message(
        f"🔄 **現在の評価モード**: {current_mode}\n"
        f"📋 **現在のリスト**: {list_type}\n\n"
        "👇 変更する場合は、下のメニューから選択してください",
        view=ModeView(guild_id),
    )


def _build_channel_list_header(behavior: str, mode_name: str, list_name: str) -> str:
    """チャンネルリスト表示のヘッダーを作成する

    Args:
        behavior: 評価モード ("allow" または "deny")
        mode_name: 表示用モード名
        list_name: 表示用リスト名

    Returns:
        str: 作成されたヘッダー文字列
    """
    emoji = "✅" if behavior == "allow" else "🚫"
    return (
        f"{emoji} **{config.BOT_NAME} {list_name}**\n"
        f"現在の評価モード: **{mode_name}**\n\n"
    )


def _format_channel_info(channel_data: dict, bot: discord.Client) -> str:
    """チャンネル情報を整形する

    Args:
        channel_data: チャンネルのデータ辞書
        bot: Discordクライアント

    Returns:
        str: フォーマットされたチャンネル情報
    """
    channel_id = channel_data.get("id")
    channel_name = channel_data.get("name", f"不明なチャンネル (ID: {channel_id})")

    # チャンネルが存在するか確認して名前を更新
    if channel_id is not None:
        try:
            channel_id_int = int(channel_id)
            channel = bot.get_channel(channel_id_int)
            if channel is not None and hasattr(channel, "name"):
                channel_name = str(getattr(channel, "name"))
        except (ValueError, TypeError):
            pass  # channel_idをint型に変換できない場合は何もしない

    return f"• {channel_name} (ID: {channel_id})\n"


async def cmd_list_channels(
    bot: discord.Client, interaction: discord.Interaction, page: int = 1
) -> None:
    """チャンネル一覧コマンドを処理する

    Args:
        bot: Discordクライアント
        interaction: インタラクションオブジェクト
        page: 表示するページ番号（1始まり）
    """
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ このコマンドはサーバー内でのみ使用できます"
        )
        return

    # ギルド固有の設定を取得
    guild_id = interaction.guild.id
    channel_config = config_manager.get_config(guild_id)

    # 現在のモードを取得
    behavior = channel_config.get_behavior()
    mode_name = channel_config.get_mode_display_name()
    list_name = channel_config.get_list_display_name()

    # チャンネルリストを取得とページング
    channels = channel_config.get_channels()
    per_page = 10  # 1ページあたりの表示数
    total_pages = (len(channels) + per_page - 1) // per_page if channels else 1

    # ページ番号の調整
    page = max(1, min(page, total_pages))

    # 表示するチャンネルのスライス
    start_idx = (page - 1) * per_page
    end_idx = min(start_idx + per_page, len(channels))
    display_channels = channels[start_idx:end_idx]

    # ヘッダー構築
    channel_info = _build_channel_list_header(behavior, mode_name, list_name)

    # チャンネル情報を追加
    if display_channels:
        for channel_data in display_channels:
            channel_info += _format_channel_info(channel_data, bot)
    else:
        if behavior == "allow":
            channel_info += (
                "現在、リストは空です（どのチャンネルでも発言できません）！\n"
            )
        else:
            channel_info += (
                "現在、リストは空です（全てのチャンネルで発言可能です）！🎉\n"
            )

    # ページ情報
    if total_pages > 1:
        channel_info += f"\nページ: {page}/{total_pages}"

    # メッセージ送信
    await interaction.response.send_message(channel_info)


async def cmd_add_channel(interaction: discord.Interaction) -> None:
    """現在のチャンネルをリストに追加するコマンドを処理する

    Args:
        interaction: インタラクションオブジェクト
    """
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ このコマンドはサーバー内でのみ使用できます"
        )
        return

    # ギルド固有の設定を取得
    guild_id = interaction.guild.id
    channel_config = config_manager.get_config(guild_id)

    channel = interaction.channel
    if channel is None:
        await interaction.response.send_message(
            "❌ チャンネル情報を取得できませんでした"
        )
        return

    channel_id = channel.id
    channel_name = ""
    if hasattr(channel, "name"):
        channel_name = str(channel.name)
    else:
        channel_name = f"チャンネルID: {channel_id}"

    # 確実に文字列型にする
    safe_channel_name = (
        str(channel_name) if channel_name else f"チャンネルID: {channel_id}"
    )

    # リストに追加
    success = channel_config.add_channel(channel_id, safe_channel_name)
    list_name = channel_config.get_list_display_name()

    if success:
        # 設定保存後にリストを再読み込み
        channel_config.load_config()
        await interaction.response.send_message(
            f"✅ チャンネル「{channel_name}」を{list_name}に追加しました！"
        )
    else:
        await interaction.response.send_message("❌ チャンネルの追加に失敗しました")


async def cmd_remove_channel(interaction: discord.Interaction) -> None:
    """現在のチャンネルをリストから削除するコマンドを処理する

    Args:
        interaction: インタラクションオブジェクト
    """
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ このコマンドはサーバー内でのみ使用できます"
        )
        return

    # ギルド固有の設定を取得
    guild_id = interaction.guild.id
    channel_config = config_manager.get_config(guild_id)

    channel = interaction.channel
    if channel is None:
        await interaction.response.send_message(
            "❌ チャンネル情報を取得できませんでした"
        )
        return

    channel_id = channel.id
    channel_name = ""
    if hasattr(channel, "name"):
        channel_name = str(channel.name)
    else:
        channel_name = f"チャンネルID: {channel_id}"

    # リストから削除
    success = channel_config.remove_channel(channel_id)
    list_name = channel_config.get_list_display_name()

    if success:
        # 設定保存後にリストを再読み込み
        channel_config.load_config()
        # チャンネルがリストにまだ存在するかチェック
        if channel_config.is_channel_in_list(channel_id):
            # 削除に失敗している場合（まだリストに存在する）
            await interaction.response.send_message(
                f"❌ チャンネル「{channel_name}」の削除に失敗しました（まだ{list_name}に含まれています）"
            )
        else:
            # 削除成功（もうリストに存在しない）
            await interaction.response.send_message(
                f"✅ チャンネル「{channel_name}」を{list_name}から削除しました！"
            )
    else:
        await interaction.response.send_message("❌ チャンネルの削除に失敗しました")


async def cmd_clear_channels(interaction: discord.Interaction) -> None:
    """チャンネルリストをクリアするコマンドを処理する

    Args:
        interaction: インタラクションオブジェクト
    """
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ このコマンドはサーバー内でのみ使用できます"
        )
        return

    # ギルド固有の設定を取得
    guild_id = interaction.guild.id
    channel_config = config_manager.get_config(guild_id)

    list_name = channel_config.get_list_display_name()

    await interaction.response.send_message(
        f"❓ {list_name}をクリアしますか？\n" f"この操作は元に戻せません。",
        view=ClearConfirmView(guild_id),
    )



async def cmd_translation(interaction: discord.Interaction) -> None:
    """翻訳機能の有効/無効切替コマンドを処理する

    Args:
        interaction: インタラクションオブジェクト
    """
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ このコマンドはサーバー内でのみ使用できます"
        )
        return

    # ギルド固有の設定を取得
    guild_id = interaction.guild.id
    channel_config = config_manager.get_config(guild_id)

    # 現在の翻訳機能状態を取得
    is_enabled = channel_config.get_translation_enabled()
    status = "有効" if is_enabled else "無効"

    # 翻訳機能の説明メッセージ
    help_text = (
        "🇺🇸 アメリカ国旗リアクションで英語翻訳\n"
        "🇯🇵 日本国旗リアクションで日本語翻訳\n"
    )

    await interaction.response.send_message(
        f"🌐 **翻訳機能**: 現在「{status}」です\n\n"
        f"{help_text}\n"
        "👇 設定を変更する場合は、下のメニューから選択してください",
        view=TranslationView(guild_id),
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

    # 評価モード切替コマンド
    @command_group.command(
        name="mode",
        description=f"{config.BOT_NAME}の評価モード（限定/全体）を切り替えます",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def mode_command(interaction: discord.Interaction) -> None:
        await cmd_mode(interaction)

    # チャンネル一覧コマンド
    @command_group.command(
        name="channels",
        description=f"{config.BOT_NAME}のチャンネルリスト・評価モードを表示します",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def list_channels_command(
        interaction: discord.Interaction, page: int = 1
    ) -> None:
        await cmd_list_channels(bot, interaction, page)

    # チャンネル追加コマンド
    @command_group.command(
        name="addlist",
        description="現在のチャンネルをリストに追加します",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def add_channel_command(interaction: discord.Interaction) -> None:
        await cmd_add_channel(interaction)

    # チャンネル削除コマンド
    @command_group.command(
        name="removelist",
        description="現在のチャンネルをリストから削除します",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def remove_channel_command(interaction: discord.Interaction) -> None:
        await cmd_remove_channel(interaction)

    # チャンネルリストクリアコマンド
    @command_group.command(
        name="clearlist",
        description="チャンネルリストをクリアします",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def clear_channels_command(interaction: discord.Interaction) -> None:
        await cmd_clear_channels(interaction)

    # 翻訳機能設定コマンド
    @command_group.command(
        name="translation", description="国旗リアクションによる翻訳機能を設定します"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def translation_command(interaction: discord.Interaction) -> None:
        await cmd_translation(interaction)

    return command_group
