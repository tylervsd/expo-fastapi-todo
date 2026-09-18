"""Phase 22 synthetic-fixture lab. Real cryptography stays in gcloud/Cloud KMS."""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

FIXTURE = b'{"synthetic":true,"customer_id":"lab-001","name":"Example Customer","email":"customer@example.test"}\n'
VERSION = re.compile(
    r"projects/(?P<project>[a-z][a-z0-9-]{4,28}[a-z0-9])/"
    r"locations/(?P<location>[a-z]+-[a-z]+[0-9]+)/"
    r"keyRings/phase22-lab/cryptoKeys/synthetic-pii/"
    r"cryptoKeyVersions/(?P<version>[1-9][0-9]*)"
)


def scope(key_version: str, identity: str) -> dict:
    match = VERSION.fullmatch(key_version) if isinstance(key_version, str) else None
    if not match:
        raise ValueError("Use a full phase22-lab/synthetic-pii key-version resource.")
    parts = match.groupdict()
    allowed = {
        f"phase22-{role}@{parts['project']}.iam.gserviceaccount.com"
        for role in ("reader", "writer")
    }
    if identity not in allowed:
        raise ValueError("Use a lab service account in the key's project.")
    return parts


def crypt(operation: str, metadata: dict, identity: str, payload: bytes) -> bytes:
    parts = scope(metadata["key_version"], identity)
    with tempfile.TemporaryDirectory(prefix="phase22-") as directory:
        plain = Path(directory) / "plain"
        cipher = Path(directory) / "cipher"
        aad = Path(directory) / "aad"
        aad.write_bytes(
            json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()
        )
        (plain if operation == "encrypt" else cipher).write_bytes(payload)
        args = [
            "gcloud",
            "kms",
            operation,
            f"--project={parts['project']}",
            f"--location={parts['location']}",
            "--keyring=phase22-lab",
            "--key=synthetic-pii",
            f"--impersonate-service-account={identity}",
            f"--plaintext-file={plain}",
            f"--ciphertext-file={cipher}",
            f"--additional-authenticated-data-file={aad}",
            "--quiet",
            "--verbosity=error",
            "--no-log-http",
        ]
        if operation == "encrypt":
            args.append(f"--version={parts['version']}")
        try:
            subprocess.run(args, check=True, capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(
                f"gcloud {operation} failed; inspect identity, KMS state and audit logs."
            ) from exc
        result = (cipher if operation == "encrypt" else plain).read_bytes()
        if not result or len(result) > 16384:
            raise RuntimeError("Unexpected KMS output size.")
        return result


def seal(key_version: str, identity: str, bundle: Path) -> None:
    scope(key_version, identity)
    if bundle.exists() or bundle.is_symlink():
        raise FileExistsError("Bundle already exists; choose a new path.")
    metadata = {"schema": 1, "key_version": key_version}
    ciphertext = crypt("encrypt", metadata, identity, FIXTURE)
    document = {**metadata, "ciphertext": base64.b64encode(ciphertext).decode("ascii")}
    # Publish only a complete file, atomically and without overwriting old evidence.
    with tempfile.NamedTemporaryFile(
        mode="w", dir=bundle.parent, encoding="utf-8"
    ) as output:
        json.dump(document, output, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
        os.link(output.name, bundle)


def check(identity: str, bundle: Path) -> None:
    with bundle.open("rb") as source:
        raw = source.read(32769)
    if len(raw) > 32768:
        raise ValueError("Bundle exceeds 32 KiB.")
    document = json.loads(raw)
    if (
        not isinstance(document, dict)
        or set(document) != {"schema", "key_version", "ciphertext"}
        or type(document["schema"]) is not int
        or document["schema"] != 1
        or not isinstance(document["ciphertext"], str)
    ):
        raise ValueError("Invalid phase 22 bundle format.")
    scope(document["key_version"], identity)
    ciphertext = base64.b64decode(document["ciphertext"], validate=True)
    if not ciphertext or len(ciphertext) > 16384:
        raise ValueError("Invalid ciphertext size.")
    metadata = {"schema": document["schema"], "key_version": document["key_version"]}
    if crypt("decrypt", metadata, identity, ciphertext) != FIXTURE:
        raise RuntimeError("Recovered plaintext does not match the synthetic fixture.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("seal", "check"):
        command = commands.add_parser(name)
        command.add_argument("--identity", required=True)
        command.add_argument("--bundle", required=True, type=Path)
        if name == "seal":
            command.add_argument("--key-version", required=True)
    args = parser.parse_args()
    try:
        if args.command == "seal":
            seal(args.key_version, args.identity, args.bundle)
        else:
            check(args.identity, args.bundle)
    except (OSError, ValueError, RuntimeError) as exc:
        # Do not echo input JSON, recovered plaintext, or gcloud stderr.
        print(
            f"Phase 22 {args.command} failed ({type(exc).__name__}). See Guide 22.",
            file=sys.stderr,
        )
        return 1
    print(f"Phase 22 {args.command} succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
