import discord

from bot.utils.logger import ConsoleLogger
from bot.utils.settings import SettingsManager
from bot.models.private_message_record import PrivateMessageRecord

def flatten_newlines_and_strip_str(text: str) -> str:
    return " ".join(line.strip() for line in text.splitlines() if line.strip())

async def get_channel(
    bot: discord.Client,
    *,
    channel_id: int,
    user_id: int | None = None,
) -> discord.abc.Messageable:

    channel = bot.get_channel(channel_id)
    if channel:
        return channel # type: ignore

    if user_id is not None:
        user = await bot.fetch_user(user_id)
        return user.dm_channel or await user.create_dm()

    return await bot.fetch_channel(channel_id) # type: ignore

async def build_dm_embed(
    *,
    guild: discord.Guild | None = None,
    record: PrivateMessageRecord,
    from_user: discord.User | discord.Member | None = None,
    settings: SettingsManager,
) -> discord.Embed:
    guild_name = guild.name if guild else "DM"

    embed = discord.Embed(
        title=settings.private_message_title.format(sender_guild_name=guild_name) if (
            settings.private_message_title
        ) else "Private Message",
        description=record.message,
        color=discord.Color.blurple(),
        timestamp=record.created_at,
    )

    embed.set_footer(
        text=settings.private_message_footer.format(
            sender_username=from_user.name if from_user else "Unknown",
            sender_guild_name=guild_name,
        ),
        icon_url=from_user.display_avatar.url if from_user else None,
    )

    if guild and guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    return embed

async def log_dm_embed(
    bot: discord.Client,
    *,
    embed: discord.Embed,
    record: PrivateMessageRecord,
    logger: ConsoleLogger,
    settings: SettingsManager,
) -> None:
    if settings.private_message_log_channel_id:
        log_channel = await get_channel(
            bot,
            channel_id=settings.private_message_log_channel_id,
        )
        if isinstance(log_channel, discord.TextChannel):
            await log_channel.send(
                content=f"DM from <@{record.from_user_id}> to <@{record.to_user_id}>:",
                embed=embed,
            )
        else:
            logger.warning(
                f"Log channel ID {settings.private_message_log_channel_id} is not a text channel."
            )
