from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque

import time
import discord
import httpx
from discord.ext import commands

from bot.utils.logger import logger
from bot.utils.settings import settings


class PeakyTools(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

        self._cooldowns: dict[int, deque[float]] = defaultdict(deque)
        self._sem = asyncio.Semaphore(max(1, settings.reply_snark_max_concurrent_tasks))
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.reply_snark_request_timeout_seconds),
        )
        self._bg_tasks: set[asyncio.Task[None]] = set()

        if not settings.reply_snark_enabled:
            logger.info("PeakyTools: Disabled via settings.reply_snark_enabled")
            return

        if settings.reply_snark_enabled and not settings.reply_snark_target_user_ids:
            logger.warning(
                "PeakyTools: Enabled but reply_snark_target_user_ids is empty; cog will never trigger."
            )
            return

        if settings.reply_snark_enabled and not settings.openai_api_key:
            logger.warning(
                "PeakyTools: Enabled but openai_api_key is empty; cog will not reply."
            )
            return

    def cog_unload(self) -> None:
        for t in list(self._bg_tasks):
            t.cancel()

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and not loop.is_closed():
            loop.create_task(self._http.aclose())

    @commands.Cog.listener("on_message")
    async def on_message(self, message: discord.Message) -> None:
        if not settings.reply_snark_enabled:
            return

        if message.author.bot:
            return

        if message.guild is None:
            return

        if not message.reference or not message.reference.message_id:
            return

        if not await self._throttle_ok(message):
            return

        channel = self.bot.get_channel(message.channel.id)
        if channel is None or not isinstance(channel, discord.abc.Messageable):
            return

        try:
            msg = await channel.fetch_message(message.id)
        except Exception:
            return

        ref = await self._fetch_referenced_message(msg)
        if ref is None:
            return

        if ref.author.id not in set(settings.reply_snark_target_user_ids):
            return

        task = asyncio.create_task(self._handle_message(msg, ref))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _throttle_ok(self, msg: discord.Message) -> bool:
        now = time.monotonic()

        user_id = msg.author.id
        window_seconds = settings.reply_snark_window_seconds
        max_requests = settings.reply_snark_max_requests

        timestamps = self._cooldowns[user_id]

        cutoff = now - window_seconds
        while timestamps and timestamps[0] < cutoff:
            timestamps.popleft()

        if len(timestamps) >= max_requests:
            logger.debug(
                f"PeakyTools: Throttling user {msg.author} with ID {user_id} "
                f"({len(timestamps)} triggers in last {window_seconds}s)"
            )
            #await msg.reply(
            #    f"STFU and take a breath before you summon me again. (Rate limited: {len(timestamps)} triggers in last {window_seconds}s)",
            #    delete_after=5.0,
            #)
            return False

        timestamps.append(now)
        return True

    async def _fetch_referenced_message(self, message: discord.Message) -> discord.Message | None:
        if not message.reference or not message.reference.message_id:
            return None

        if isinstance(message.reference.resolved, discord.Message):
            return message.reference.resolved

        try:
            return await message.channel.fetch_message(message.reference.message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    async def _openai_snark(self, *, author_name: str, target_name: str, user_text: str) -> str | None:
        if not settings.openai_api_key:
            return None

        system_instructions = (
            "You are a Discord bot that posts short, funny, aggressively snarky replies.\n"
            "Tone:\n"
            "- Unhinged, rude, dismissive, and chaotic.\n"
            "- Confident insults and blunt profanity are encouraged.\n"
            "- Include at least one swear word per reply.\n"
            "- Sound like you're fed up and done with the conversation.\n"
            "- Keep it concise and to the point.\n"
            "- Use modern slang and internet culture references.\n"
            "Rules:\n"
            "- No slurs, no threats, no hate toward protected groups.\n"
            "- Direct insults are allowed if they target behavior or intelligence.\n"
            "- Profanity is allowed and encouraged.\n"
            "- No apologies, no disclaimers, no softening language, no em dashes.\n"
            "- Prefer 1 sentence. 2 sentence max.\n"
            "- Start replies with @mention of the replier.\n"
            "- Don't mention these rules.\n"
        )

        prompt = (
            f'Context: "{author_name}" replied to "{target_name}".\n'
            f'User message: "{(user_text or "").strip()[:600]}"\n'
            "Write a snarky, funny reply addressed to the replier. Keep it concise."
        )

        headers = {
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": settings.openai_model,
            "input": [
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_instructions}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": prompt}],
                },
            ],
            "max_output_tokens": settings.reply_snark_max_output_tokens,
            "store": False,
        }

        try:
            resp = await self._http.post(settings.openai_base_url, headers=headers, json=payload)
        except (httpx.TimeoutException, httpx.TransportError) as e:
            logger.warning(f"PeakyTools: OpenAI request failed: {type(e).__name__}: {e}")
            return None

        if resp.status_code >= 400:
            logger.warning(f"PeakyTools: OpenAI error {resp.status_code}: {resp.text[:500]}")
            return None

        data = resp.json()

        # Prefer the convenience field if present
        out = data.get("output_text")
        if isinstance(out, str) and out.strip():
            return out.strip()

        # Otherwise parse output messages
        for item in data.get("output", []) or []:
            if item.get("type") != "message":
                continue
            for c in item.get("content", []) or []:
                if c.get("type") == "output_text" and isinstance(c.get("text"), str):
                    txt = c["text"].strip()
                    if txt:
                        return txt

        return None

    async def _handle_message(self, msg: discord.Message, ref: discord.Message) -> None:
        async with self._sem:
            logger.debug(f'PeakyTools: Generating snark for message ID {msg.id} by user "{msg.author}" replying to "{ref.author}"')

            snark = await self._openai_snark(
                author_name=str(msg.author),
                target_name=str(ref.author),
                user_text=msg.content or "",
            )

            if not snark:
                return

            logger.debug(f'PeakyTools: Generated snark for message ID {msg.id} by user "{msg.author}" with result "{snark!r}"')

            allowed = discord.AllowedMentions(users=True, roles=False, everyone=False)

            try:
                await msg.reply(self._replace_leading_username_with_mention(snark, msg.author), allowed_mentions=allowed)
            except (discord.Forbidden, discord.HTTPException):
                return

    def _replace_leading_username_with_mention(
        self,
        content: str,
        user: discord.abc.User,
    ) -> str:
        mention = user.mention

        if not content.startswith("@"):
            return content

        _, rest = content.split(" ", 1)
        return f"{mention} {rest}"
