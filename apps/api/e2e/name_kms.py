"""Test-only KMS boundary: opaque handles, no cloud credentials or real encryption.

Lives outside app/ and is injected only by tests/e2e.app. State lasts for the
test server's lifetime; never use this for real data or production persistence.
"""

from uuid import uuid4

import google_crc32c
from google.cloud import kms_v1


class FakeNameKms:
    def __init__(self):
        self.values = {}
        self.primary = 1
        self.disabled = set()
        self.unavailable = False
        self.decrypt_calls = 0

    def encrypt(self, *, request, retry, timeout):
        if self.unavailable:
            raise ValueError("test KMS unavailable")
        ciphertext = b"test-only:" + uuid4().bytes
        self.values[ciphertext] = (
            request["plaintext"],
            request["additional_authenticated_data"],
            self.primary,
        )
        return kms_v1.EncryptResponse(
            name=f"{request['name']}/cryptoKeyVersions/{self.primary}",
            ciphertext=ciphertext,
            ciphertext_crc32c=google_crc32c.value(ciphertext),
            verified_plaintext_crc32c=True,
            verified_additional_authenticated_data_crc32c=True,
        )

    def decrypt(self, *, request, retry, timeout):
        self.decrypt_calls += 1
        if self.unavailable:
            raise ValueError("test KMS unavailable")
        stored = self.values.get(request["ciphertext"])
        if (
            not stored
            or stored[1] != request["additional_authenticated_data"]
            or stored[2] in self.disabled
        ):
            raise ValueError("test authentication or version failure")
        return kms_v1.DecryptResponse(
            plaintext=stored[0], plaintext_crc32c=google_crc32c.value(stored[0])
        )
