"""API so'rov modellari (uzunlik chegaralari bilan: katta yuklama va bazaga ortiqcha yozishdan himoya)."""
from pydantic import BaseModel, Field


class RegisterIn(BaseModel):
    username: str = Field(max_length=64)
    nickname: str = Field(max_length=64)
    password: str = Field(max_length=128)         # E2EE: brauzer parolidan hosil qilgan kirish kaliti (hex), asl parol EMAS
    e2ee: dict | None = None                       # {ecdh_pub, sign_pub, key_blob, kdf_iter}


class KdfIn(BaseModel):
    username: str = Field(max_length=64)


class LoginIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=128)
