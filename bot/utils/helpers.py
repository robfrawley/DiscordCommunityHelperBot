from datetime import datetime
import re
import httpx

import discord
from discord.ext import commands

from bot.core.bot import Bot
from bot.models.emoji_payload import EmojiPayload
from bot.models.role_identifier import RoleIdentifier
from bot.utils.logger import ConsoleLogger
from bot.utils.settings import SettingsManager
from bot.models.private_message_record import PrivateMessageRecord
from bot.utils.logger import logger
from bot.utils.settings import settings

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


async def check_command_role_permission(
    interaction: discord.Interaction,
    authorized_roles: list[RoleIdentifier]
) -> bool:
    if not authorized_roles:
        logger.warning(
            "No roles are configured to use private message commands."
        )
        await interaction.response.send_message(
            "No roles are configured to use this command.",
            ephemeral=True,
        )
        return False

    if interaction.guild is None:
        logger.debug(
            "Private message command used outside of a guild."
        )
        await interaction.response.send_message(
            "This command can only be used in a server.",
            ephemeral=True,
        )
        return False

    member = interaction.guild.get_member(interaction.user.id)
    if member is None:
        logger.warning(
            f"Unable to resolve server member for user {interaction.user.id}."
        )
        await interaction.response.send_message(
            "Unable to resolve your server roles.",
            ephemeral=True,
        )
        return False

    if not any(
        role.id in authorized_roles for role in member.roles
    ):
        logger.warning(
            f"User {interaction.user.id} lacks required roles "
            "to use private message commands."
        )
        await interaction.response.send_message(
            "You do not have permission to use this command.",
            ephemeral=True,
        )
        return False

    return True


def extract_reaction_payload_info(payload: discord.RawReactionActionEvent) -> EmojiPayload:
    parts: list[str | int | None] = [
        get_emoji_as_readable_utf8_str(payload),
        payload.emoji.id,
    ]

    return EmojiPayload(
        message_id=payload.message_id,
        channel_id=payload.channel_id,
        user_id=payload.user_id,
        guild_id=payload.guild_id if payload.guild_id is not None else 0,
        emoji="-".join(str(x) for x in parts if x is not None),
        timestamp=datetime.now(settings.bot_time_zone),
    )


def get_log_channel(bot: commands.Bot) -> discord.TextChannel | None:
    if settings.reaction_abuser_log_channel_id is None:
        logger.warning("Reaction abuser log channel ID is not configured.")
        return None

    channel = bot.get_channel(settings.reaction_abuser_log_channel_id)
    if channel is None or not isinstance(channel, discord.TextChannel):
        logger.warning(
            f"Unable to resolve reaction abuser log channel with ID "
            f"{settings.reaction_abuser_log_channel_id}."
        )
        return None

    return channel


def get_emoji_as_readable_utf8_str(payload: discord.RawReactionActionEvent) -> str | None:
    if payload.emoji.name:
        return payload.emoji.name.encode("unicode_escape").decode("ascii")

    return None


def emoji_cdn_url(emoji_id: str, animated: bool | None = None) -> str:
    base = f"https://cdn.discordapp.com/emojis/{emoji_id}"

    gif_url = f"{base}.gif?v=1"
    png_url = f"{base}.png?v=1"

    if animated is True:
        return gif_url

    if animated is False:
        return png_url

    try:
        with httpx.Client(timeout=2.0) as client:
            resp = client.head(gif_url)
            if resp.status_code < 400:
                return gif_url
    except httpx.HTTPError:
        pass

    return png_url


_EMOJI_CUSTOMS_RE = re.compile(r"^([A-Za-z0-9_]+)-(\d+)$")

def encode_emoji_as_renderable(bot: commands.Bot, payload: EmojiPayload) -> str:
    if not payload.emoji:
        return ""

    # Unicode escape text like "\\u2764\\ufe0f" or "\\U0001f525"
    if payload.emoji.startswith("\\"):
        try:
            return payload.emoji.encode("ascii").decode("unicode_escape")
        except Exception as e:
            logger.warning(f"Failed to decode unicode emoji '{payload.emoji}': {e}")
            return ""

    m = _EMOJI_CUSTOMS_RE.fullmatch(payload.emoji)
    if not m:
        return payload.emoji  # if you ever store real unicode directly

    emoji_name, emoji_id = m.group(1), m.group(2)

    guild = bot.get_guild(payload.guild_id)
    emoji_obj = guild and discord.utils.get(guild.emojis, id=int(emoji_id))

    if emoji_obj:
        return f"<{'a' if emoji_obj.animated else ''}:{emoji_name}:{emoji_id}>"

    # Can't render as emoji -> provide a clickable image link
    url = emoji_cdn_url(emoji_id)
    return f"[`:{emoji_name}:`]({url})"
