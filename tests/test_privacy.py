import base64
import sys
import types
import unittest
from unittest.mock import patch

from ruang_tumbuh.privacy import DataCipher, DataIntegrityError, rotate_sensitive_content


class RotationConnection:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, query, params=None):
        if query.startswith('SELECT to_regclass'):
            return type('Result', (), {'fetchone': lambda _self: (params[0] if params[0] in self.rows else None,)})()
        if query.startswith("SELECT "):
            table = query.split(" FROM ")[1]
            return type("Result", (), {"fetchall": lambda _self: ([self.rows[table]] if table in self.rows else [])})()
        table = query.split("UPDATE ")[1].split(" SET ")[0]
        self.rows[table] = (*self.rows[table][:-1], params[0])


class DataCipherTests(unittest.TestCase):
    def setUp(self):
        self.cipher = DataCipher(base64.urlsafe_b64encode(bytes(range(32))).decode())

    def test_text_and_json_round_trip_without_plaintext(self):
        text = "synthetic child growth note"
        sealed = self.cipher.seal(text, "events.payload")
        self.assertNotIn(text, sealed)
        self.assertEqual(self.cipher.open(sealed, "events.payload"), text)
        value = {"notes": text, "value": 6.4}
        self.assertEqual(self.cipher.open_json(self.cipher.seal_json(value, "events.payload"), "events.payload"), value)

    def test_context_and_ciphertext_tampering_are_rejected(self):
        sealed = self.cipher.seal("synthetic", "children.nickname")
        with self.assertRaises(DataIntegrityError):
            self.cipher.open(sealed, "families.name")
        tampered = sealed[:4] + ("A" if sealed[4] != "A" else "B") + sealed[5:]
        with self.assertRaises(DataIntegrityError):
            self.cipher.open(tampered, "children.nickname")

    def test_key_and_envelope_validation(self):
        for key in ("", "not-base64", base64.urlsafe_b64encode(b"short").decode()):
            with self.subTest(key=key), self.assertRaises(ValueError):
                DataCipher(key)
        with self.assertRaises(DataIntegrityError):
            self.cipher.open("plain text", "events.payload")

    def test_rotation_reseals_text_and_json_under_new_key(self):
        new_cipher = DataCipher(base64.urlsafe_b64encode(bytes(reversed(range(32)))).decode())
        rows = {
            "families": (7, self.cipher.seal("Synthetic family", "families.name")),
            "events": (8, self.cipher.seal_json({"note": "synthetic"}, "events.payload")),
        }
        psycopg = types.ModuleType("psycopg")
        psycopg_types = types.ModuleType("psycopg.types")
        json_module = types.ModuleType("psycopg.types.json")
        json_module.Jsonb = lambda value: value
        with patch.dict(sys.modules, {"psycopg": psycopg, "psycopg.types": psycopg_types,
                                      "psycopg.types.json": json_module}):
            rotate_sensitive_content(RotationConnection(rows), self.cipher, new_cipher)
        self.assertEqual(new_cipher.open(rows["families"][1], "families.name"), "Synthetic family")
        self.assertEqual(new_cipher.open_json(rows["events"][1], "events.payload"), {"note": "synthetic"})
        with self.assertRaises(DataIntegrityError):
            self.cipher.open(rows["families"][1], "families.name")


if __name__ == "__main__":
    unittest.main()

