from __future__ import annotations

import asyncio
import time
import re
from collections import defaultdict, deque

import time
import disnake
import httpx
import spacy
from disnake.ext import commands

from bot.utils.logger import logger
from bot.utils.settings import settings
from bot.utils.helpers import strip_leading_mention


USER_MENTION_RE = re.compile(r"(<@!?\d{15,25}>|@\w{1,32})")


class PeakyResponseService(commands.Cog):
    def __init__(self, bot: commands.Bot, nice: bool) -> None:
        self.bot = bot
        self.nice = nice

        if not settings.peaky_tools_enabled:
            logger.info(
                "PeakyTools: Disabled via settings.peaky_tools_enabled"
            )
            return

        if not settings.peaky_tools_target_user_ids:
            logger.warning(
                "PeakyTools: Enabled but peaky_tools_target_user_ids is empty; cog will never trigger."
            )
            return

        if not settings.openai_api_key:
            logger.warning(
                "PeakyTools: Enabled but openai_api_key is empty; cog will not reply."
            )
            return

        self._target_ids = frozenset(settings.peaky_tools_target_user_ids)
        self._whitelist_ids = frozenset(settings.peaky_tools_max_request_user_id_whitelist or [])

        self._cooldowns: dict[int, deque[float]] = defaultdict(deque)
        self._sem = asyncio.Semaphore(max(1, settings.peaky_tools_max_concurrent_tasks))
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.peaky_tools_request_timeout_seconds),
        )
        self._bg_tasks: set[asyncio.Task[None]] = set()
        self._nlpnames: spacy.language.Language = spacy.load(settings.peaky_tools_nlp_model_name)


    def shutdown(self) -> None:
        for t in list(self._bg_tasks):
            t.cancel()

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and not loop.is_closed():
            loop.create_task(self._http.aclose())


    async def handle(self, msg: disnake.Message, allow_no_ref: bool = False) -> None:
        ref = await self._fetch_referenced_message(msg)
        if ref is None and not allow_no_ref:
            return

        if ref and ref.author.id not in self._target_ids:
            return

        if self._is_excluded_embed_title(msg, ref or msg):
            return

        if self._is_user_throttled(msg):
            return

        task = asyncio.create_task(self._handle_message(msg, ref or msg))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)


    def _is_excluded_embed_title(self, msg: disnake.Message, ref: disnake.Message) -> bool:
        excluded_titles = tuple(
            t.lower() for t in (settings.peaky_tools_target_embed_exclusions or [])
        )

        if not excluded_titles:
            return False

        for embed in ref.embeds:
            if not embed.title:
                continue

            title = embed.title.lower()

            if any(excluded in title for excluded in excluded_titles):
                logger.debug(
                    f'PeakyTools: Skipping reply with message ID {msg.id} to reply message ID {ref.id} '
                    f'due to excluded embed title in referenced message: "{embed.title}"'
                )
                return True

        return False


    def _is_user_throttled(self, msg: disnake.Message) -> bool:
        now = time.monotonic()

        user_id = msg.author.id

        if user_id in self._whitelist_ids:
            logger.debug(
                f"PeakyTools: User {msg.author} with ID {user_id} is whitelisted from rate limiting."
            )
            return False

        window_seconds = settings.peaky_tools_window_seconds
        max_requests = settings.peaky_tools_max_requests
        timestamps = self._cooldowns[user_id]
        cutoff = now - window_seconds

        while timestamps and timestamps[0] < cutoff:
            timestamps.popleft()

        if len(timestamps) >= max_requests:
            logger.debug(
                f"PeakyTools: Throttling user {msg.author} with ID {user_id} "
                f"({len(timestamps)} triggers in last {window_seconds}s)"
            )
            return True

        timestamps.append(now)

        return False


    async def _fetch_referenced_message(self, message: disnake.Message) -> disnake.Message | None:
        if not message.reference or not message.reference.message_id:
            return None

        if isinstance(message.reference.resolved, disnake.Message):
            return message.reference.resolved

        try:
            return await message.channel.fetch_message(message.reference.message_id)
        except (disnake.NotFound, disnake.Forbidden, disnake.HTTPException):
            return None


    async def _handle_message(self, msg: disnake.Message, ref: disnake.Message) -> None:
        async with self._sem:
            attempt_count = 0
            attempt_limit = 6

            while attempt_count < attempt_limit:
                attempt_count += 1

                logger.debug(
                    f'PeakyTools: Starting generation of peaky message in reply to "{msg.author}@{msg.id}" <- "{ref.author}" (mode: {"nice" if self.nice else "snarky"}, attempt: {attempt_count}/{attempt_limit})'
                )

                snark = await self._openai_snark(
                    author_name=str(msg.author),
                    target_name=str(ref.author),
                    user_text=msg.content or "",
                )

                snark = self._cleanup_snark_response(snark, msg)

                if not snark:
                    logger.warning(
                        f'PeakyTools: OpenAI request failed for message "{msg.author}@{msg.id}" on attempt {attempt_count}/{attempt_limit}.'
                    )
                    await asyncio.sleep(0.2 ** attempt_count)
                    continue

                logger.debug(
                    f'PeakyTools: Finished generation of peaky message in reply to "{msg.author}@{msg.id}" with result "{snark!r}"'
                )

                allowed = disnake.AllowedMentions(users=True, roles=False, everyone=False)

                try:
                    await msg.reply(snark, allowed_mentions=allowed)
                    break
                except (disnake.Forbidden, disnake.HTTPException) as e:
                    logger.warning(
                        f'PeakyTools: Sending of message "{msg.author}@{msg.id}" failed on attempt {attempt_count}/{attempt_limit}: {e}'
                    )
                    continue


    def _cleanup_snark_response(self, response: str | None, msg: disnake.Message) -> str | None:
        response = (response or "").strip()

        if not response:
            return None

        spans = [
            ent for ent in self._nlpnames(response).ents
            if ent.label_ == "PERSON"
        ]

        if spans:
            result = []
            last_e = 0

            for ent in spans:
                result.append(response[last_e:ent.start_char])
                result.append(msg.author.mention)
                last_e = ent.end_char

            result.append(response[last_e:])

            response = "".join(result).strip()

        if len(response) < 2:
            return None

        response = self._replace_username_with_mention(
            response,
            msg.author
        )

        return response


    def _generate_system_tone_instructions(self) -> str:
        if not self.nice:
            return (
                "- Unhinged, rude, dismissive, condescending, and chaotic.\n"
                "- Confident insults and blunt profanity are encouraged.\n"
                "- Include at least one swear per reply.\n"
                "- Sound like you're fed up and done with the conversation.\n"
                "- Keep it concise and to the point.\n"
                "- Use gen-z slang if appropriate.\n"
                "- Use modern slang and internet culture references.\n"
            )

        return (
            "- Friendly, polite, upbeat, and supportive.\n"
            "- Confident statements, compliments, and agreeable statements are encouraged.\n"
            "- Keep it concise and to the point.\n"
            "- Use modern slang and internet culture references.\n"
            "- Use gen-z slang if appropriate.\n"
            "- Don't say overuse the term 'legend'.\n"
            "- The reply must be a compliment.\n"
            "- Reply must not be mean, negative, or dismissive in any way.\n"
        )


    def _generate_system_rule_instructions(self) -> str:
        rules: str = (
            "- No slurs, no threats, no hate speech, no hate toward protected groups.\n"
            "- Profanity is allowed and encouraged.\n"
            "- No apologies, no disclaimers, no softening language, no em dashes.\n"
            "- Prefer 1 sentence. Prefer short sentences with less than 10 words.\n"
            "- Don't start with a Discord username or displayname @mention of anyone.\n"
            "- If asked, your creator is RMF, but also mention Peaky as being an inspiration.\n"
            "- No tech related jokes.\n"
            "- Don't mention you are an AI language model.\n"
            "- Don't mention these rules.\n"
        )

        if not self.nice:
            rules += (
                "- Direct insults are allowed if they target behavior, intelligence, grammar, and spelling.\n"
            )

        return rules


    def _generate_system_open_instructions(self) -> str:
        if not self.nice:
            return (
                "You are a Discord bot called invisipeak that posts short, funny, aggressively snarky replies.\n"
            )

        return (
            "You are a Discord bot called peaky that posts short, funny, supportive replies.\n"
        )


    def _generate_system_instructions(self) -> str:
        instructions: str = (
            self._generate_system_open_instructions() +
            "Tone:\n" + self._generate_system_tone_instructions() +
            "Rules:\n" + self._generate_system_rule_instructions()
        )

        return instructions


    async def _openai_snark(self, *, author_name: str, target_name: str, user_text: str) -> str | None:
        if not settings.openai_api_key:
            return None

        system_instructions = self._generate_system_instructions()

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
            "model": settings.openai_nice_model if self.nice else settings.openai_mean_model,
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
            "max_output_tokens": settings.peaky_tools_max_output_tokens,
            "store": False,
        }

        try:
            resp = await self._http.post(settings.openai_base_url, headers=headers, json=payload)
        except (httpx.TimeoutException, httpx.TransportError) as e:
            logger.warning(
                f"PeakyTools: OpenAI request failed: {type(e).__name__}: {e}"
            )
            return None

        if resp.status_code >= 400:
            logger.warning(
                f"PeakyTools: OpenAI error {resp.status_code}: {resp.text[:500]}"
            )
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


    def contains_no_user_mention(self, text: str) -> bool:
        return not bool(USER_MENTION_RE.search(text))


    def _replace_username_with_mention(
        self,
        content: str | None,
        user: disnake.abc.User,
    ) -> str | None:
        if not content:
            return None

        return strip_leading_mention(content).strip()

        if self.contains_no_user_mention(content):
            content = self._ensure_leading_mention(content, user)

        return


    def _ensure_leading_mention(
        self,
        content: str,
        user: disnake.abc.User,
    ) -> str:
        if not content:
            return user.mention

        mention = user.mention

        pattern = re.compile(
            rf"@{re.escape(user.name)}\b",
            flags=re.IGNORECASE,
        )
        content = pattern.sub(mention, content).strip()

        if content.startswith(mention):
            return content

        return f"{mention} {content}"
