from __future__ import annotations

import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.build_altcoin_multitf_005 import CONFIG_HASH, PROTOCOL_ID, deterministic_archive, fetch_retry, load_state, new_state, save_state, verified
from scripts.rebuild_altcoin_multitf_004 import FROZEN_ROSTER
from scripts.restore_altcoin_multitf_005 import safe_members
from scripts.verify_altcoin_multitf_005_blob import verify as verify_blob


class AltcoinMultitf005Tests(unittest.TestCase):
    def test_frozen_roster_is_exact(self) -> None:
        self.assertEqual(len(FROZEN_ROSTER), 40); self.assertEqual(len(set(FROZEN_ROSTER)), 40)
        self.assertIn("BTWUSDT", FROZEN_ROSTER); self.assertNotIn("BTCUSDT", FROZEN_ROSTER)

    def test_checkpoint_roundtrip_and_incompatibility(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory); state = new_state(); state["completed"]["prepare"] = True; save_state(workspace, state)
            self.assertEqual(load_state(workspace)["config_hash"], CONFIG_HASH)
            path = workspace / "checkpoint" / "state.json"; broken = json.loads(path.read_text()); broken["config_hash"] = "wrong"; path.write_text(json.dumps(broken))
            with self.assertRaises(RuntimeError): load_state(workspace)

    def test_verified_resume_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "part.zip"; path.write_bytes(b"valid")
            import hashlib
            record = {"size": 5, "sha256": hashlib.sha256(b"valid").hexdigest()}
            self.assertTrue(verified(path, record)); path.write_bytes(b"other"); self.assertFalse(verified(path, record))

    def test_archive_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); dataset = root / "altcoin-multitf-005"; dataset.mkdir(); (dataset / "a.txt").write_text("same")
            first, second = root / "one.tar.gz", root / "two.tar.gz"
            self.assertEqual(deterministic_archive(dataset, first)["sha256"], deterministic_archive(dataset, second)["sha256"])

    def _archive(self, name: str, kind: bytes = tarfile.REGTYPE) -> tarfile.TarFile:
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            member = tarfile.TarInfo(name); member.type = kind; member.size = 0; archive.addfile(member)
        stream.seek(0); return tarfile.open(fileobj=stream, mode="r")

    def test_restore_rejects_traversal_and_links(self) -> None:
        with self._archive("altcoin-multitf-005/../escape") as archive:
            with self.assertRaises(RuntimeError): safe_members(archive)
        with self._archive("altcoin-multitf-005/link", tarfile.SYMTYPE) as archive:
            with self.assertRaises(RuntimeError): safe_members(archive)

    def test_anonymous_verification_uses_no_authorization(self) -> None:
        payload = b"archive"
        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *_): self.close()
        with tempfile.TemporaryDirectory() as directory:
            import hashlib
            metadata = Path(directory) / "blob.json"
            metadata.write_text(json.dumps({"protocol_id": PROTOCOL_ID, "access": "public", "url": "https://example.test/a", "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}))
            def open_request(request, timeout):
                self.assertIsNone(request.get_header("Authorization")); return Response(payload)
            with patch("urllib.request.urlopen", side_effect=open_request): self.assertEqual(verify_blob(metadata)["anonymous_verification"], "PASS")


if __name__ == "__main__": unittest.main()
