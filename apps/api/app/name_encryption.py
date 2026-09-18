"""Direct KMS encryption for the small, non-searchable user name field."""

import re
import unicodedata
from uuid import UUID

import google_crc32c
from google.api_core.exceptions import GoogleAPIError
from google.auth.exceptions import GoogleAuthError
from google.cloud import kms_v1

KEY_PATTERN = re.compile(
    r"projects/[a-z][a-z0-9-]{4,28}[a-z0-9]/locations/[a-z0-9-]+/"
    r"keyRings/[a-zA-Z0-9_-]+/cryptoKeys/[a-zA-Z0-9_-]+"
)


class NameUnavailable(RuntimeError):
    """Safe failure; never include plaintext, ciphertext or provider errors."""


def validate_key(key: str) -> str:
    if not KEY_PATTERN.fullmatch(key):
        raise ValueError("REAL_NAME_KMS_KEY must be a full logical KMS key resource.")
    return key


def normalize_name(name: str) -> str:
    if not 1 <= len(name.strip()) <= 100 or any(
        unicodedata.category(char) in {"Cc", "Cs", "Zl", "Zp"} for char in name
    ):
        raise ValueError("Name must contain 1–100 characters without controls.")
    return name.strip()


class NameCipher:
    def __init__(self, key: str, *, client=None):
        self.key = validate_key(key)
        self.client = (
            client if client is not None else kms_v1.KeyManagementServiceClient()
        )

    def encrypt(self, owner: UUID, name: str) -> bytes:
        plaintext = normalize_name(name).encode("utf-8")
        aad = f"fullstack:users:real_name:v1:{owner}".encode("ascii")
        try:
            result = self.client.encrypt(
                request={
                    "name": self.key,
                    "plaintext": plaintext,
                    "plaintext_crc32c": google_crc32c.value(plaintext),
                    "additional_authenticated_data": aad,
                    "additional_authenticated_data_crc32c": google_crc32c.value(aad),
                },
                retry=None,
                timeout=3,
            )
            if (
                not result.verified_plaintext_crc32c
                or not result.verified_additional_authenticated_data_crc32c
                or not result.ciphertext
                or result.ciphertext_crc32c != google_crc32c.value(result.ciphertext)
                or not result.name.startswith(self.key + "/cryptoKeyVersions/")
            ):
                raise ValueError("KMS integrity check failed")
            return bytes(result.ciphertext)
        except (GoogleAPIError, GoogleAuthError, ValueError) as exc:
            raise NameUnavailable("Name encryption unavailable.") from exc

    def decrypt(self, owner: UUID, ciphertext: bytes) -> str:
        aad = f"fullstack:users:real_name:v1:{owner}".encode("ascii")
        try:
            result = self.client.decrypt(
                request={
                    "name": self.key,
                    "ciphertext": ciphertext,
                    "ciphertext_crc32c": google_crc32c.value(ciphertext),
                    "additional_authenticated_data": aad,
                    "additional_authenticated_data_crc32c": google_crc32c.value(aad),
                },
                retry=None,
                timeout=3,
            )
            if result.plaintext_crc32c != google_crc32c.value(result.plaintext):
                raise ValueError("KMS integrity check failed")
            return normalize_name(result.plaintext.decode("utf-8"))
        except (GoogleAPIError, GoogleAuthError, ValueError) as exc:
            raise NameUnavailable("Name decryption unavailable.") from exc
