from pydantic import BaseModel


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class MeOut(BaseModel):
    id: int
    username: str
    email: str
    roles: list[str]
    permissions: list[str]


class LoginOut(TokenOut):
    user: MeOut
