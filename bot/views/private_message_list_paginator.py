import discord
from discord import ui
from typing import Optional

from bot.db.repos.private_message_repo import private_message_repo

class PrivateMessageListPaginator(ui.View):
    def __init__(
        self,
        *,
        cog: "PrivateMessageCommands", # type: ignore # forward reference
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

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    async def _refresh(self, interaction: discord.Interaction) -> None:
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

        # Disable/enable buttons based on paging boundaries
        self.prev_button.disabled = (self.offset <= 0)
        self.next_button.disabled = (len(records) < self.limit)

        await interaction.response.edit_message(embed=embed, view=self)

    @ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: ui.Button):
        self.offset = max(0, self.offset - self.limit)
        await self._refresh(interaction)

    @ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: ui.Button):
        self.offset += self.limit
        await self._refresh(interaction)
