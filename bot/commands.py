import asyncio
from typing import Any

import discord
from discord import app_commands, ui

import config
from ai.conversation import channel_conversations
from log_utils.logger import logger
from utils.channel_config import ChannelConfig, ChannelConfigManager
from utils.proactive_registry import ClaimStatus, ProactiveRegistry, get_proactive_registry

# チャンネル設定マネージャーのシングルトンインスタンスを取得
config_manager = ChannelConfigManager.get_instance()


async def _defer(interaction: discord.Interaction) -> None:
    """設定の読み書き (Firestore 等) の前に応答を保留し、3秒の応答期限切れを防ぐ

    管理コマンドの応答は実行者だけに見せるため ephemeral で保留する。

    Args:
        interaction: インタラクションオブジェクト
    """
    if not interaction.response.is_done():
        await interaction.response.defer(thinking=True, ephemeral=True)


async def _reply(
    interaction: discord.Interaction, content: str, view: ui.View | None = None
) -> None:
    """インタラクションに返信する（defer 済みなら followup で送る）

    管理コマンドの応答（チャンネル一覧など）は実行者だけに見えるよう ephemeral で送る。

    Args:
        interaction: インタラクションオブジェクト
        content: 送信する本文
        view: 添付するビュー（任意）
    """
    if interaction.response.is_done():
        if view is None:
            await interaction.followup.send(content, ephemeral=True)
        else:
            await interaction.followup.send(content, view=view, ephemeral=True)
    elif view is None:
        await interaction.response.send_message(content, ephemeral=True)
    else:
        await interaction.response.send_message(content, view=view, ephemeral=True)


_LOAD_FAILED_MESSAGE = (
    "⚠️ 設定を読み込めなかったため、このサーバーでの発言を一時的に止めています。"
    "しばらくしてからもう一度試してください"
)


async def _get_config_or_notify(
    interaction: discord.Interaction, guild_id: int
) -> ChannelConfig | None:
    """ギルドの設定を取得する。読み込みに失敗していればその旨を返信して None を返す

    読み込み失敗中の設定はデフォルト値のため、そのまま表示・変更すると実際の挙動
    （発言停止）と食い違う。

    Args:
        interaction: インタラクションオブジェクト
        guild_id: ギルドID

    Returns:
        設定インスタンス。読み込みに失敗している場合は None。
    """
    channel_config = await asyncio.to_thread(config_manager.get_config, guild_id)
    if channel_config.load_failed is True:
        await _reply(interaction, _LOAD_FAILED_MESSAGE)
        return None
    return channel_config


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
        await _defer(interaction)
        # 保存済みのguild_idを使用
        channel_config = await _get_config_or_notify(interaction, self.guild_id)
        if channel_config is None:
            return

        selected_mode = self.values[0]
        success = await asyncio.to_thread(channel_config.set_behavior, selected_mode)

        if success:
            # 設定保存後にリストを再読み込み
            await asyncio.to_thread(channel_config.load_config)
            mode_name = "限定モード" if selected_mode == "allow" else "全体モード"
            await _reply(
                interaction,
                f"✅ 評価モードを「{mode_name}」に変更しました！\n"
                f"現在のリストは「{channel_config.get_list_display_name()}」として扱われます"
            )
        else:
            await _reply(interaction, "❌ 評価モードの変更に失敗しました")


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
        await _defer(interaction)
        # 保存済みのguild_idを使用
        channel_config = await _get_config_or_notify(interaction, self.guild_id)
        if channel_config is None:
            return

        selected_value = (
            self.values[0] == "true"
        )  # "true" または "false" を boolean に変換
        success = await asyncio.to_thread(channel_config.set_translation_enabled, selected_value)

        if success:
            # 設定保存後にリストを再読み込み
            await asyncio.to_thread(channel_config.load_config)
            status = "有効" if selected_value else "無効"
            await _reply(
                interaction,
                f"✅ 翻訳機能を「{status}」に設定しました！"
            )
        else:
            await _reply(
                interaction,
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

    async def _close(self, interaction: discord.Interaction) -> None:
        """ボタンを無効化してビューを止め、二重に押されないようにする

        確認メッセージの編集がインタラクションへの応答を兼ねるため、以降の返信は followup になる。

        Args:
            interaction: ボタンのインタラクション
        """
        for item in self.children:
            if isinstance(item, ui.Button):
                item.disabled = True
        self.stop()
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="はい", style=discord.ButtonStyle.danger)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """確認ボタンのコールバック"""
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("👮 このコマンドは管理者権限が必要だよ！", ephemeral=True)
            return
        await self._close(interaction)
        # 保存済みのguild_idを使用
        channel_config = await _get_config_or_notify(interaction, self.guild_id)
        if channel_config is None:
            return

        success = await asyncio.to_thread(channel_config.clear_channels)

        if success:
            # 設定保存後にリストを再読み込み
            await asyncio.to_thread(channel_config.load_config)
            await _reply(
                interaction,
                f"✅ {channel_config.get_list_display_name()}をクリアしました！"
            )
        else:
            await _reply(interaction, "❌ リストのクリアに失敗しました")

    @discord.ui.button(label="いいえ", style=discord.ButtonStyle.secondary)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """キャンセルボタンのコールバック"""
        await self._close(interaction)
        await _reply(interaction, "✅ キャンセルしました")


async def cmd_mode(interaction: discord.Interaction) -> None:
    """評価モード切替コマンドを処理する

    Args:
        interaction: インタラクションオブジェクト
    """
    if not interaction.guild:
        await _reply(
            interaction,
            "❌ このコマンドはサーバー内でのみ使用できます"
        )
        return

    # ギルド固有の設定を取得（I/O の前に応答を保留する）
    guild_id = interaction.guild.id
    await _defer(interaction)
    channel_config = await _get_config_or_notify(interaction, guild_id)
    if channel_config is None:
        return

    # 現在のモード情報表示
    current_mode = channel_config.get_mode_display_name()
    list_type = channel_config.get_list_display_name()

    await _reply(
        interaction,
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


def _format_channel_info(channel_data: dict[str, Any], bot: discord.Client) -> str:
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


def _build_channel_list_message(
    bot: discord.Client, channel_config: ChannelConfig, page: int
) -> str:
    """チャンネル一覧コマンドの応答メッセージを組み立てる

    Args:
        bot: Discordクライアント
        channel_config: ギルドのチャンネル設定
        page: 表示するページ番号（1始まり、範囲外は丸める）

    Returns:
        str: ヘッダー・チャンネル一覧・ページ情報を含むメッセージ
    """
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

    return channel_info


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
        await _reply(
            interaction,
            "❌ このコマンドはサーバー内でのみ使用できます"
        )
        return

    # ギルド固有の設定を取得（I/O の前に応答を保留する）
    guild_id = interaction.guild.id
    await _defer(interaction)
    channel_config = await _get_config_or_notify(interaction, guild_id)
    if channel_config is None:
        return

    channel_info = _build_channel_list_message(bot, channel_config, page)

    # メッセージ送信
    await _reply(interaction, channel_info)


async def cmd_add_channel(interaction: discord.Interaction) -> None:
    """現在のチャンネルをリストに追加するコマンドを処理する

    Args:
        interaction: インタラクションオブジェクト
    """
    if not interaction.guild:
        await _reply(
            interaction,
            "❌ このコマンドはサーバー内でのみ使用できます"
        )
        return

    # ギルド固有の設定を取得（I/O の前に応答を保留する）
    guild_id = interaction.guild.id
    await _defer(interaction)
    channel_config = await _get_config_or_notify(interaction, guild_id)
    if channel_config is None:
        return

    channel = interaction.channel
    if channel is None:
        await _reply(
            interaction,
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
    success = await asyncio.to_thread(channel_config.add_channel, channel_id, safe_channel_name)
    list_name = channel_config.get_list_display_name()

    if success:
        # 設定保存後にリストを再読み込み
        await asyncio.to_thread(channel_config.load_config)
        await _reply(
            interaction,
            f"✅ チャンネル「{channel_name}」を{list_name}に追加しました！"
        )
    else:
        await _reply(interaction, "❌ チャンネルの追加に失敗しました")


async def cmd_remove_channel(interaction: discord.Interaction) -> None:
    """現在のチャンネルをリストから削除するコマンドを処理する

    Args:
        interaction: インタラクションオブジェクト
    """
    if not interaction.guild:
        await _reply(
            interaction,
            "❌ このコマンドはサーバー内でのみ使用できます"
        )
        return

    # ギルド固有の設定を取得（I/O の前に応答を保留する）
    guild_id = interaction.guild.id
    await _defer(interaction)
    channel_config = await _get_config_or_notify(interaction, guild_id)
    if channel_config is None:
        return

    channel = interaction.channel
    if channel is None:
        await _reply(
            interaction,
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
    success = await asyncio.to_thread(channel_config.remove_channel, channel_id)
    list_name = channel_config.get_list_display_name()

    if success:
        # 設定保存後にリストを再読み込み
        await asyncio.to_thread(channel_config.load_config)
        # チャンネルがリストにまだ存在するかチェック
        if channel_config.is_channel_in_list(channel_id):
            # 削除に失敗している場合（まだリストに存在する）
            await _reply(
                interaction,
                f"❌ チャンネル「{channel_name}」の削除に失敗しました（まだ{list_name}に含まれています）"
            )
        else:
            # 削除成功（もうリストに存在しない）
            await _reply(
                interaction,
                f"✅ チャンネル「{channel_name}」を{list_name}から削除しました！"
            )
    else:
        await _reply(interaction, "❌ チャンネルの削除に失敗しました")


async def cmd_clear_channels(interaction: discord.Interaction) -> None:
    """チャンネルリストをクリアするコマンドを処理する

    Args:
        interaction: インタラクションオブジェクト
    """
    if not interaction.guild:
        await _reply(
            interaction,
            "❌ このコマンドはサーバー内でのみ使用できます"
        )
        return

    # ギルド固有の設定を取得（I/O の前に応答を保留する）
    guild_id = interaction.guild.id
    await _defer(interaction)
    channel_config = await _get_config_or_notify(interaction, guild_id)
    if channel_config is None:
        return

    list_name = channel_config.get_list_display_name()

    await _reply(
        interaction,
        f"❓ {list_name}をクリアしますか？\n" f"この操作は元に戻せません。",
        view=ClearConfirmView(guild_id),
    )



async def cmd_translation(interaction: discord.Interaction) -> None:
    """翻訳機能の有効/無効切替コマンドを処理する

    Args:
        interaction: インタラクションオブジェクト
    """
    if not interaction.guild:
        await _reply(
            interaction,
            "❌ このコマンドはサーバー内でのみ使用できます"
        )
        return

    # ギルド固有の設定を取得（I/O の前に応答を保留する）
    guild_id = interaction.guild.id
    await _defer(interaction)
    channel_config = await _get_config_or_notify(interaction, guild_id)
    if channel_config is None:
        return

    # 現在の翻訳機能状態を取得
    is_enabled = channel_config.get_translation_enabled()
    status = "有効" if is_enabled else "無効"

    # 翻訳機能の説明メッセージ
    help_text = (
        "🇺🇸 アメリカ国旗リアクションで英語翻訳\n"
        "🇯🇵 日本国旗リアクションで日本語翻訳\n"
    )

    await _reply(
        interaction,
        f"🌐 **翻訳機能**: 現在「{status}」です\n\n"
        f"{help_text}\n"
        "👇 設定を変更する場合は、下のメニューから選択してください",
        view=TranslationView(guild_id),
    )


_PROACTIVE_ERROR_MESSAGE = (
    "❌ 自発会話の設定を変更できませんでした。しばらくしてからもう一度試してください"
)


async def _proactive_turn_on(
    interaction: discord.Interaction, channel_config: ChannelConfig, channel_id: int
) -> None:
    """登録簿に担当として登録してから、チャンネル設定で自発会話を ON にする

    設定の保存に失敗したら、今回新しく登録した場合だけ登録簿から削除して巻き戻す。

    Args:
        interaction: インタラクションオブジェクト
        channel_config: ギルドのチャンネル設定
        channel_id: 対象のチャンネルID
    """
    registry = get_proactive_registry()
    instance = config.INSTANCE_NAME
    try:
        result = await asyncio.to_thread(registry.claim, channel_id, instance)
    except Exception:
        logger.error(f"自発会話の登録簿への登録に失敗: チャンネルID={channel_id}", exc_info=True)
        await _reply(interaction, _PROACTIVE_ERROR_MESSAGE)
        return

    if result.status is ClaimStatus.OWNED_BY_OTHER:
        await _reply(
            interaction,
            f"⚠️ このチャンネルの自発会話は「{result.owner}」が担当しています。"
            "1つのチャンネルを担当できるのは1インスタンスだけです",
        )
        return

    if await asyncio.to_thread(channel_config.add_proactive_channel, channel_id):
        await _reply(interaction, "✅ このチャンネルの自発会話をONにしました！")
        return

    if result.status is ClaimStatus.CLAIMED:
        await _rollback_claim(registry, channel_id, instance)
    await _reply(interaction, _PROACTIVE_ERROR_MESSAGE)


async def _rollback_claim(
    registry: ProactiveRegistry, channel_id: int, instance: str
) -> None:
    """設定の保存に失敗したときに、登録簿への登録を取り消す

    Args:
        registry: 登録簿
        channel_id: 対象のチャンネルID
        instance: 自インスタンス名
    """
    logger.warning(f"自発会話の設定保存に失敗したため登録簿から削除します: チャンネルID={channel_id}")
    try:
        await asyncio.to_thread(registry.release, channel_id, instance)
    except Exception:
        logger.error(
            f"自発会話の登録簿の巻き戻しに失敗: チャンネルID={channel_id}", exc_info=True
        )


async def _proactive_turn_off(
    interaction: discord.Interaction, channel_config: ChannelConfig, channel_id: int
) -> None:
    """チャンネル設定で自発会話を OFF にしてから、自分が担当なら登録簿から削除する

    Args:
        interaction: インタラクションオブジェクト
        channel_config: ギルドのチャンネル設定
        channel_id: 対象のチャンネルID
    """
    if not await asyncio.to_thread(channel_config.remove_proactive_channel, channel_id):
        await _reply(interaction, _PROACTIVE_ERROR_MESSAGE)
        return

    registry = get_proactive_registry()
    try:
        await asyncio.to_thread(registry.release, channel_id, config.INSTANCE_NAME)
    except Exception:
        logger.error(f"自発会話の登録簿からの削除に失敗: チャンネルID={channel_id}", exc_info=True)
        await _reply(
            interaction,
            "⚠️ 自発会話はOFFにしましたが、担当の解除に失敗しました。"
            "もう一度OFFにしてください",
        )
        return
    await _reply(interaction, "✅ このチャンネルの自発会話をOFFにしました")


async def _proactive_show_status(
    interaction: discord.Interaction, channel_config: ChannelConfig, channel_id: int
) -> None:
    """チャンネルの自発会話の状態（ON/OFF と担当インスタンス）を表示する

    Args:
        interaction: インタラクションオブジェクト
        channel_config: ギルドのチャンネル設定
        channel_id: 対象のチャンネルID
    """
    status = "ON" if channel_config.is_proactive_channel(channel_id) else "OFF"
    try:
        owner = await asyncio.to_thread(get_proactive_registry().get_owner, channel_id)
    except Exception:
        logger.error(f"自発会話の登録簿の読み込みに失敗: チャンネルID={channel_id}", exc_info=True)
        owner_text = "（取得できませんでした）"
    else:
        owner_text = owner or "なし"
    await _reply(
        interaction,
        f"💬 **自発会話**: 現在「{status}」です\n"
        f"このチャンネルの担当: {owner_text}\n\n"
        "👉 `enabled` に True / False を指定すると切り替えられます",
    )


async def cmd_proactive(
    interaction: discord.Interaction, enabled: bool | None = None
) -> None:
    """実行したチャンネルの自発会話を ON/OFF するコマンドを処理する

    Args:
        interaction: インタラクションオブジェクト
        enabled: True で ON、False で OFF、None なら現在の状態を表示する
    """
    if not interaction.guild:
        await _reply(interaction, "❌ このコマンドはサーバー内でのみ使用できます")
        return
    channel = interaction.channel
    if channel is None:
        await _reply(interaction, "❌ チャンネル情報を取得できませんでした")
        return
    if isinstance(channel, discord.Thread):
        # 自発会話の対象はチャンネルのみ。スレッドでは設定も状態表示もしない
        await _reply(
            interaction, "❌ 自発会話はスレッドでは使えません。チャンネルで実行してください"
        )
        return

    await _defer(interaction)
    channel_config = await _get_config_or_notify(interaction, interaction.guild.id)
    if channel_config is None:
        return

    if enabled is None:
        await _proactive_show_status(interaction, channel_config, channel.id)
    elif enabled:
        await _proactive_turn_on(interaction, channel_config, channel.id)
    else:
        await _proactive_turn_off(interaction, channel_config, channel.id)


async def handle_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
) -> None:
    """スラッシュコマンドエラーハンドラ

    Args:
        interaction: インタラクションオブジェクト
        error: エラーオブジェクト
    """
    if isinstance(error, app_commands.errors.MissingPermissions):
        await _send_ephemeral(interaction, "👮 このコマンドは管理者権限が必要だよ！")
        return
    if isinstance(error, app_commands.errors.NoPrivateMessage):
        await _send_ephemeral(interaction, "❌ このコマンドはサーバー内でのみ使用できます")
        return

    # 例外の詳細はログにのみ出し、ユーザーには固定文言を返す
    logger.error(f"コマンドエラー発生: {str(error)}", exc_info=True)
    await _send_ephemeral(
        interaction, "😱 コマンド実行中にエラーが発生しちゃった…時間を置いてもう一度試してみてね"
    )


async def _send_ephemeral(interaction: discord.Interaction, content: str) -> None:
    """インタラクションに本人だけ見えるメッセージを送る

    すでに応答済み（send_message / defer 済み）の場合は followup で送る。
    送信自体の失敗（インタラクション期限切れ等）はログに残して握りつぶす。

    Args:
        interaction: インタラクションオブジェクト
        content: 送信する本文
    """
    try:
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=True)
        else:
            await interaction.response.send_message(content, ephemeral=True)
    except discord.HTTPException:
        logger.warning("コマンドエラー通知の送信に失敗しました", exc_info=True)


def _register_channel_list_commands(
    command_group: app_commands.Group, bot: discord.Client
) -> None:
    """チャンネルリスト関連のコマンド（一覧・追加・削除・クリア）を登録する

    Args:
        command_group: 登録先のコマンドグループ
        bot: Discordクライアント
    """
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

    # チャンネルリスト関連コマンド（一覧・追加・削除・クリア）
    _register_channel_list_commands(command_group, bot)

    # 翻訳機能設定コマンド
    @command_group.command(
        name="translation", description="国旗リアクションによる翻訳機能を設定します"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def translation_command(interaction: discord.Interaction) -> None:
        await cmd_translation(interaction)

    _register_proactive_command(command_group)

    return command_group


def _register_proactive_command(command_group: app_commands.Group) -> None:
    """自発会話の ON/OFF コマンドを登録する

    Args:
        command_group: 登録先のコマンドグループ
    """
    @command_group.command(
        name="proactive",
        description="このチャンネルの自発会話をON/OFFします（指定なしで現在の状態を表示）",
    )
    @app_commands.describe(enabled="True でON、False でOFF")
    @app_commands.checks.has_permissions(administrator=True)
    async def proactive_command(
        interaction: discord.Interaction, enabled: bool | None = None
    ) -> None:
        await cmd_proactive(interaction, enabled)
