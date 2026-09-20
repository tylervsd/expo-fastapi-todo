"""Exercise bundle/filesystem behavior; only the external gcloud boundary is fake."""

import base64
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "kms_lab.py"
VERSION = (
    "projects/example-phase22-project/locations/us-west1/"
    "keyRings/phase22-lab/cryptoKeys/synthetic-pii/cryptoKeyVersions/1"
)
READER = "phase22-reader@example-phase22-project.iam.gserviceaccount.com"
WRITER = "phase22-writer@example-phase22-project.iam.gserviceaccount.com"


class KmsLabTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.exists(), "phase 22 runner is not implemented")
        spec = importlib.util.spec_from_file_location("kms_lab", SCRIPT)
        self.lab = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.lab)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.bundle = Path(directory.name) / "fixture.json"
        self.paths = []
        self.sealed = {}

    def cloud(self, args, **kwargs):
        self.assertEqual(args[:2], ["gcloud", "kms"])
        self.assertEqual(kwargs["timeout"], 60)
        self.assertTrue(kwargs["check"])
        self.assertNotIn("--skip-integrity-verification", args)
        flags = dict(a[2:].split("=", 1) for a in args[3:] if "=" in a)
        self.assertEqual(flags["project"], "example-phase22-project")
        self.assertEqual(flags["location"], "us-west1")
        self.assertEqual(flags["keyring"], "phase22-lab")
        self.assertEqual(flags["key"], "synthetic-pii")
        plain = Path(flags["plaintext-file"])
        cipher = Path(flags["ciphertext-file"])
        aad = Path(flags["additional-authenticated-data-file"])
        self.paths.extend([plain, cipher, aad])
        if args[2] == "encrypt":
            self.assertEqual(flags["version"], "1")
            ciphertext = b"external KMS ciphertext"
            self.sealed[ciphertext] = (aad.read_bytes(), plain.read_bytes())
            cipher.write_bytes(ciphertext)
        else:
            self.assertNotIn("version", flags)  # KMS decrypt chooses the version.
            stored = self.sealed.get(cipher.read_bytes())
            if (
                flags["impersonate-service-account"] == WRITER
                or not stored
                or stored[0] != aad.read_bytes()
            ):
                raise subprocess.CalledProcessError(
                    1, args, stderr="sensitive raw error"
                )
            plain.write_bytes(stored[1])
        return subprocess.CompletedProcess(args, 0)

    def test_roundtrip_private_bundle_and_temp_cleanup(self):
        with patch.object(self.lab.subprocess, "run", side_effect=self.cloud):
            self.lab.seal(VERSION, READER, self.bundle)
            self.lab.check(READER, self.bundle)
        document = json.loads(self.bundle.read_text())
        self.assertEqual(set(document), {"schema", "key_version", "ciphertext"})
        self.assertEqual(document["key_version"], VERSION)
        self.assertNotIn("example.test", self.bundle.read_text())
        self.assertEqual(self.bundle.stat().st_mode & 0o777, 0o600)
        self.assertTrue(all(not p.exists() for p in self.paths))

    def test_denied_and_tampered_bundles_never_pass(self):
        with patch.object(self.lab.subprocess, "run", side_effect=self.cloud):
            self.lab.seal(VERSION, READER, self.bundle)
            original = self.bundle.read_text()
            with self.assertRaisesRegex(RuntimeError, "gcloud") as failure:
                self.lab.check(WRITER, self.bundle)
            self.assertNotIn("sensitive", str(failure.exception))
            for field, value in (
                ("key_version", VERSION[:-1] + "2"),
                ("ciphertext", base64.b64encode(b"tampered").decode()),
            ):
                document = json.loads(original)
                document[field] = value
                self.bundle.write_text(json.dumps(document))
                with self.assertRaises(RuntimeError):
                    self.lab.check(READER, self.bundle)
        self.assertTrue(all(not p.exists() for p in self.paths))

    def test_wrong_recovered_plaintext_fails(self):
        with patch.object(self.lab.subprocess, "run", side_effect=self.cloud):
            self.lab.seal(VERSION, READER, self.bundle)
            aad, _ = self.sealed[b"external KMS ciphertext"]
            self.sealed[b"external KMS ciphertext"] = (aad, b"wrong customer")
            with self.assertRaisesRegex(RuntimeError, "fixture"):
                self.lab.check(READER, self.bundle)

    def test_invalid_input_stops_before_cloud(self):
        with patch.object(self.lab.subprocess, "run") as cloud:
            for version in (
                VERSION.replace("phase22-lab", "production"),
                VERSION[:-1] + "0",
                VERSION + "/extra",
            ):
                with self.assertRaises(ValueError):
                    self.lab.seal(version, READER, self.bundle)
            with self.assertRaises(ValueError):
                self.lab.seal(
                    VERSION,
                    READER.replace("example-phase22-project", "other-project"),
                    self.bundle,
                )
            for document in (
                [],
                {},
                {"schema": True, "key_version": VERSION, "ciphertext": "YQ=="},
                {"schema": 2, "key_version": VERSION, "ciphertext": "YQ=="},
                {"schema": 1, "key_version": VERSION, "ciphertext": "!"},
                {"schema": 1, "key_version": VERSION, "ciphertext": ""},
                {"schema": 1, "key_version": VERSION, "ciphertext": "YQ==", "extra": 1},
                {
                    "schema": 1,
                    "key_version": VERSION,
                    "ciphertext": base64.b64encode(b"x" * 16385).decode(),
                },
            ):
                self.bundle.write_text(json.dumps(document))
                with self.assertRaises(ValueError):
                    self.lab.check(READER, self.bundle)
            self.bundle.write_bytes(b" " * 32769)
            with self.assertRaises(ValueError):
                self.lab.check(READER, self.bundle)
            cloud.assert_not_called()

    def test_no_clobber_file_or_symlink(self):
        self.bundle.write_bytes(b"keep me")
        with patch.object(self.lab.subprocess, "run") as cloud:
            with self.assertRaises(FileExistsError):
                self.lab.seal(VERSION, READER, self.bundle)
            self.assertEqual(self.bundle.read_bytes(), b"keep me")
            link = self.bundle.with_suffix(".link")
            link.symlink_to(self.bundle)
            with self.assertRaises(FileExistsError):
                self.lab.seal(VERSION, READER, link)
            cloud.assert_not_called()

    def test_cloud_failure_does_not_leave_bundle(self):
        for error in (
            subprocess.TimeoutExpired("gcloud", 60),
            subprocess.CalledProcessError(1, "gcloud"),
        ):
            with (
                patch.object(self.lab.subprocess, "run", side_effect=error),
                self.assertRaises(RuntimeError),
            ):
                self.lab.seal(VERSION, READER, self.bundle)
            self.assertFalse(self.bundle.exists())

    def test_concurrent_output_is_not_overwritten(self):
        def racing_cloud(args, **kwargs):
            result = self.cloud(args, **kwargs)
            self.bundle.write_bytes(b"other run's evidence")
            return result

        with (
            patch.object(self.lab.subprocess, "run", side_effect=racing_cloud),
            self.assertRaises(FileExistsError),
        ):
            self.lab.seal(VERSION, READER, self.bundle)
        self.assertEqual(self.bundle.read_bytes(), b"other run's evidence")
        self.assertEqual(list(self.bundle.parent.iterdir()), [self.bundle])

    def test_failed_publication_removes_partial_file(self):
        with (
            patch.object(self.lab.subprocess, "run", side_effect=self.cloud),
            patch.object(self.lab.os, "fsync", side_effect=OSError("disk failure")),
            self.assertRaises(OSError),
        ):
            self.lab.seal(VERSION, READER, self.bundle)
        self.assertEqual(list(self.bundle.parent.iterdir()), [])
        self.assertTrue(all(not p.exists() for p in self.paths))

    def test_cli_help_is_offline_and_bad_input_fails(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"], capture_output=True, check=False
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn(b"seal", result.stdout)
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "seal",
                "--key-version",
                "invalid",
                "--identity",
                READER,
                "--bundle",
                str(self.bundle),
            ],
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(b"Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
