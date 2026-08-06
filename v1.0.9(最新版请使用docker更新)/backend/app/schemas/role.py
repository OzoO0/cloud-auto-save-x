from pydantic import BaseModel, Field


class PermissionOut(BaseModel):
    id: int
    code: str
    name: str
    description: str | None = None


class RoleOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    permissions: list[PermissionOut] = []


class RoleCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    description: str | None = Field(default=None, max_length=255)


class RoleUpdateIn(BaseModel):
    description: str | None = Field(default=None, max_length=255)


class RoleSetPermissionsIn(BaseModel):
    permission_ids: list[int] = Field(default_factory=list)
