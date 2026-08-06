from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import Page


class RoleOut(BaseModel):
    id: int
    name: str
    description: str | None = None


class UserOut(BaseModel):
    id: int
    username: str
    email: EmailStr
    is_active: bool
    roles: list[RoleOut] = []


class UserListOut(Page):
    items: list[UserOut]


class UserCreateIn(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserStatusUpdateIn(BaseModel):
    is_active: bool


class UserSetRolesIn(BaseModel):
    role_ids: list[int] = Field(default_factory=list)


class UserBatchStatusIn(BaseModel):
    user_ids: list[int] = Field(min_length=1)
    is_active: bool


class UserBatchRolesIn(BaseModel):
    user_ids: list[int] = Field(min_length=1)
    role_ids: list[int] = Field(default_factory=list)
