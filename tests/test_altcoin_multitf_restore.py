from __future__ import annotations

import io
import tarfile
import unittest

from scripts.rebuild_altcoin_multitf_004 import FROZEN_ROSTER
from scripts.restore_altcoin_multitf_004 import safe_members


class AltcoinMultitfRestoreTests(unittest.TestCase):
    def _archive(self, name: str, *, kind: bytes = tarfile.REGTYPE) -> tarfile.TarFile:
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.size = 0
            archive.addfile(member)
        stream.seek(0)
        return tarfile.open(fileobj=stream, mode="r")

    def test_frozen_roster_is_exact_and_keeps_missing_symbol(self) -> None:
        self.assertEqual(len(FROZEN_ROSTER), 40)
        self.assertEqual(len(set(FROZEN_ROSTER)), 40)
        self.assertIn("BTWUSDT", FROZEN_ROSTER)
        self.assertNotIn("BTCUSDT", FROZEN_ROSTER)
        self.assertNotIn("ETHUSDT", FROZEN_ROSTER)

    def test_restore_rejects_path_traversal(self) -> None:
        with self._archive("altcoin-multitf-004/../escape") as archive:
            with self.assertRaises(RuntimeError):
                safe_members(archive)

    def test_restore_rejects_links(self) -> None:
        with self._archive("altcoin-multitf-004/link", kind=tarfile.SYMTYPE) as archive:
            with self.assertRaises(RuntimeError):
                safe_members(archive)

    def test_restore_accepts_dataset_members_only(self) -> None:
        with self._archive("altcoin-multitf-004/metadata/manifest.json") as archive:
            self.assertEqual(len(safe_members(archive)), 1)


if __name__ == "__main__":
    unittest.main()
