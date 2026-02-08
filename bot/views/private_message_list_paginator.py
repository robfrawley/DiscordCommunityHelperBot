from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import disnake
from disnake import ui

from bot.db.repos.private_message_repo import private_message_repo

if TYPE_CHECKING:
    from bot.cogs.private_message.private_message_commands import PrivateMessageCommands


class PrivateMessageListPaginator(ui.View):
    def __init__(
        self,
        *,
        cog: "PrivateMessageCommands",
        user_id: int,
        to_user_id: Optional[int],
        from_user_id: Optional[int],
        to_user_label: Optional[str],
        from_user_label: Optional[str],
        limit: int,
        offset: int,
        timeout: float = 600.0,
    ):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.user_id = user_id
        self.to_user_id = to_user_id
        self.from_user_id = from_user_id
        self.to_user_label = to_user_label
        self.from_user_label = from_user_label
        self.limit = limit
        self.offset = offset

        self._prev_btn: ui.Button = self.prev_button  # type: ignore[assignment]
        self._next_btn: ui.Button = self.next_button  # type: ignore[assignment]

        # Initial state
        self._prev_btn.disabled = (self.offset <= 0)

    async def interaction_check(self, interaction: disnake.MessageInteraction) -> bool:
        return interaction.user.id == self.user_id

    async def _refresh(self, interaction: disnake.MessageInteraction) -> None:
        records = await private_message_repo.get_latest(
            to_user_id=self.to_user_id,
            from_user_id=self.from_user_id,
            limit=self.limit,
            offset=self.offset,
        )

        embed = self.cog._build_dm_list_embed(
            records=records,
            to_user_id=self.to_user_id,
            from_user_id=self.from_user_id,
            to_user_label=self.to_user_label,
            from_user_label=self.from_user_label,
            limit=self.limit,
            offset=self.offset,
        )

        self._prev_btn.disabled = (self.offset <= 0)
        self._next_btn.disabled = (len(records) < self.limit)

        await interaction.response.edit_message(embed=embed, view=self)

    @ui.button(label="◀ Prev", style=disnake.ButtonStyle.secondary)
    async def prev_button(self, button: ui.Button, interaction: disnake.MessageInteraction):
        self.offset = max(0, self.offset - self.limit)
        await self._refresh(interaction)

    @ui.button(label="Next ▶", style=disnake.ButtonStyle.secondary)
    async def next_button(self, button: ui.Button, interaction: disnake.MessageInteraction):
        self.offset += self.limit
        await self._refresh(interaction)
