"""Credential registration, resolution and revocation tests."""
import tempfile
import unittest
from pathlib import Path
from read_identity import ReadIdentity

class ReadIdentityTests(unittest.TestCase):
    def test_distinct_revocable_actor_tokens(self):
        with tempfile.TemporaryDirectory() as folder:
            registry = ReadIdentity(Path(folder) / "tokens.sqlite")
            alice = registry.issue("alice")
            bob = registry.issue("bob")
            self.assertNotEqual(alice, bob)
            self.assertEqual(registry.resolve(alice), "alice")
            self.assertEqual(registry.resolve(bob), "bob")
            registry.revoke(alice)
            with self.assertRaises(PermissionError):
                registry.resolve(alice)
            self.assertEqual(registry.resolve(bob), "bob")
            with self.assertRaises(PermissionError):
                registry.resolve("not-a-real-token")
            with self.assertRaises(ValueError):
                registry.issue("")

if __name__ == "__main__":
    unittest.main()
