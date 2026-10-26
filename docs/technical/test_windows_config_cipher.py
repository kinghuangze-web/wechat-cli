"""Focused regression checks for the PR #22 Windows extraction path."""

import hashlib
import hmac
import struct
import unittest
from unittest.mock import patch

from wechat_cli.keys import scanner_windows as scanner
from wechat_cli.keys.common import verify_enc_key


def signed_page(key, salt):
    page = bytearray((index * 17) % 256 for index in range(4096))
    page[:16] = salt
    mac_key = hashlib.pbkdf2_hmac(
        "sha512", key, bytes(value ^ 0x3A for value in salt), 2, dklen=32
    )
    page[-64:] = hmac.new(
        mac_key, bytes(page[16:4032]) + struct.pack("<I", 1), hashlib.sha512
    ).digest()
    return bytes(page)


class WindowsConfigCipherTests(unittest.TestCase):
    def setUp(self):
        self.key = bytes(range(32))
        self.salt = bytes(range(32, 48))
        self.literal = b"x'" + self.key.hex().encode() + self.salt.hex().encode() + b"'"
        self.blob = scanner._xor_repeat(self.literal, scanner.WINDOWS_CONFIG_XOR_MASK)
        self.page = signed_page(self.key, self.salt)

    def test_xor_candidate_recovers_key_and_embedded_salt(self):
        self.assertEqual(
            scanner._windows_v411_config_key_candidates(self.blob),
            [(self.key.hex(), self.salt.hex())],
        )

    def test_invalid_blob_is_rejected(self):
        self.assertEqual(scanner._windows_v411_config_key_candidates(b""), [])
        self.assertEqual(scanner._windows_v411_config_key_candidates(b"a" * 1025), [])
        self.assertEqual(scanner._windows_v411_config_key_candidates(b"not-a-key"), [])

    def test_hmac_accepts_valid_page_and_rejects_corruption(self):
        self.assertTrue(verify_enc_key(self.key, self.page))
        corrupted = bytearray(self.page)
        corrupted[100] ^= 1
        self.assertFalse(verify_enc_key(self.key, bytes(corrupted)))
        self.assertFalse(verify_enc_key(bytes(reversed(self.key)), self.page))

    def test_config_pointer_walk_only_accepts_verified_candidate(self):
        base = 0x10000
        memory = bytearray(0x4000)

        def put(address, data):
            memory[address - base:address - base + len(data)] = data

        def read(_handle, address, size):
            offset = address - base
            if offset < 0 or offset + size > len(memory):
                return None
            return bytes(memory[offset:offset + size])

        put(base + 0x100, scanner.WINDOWS_CONFIG_CIPHER_NAME)
        put(base + 0x1010, struct.pack("<QQ", base + 0x100, len(scanner.WINDOWS_CONFIG_CIPHER_NAME)))
        put(base + 0x1028, struct.pack("<Q", base + 0x2000))
        put(base + 0x2090, struct.pack("<QQ", base + 0x2800, len(self.blob)))
        put(base + 0x2800, self.blob)
        rel = "message\\message_0.db"
        db_files = [(rel, "unused", 4096, self.salt.hex(), self.page)]
        salts = {self.salt.hex(): [rel]}
        key_map = {}
        remaining = set(salts)
        with patch.object(scanner, "_read_mem", side_effect=read):
            matched = scanner._scan_config_cipher(
                1, None, [(base, len(memory))], db_files, salts, key_map, remaining
            )
        self.assertEqual(matched, 1)
        self.assertEqual(key_map, {self.salt.hex(): self.key.hex()})
        self.assertEqual(remaining, set())

        key_map.clear()
        remaining = set(salts)
        invalid_files = [(rel, "unused", 4096, self.salt.hex(), b"\0" * 4096)]
        with patch.object(scanner, "_read_mem", side_effect=read):
            matched = scanner._scan_config_cipher(
                1, None, [(base, len(memory))], invalid_files, salts, key_map, remaining
            )
        self.assertEqual(matched, 0)
        self.assertEqual(key_map, {})
        self.assertEqual(remaining, set(salts))


if __name__ == "__main__":
    unittest.main()
