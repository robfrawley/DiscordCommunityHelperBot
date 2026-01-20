from discord import Role
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RoleIdentifier:
    id: int

    def __str__(self) -> str:
        return str(self.id)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Role) or isinstance(other, RoleIdentifier):
            return self.id == other.id

        if isinstance(other, int):
            return self.id == other

        if isinstance(other, str):
            return str(self.id) == other

        return NotImplemented
