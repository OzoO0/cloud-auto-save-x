from pydantic import BaseModel, EmailStr


class SetupStatusOut(BaseModel):
    initialized: bool


class SetupAdminIn(BaseModel):
    username: str
    email: EmailStr
    password: str

