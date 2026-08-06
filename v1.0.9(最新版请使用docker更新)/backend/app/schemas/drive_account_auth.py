from __future__ import annotations

from pydantic import BaseModel, Field


class DriveAccountCaptchaSubmitIn(BaseModel):
    code: str = Field(min_length=1, max_length=16)


class DriveAccountSmsSubmitIn(BaseModel):
    code: str = Field(min_length=1, max_length=16)

