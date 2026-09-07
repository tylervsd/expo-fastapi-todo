from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_password_hasher = PasswordHasher()

# Valid hash of an unused password. Verifying unknown-user logins against it
# keeps response latency uniform so timing does not reveal whether a username
# exists (the 401 body is identical either way).
DUMMY_PASSWORD_HASH = _password_hasher.hash("no-such-user")


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
