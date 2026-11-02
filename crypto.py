import os
from cryptography.fernet import Fernet

_k = os.environ.get("SESSION_KEY")
_f = Fernet(_k.encode()) if _k else None


def enc(s: str) -> str:
    return _f.encrypt(s.encode()).decode() if _f else s


def dec(s: str) -> str:
    return _f.decrypt(s.encode()).decode() if _f else s
