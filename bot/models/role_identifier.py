from dataclasses import dataclass

from disnake import Role


@dataclass(frozen=True, slots=True)
class RoleIdentifier:
    id: int

    def mention(self) -> str:
        return f"<@&{self.id}>"

    def __str__(self) -> str:
        return str(self.id)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, (Role, RoleIdentifier)):
            return self.id == other.id

        if isinstance(other, int):
            return self.id == other

        if isinstance(other, str):
            return str(self.id) == other

        return NotImplemented
