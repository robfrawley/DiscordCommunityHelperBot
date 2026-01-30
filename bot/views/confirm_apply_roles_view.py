import discord

class ConfirmApplyRolesView(discord.ui.View):
    def __init__(self, requester_id: int, *, timeout: float = 60.0) -> None:
        super().__init__(timeout=timeout)
        self.requester_id = requester_id
        self.confirmed: bool | None = None  # True/False when decided, None if timed out

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Only the command invoker can confirm/cancel
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "Only the user who ran this command can confirm or cancel.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.confirmed = True
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        await interaction.response.edit_message(content="✅ Confirmed. Starting role assignment...", view=self)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.confirmed = False
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        await interaction.response.edit_message(content="❌ Cancelled. No roles were changed.", view=self)
        self.stop()

    async def on_timeout(self) -> None:
        # Don't assume we can edit the message here reliably without storing it;
        # util_apply_roles will handle timeout messaging after wait().
        self.confirmed = None
