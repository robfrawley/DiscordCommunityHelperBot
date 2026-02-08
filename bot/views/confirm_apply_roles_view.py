from __future__ import annotations

import disnake
from disnake import ui


class ConfirmApplyRolesView(ui.View):
    def __init__(self, requester_id: int, *, timeout: float = 60.0) -> None:
        super().__init__(timeout=timeout)
        self.requester_id = requester_id
        self.confirmed: bool | None = None  # True/False when decided, None if timed out

    async def interaction_check(self, interaction: disnake.MessageInteraction) -> bool:
        # Only the command invoker can confirm/cancel
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "Only the user who ran this command can confirm or cancel.",
                ephemeral=True,
            )
            return False
        return True

    @ui.button(label="Confirm", style=disnake.ButtonStyle.danger)
    async def confirm(self, button: ui.Button, interaction: disnake.MessageInteraction) -> None:
        self.confirmed = True
        for child in self.children:
            if isinstance(child, ui.Button):
                child.disabled = True
        await interaction.response.edit_message(
            content="✅ Confirmed. Starting role assignment...",
            view=self,
        )
        self.stop()

    @ui.button(label="Cancel", style=disnake.ButtonStyle.secondary)
    async def cancel(self, button: ui.Button, interaction: disnake.MessageInteraction) -> None:
        self.confirmed = False
        for child in self.children:
            if isinstance(child, ui.Button):
                child.disabled = True
        await interaction.response.edit_message(
            content="❌ Cancelled. No roles were changed.",
            view=self,
        )
        self.stop()

    async def on_timeout(self) -> None:
        self.confirmed = None
