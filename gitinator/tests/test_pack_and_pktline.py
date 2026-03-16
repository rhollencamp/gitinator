"""
Tests for pack.parse() and pktline.decode_stream().
"""

import hashlib
import struct
import zlib

from django.test import SimpleTestCase

from gitinator import pack, pktline
from gitinator.git import compute_sha
from gitinator.models import GitObject
from gitinator.pack import _apply_delta  # noqa: PLC2701
from gitinator.tests.factories import BLOB_SHA, COMMIT_SHA, TREE_SHA


class PackParseTest(SimpleTestCase):
    def _make_objects(self):
        """Build a list of mock objects for pack building/parsing."""

        class FakeObj:
            def __init__(self, type_, sha, data):
                self.type = type_
                self.sha = sha
                self.data = data

        return [
            FakeObj(GitObject.Type.BLOB, BLOB_SHA, b"hello world"),
            FakeObj(GitObject.Type.TREE, TREE_SHA, b"tree data"),
            FakeObj(GitObject.Type.COMMIT, COMMIT_SHA, b"commit data"),
        ]

    def test_parse_roundtrip(self):
        objects = self._make_objects()
        pack_data = pack.build(objects)
        parsed = pack.parse(pack_data)
        self.assertEqual(len(parsed), 3)
        types = [o["type"] for o in parsed]
        self.assertIn("blob", types)
        self.assertIn("tree", types)
        self.assertIn("commit", types)

    def test_parse_roundtrip_data_matches(self):
        objects = self._make_objects()
        pack_data = pack.build(objects)
        parsed = pack.parse(pack_data)
        parsed_by_type = {o["type"]: o["data"] for o in parsed}
        self.assertEqual(parsed_by_type["blob"], b"hello world")
        self.assertEqual(parsed_by_type["tree"], b"tree data")
        self.assertEqual(parsed_by_type["commit"], b"commit data")

    def test_parse_raises_for_invalid_magic(self):
        with self.assertRaises(ValueError):
            pack.parse(b"NOPE" + b"\x00" * 100)

    def test_parse_raises_for_bad_checksum(self):
        objects = self._make_objects()
        pack_data = pack.build(objects)
        # Corrupt the last byte of the checksum
        corrupted = pack_data[:-1] + bytes([pack_data[-1] ^ 0xFF])
        with self.assertRaises(ValueError):
            pack.parse(corrupted)

    def test_parse_ref_delta_with_base_lookup(self):
        """REF_DELTA objects are resolved via base_lookup when base is not in pack."""
        base_data = b"hello"
        base_type = "blob"
        base_sha_hex = compute_sha(base_type, base_data)
        base_sha_bytes = bytes.fromhex(base_sha_hex)

        # Delta: copy all 5 bytes from base, then insert b" world"
        # src_size=5, tgt_size=11, copy(offset=0, size=5), insert(6 bytes)
        delta = bytes([0x05, 0x0B, 0x90, 0x05, 0x06]) + b" world"
        # Verify _apply_delta produces the expected result before building the pack
        self.assertEqual(_apply_delta(base_data, delta), b"hello world")

        delta_size = len(delta)  # 11 fits in 4 bits
        type_size_byte = bytes([(7 << 4) | (delta_size & 0x0F)])
        compressed_delta = zlib.compress(delta)

        header = b"PACK" + struct.pack(">II", 2, 1)
        body = type_size_byte + base_sha_bytes + compressed_delta
        pack_data = header + body
        pack_data += hashlib.sha1(pack_data, usedforsecurity=False).digest()

        def base_lookup(sha):
            return (base_type, base_data) if sha == base_sha_hex else None

        parsed = pack.parse(pack_data, base_lookup=base_lookup)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["type"], "blob")
        self.assertEqual(parsed[0]["data"], b"hello world")

    def test_parse_raises_for_ofs_delta(self):
        """OFS_DELTA (type 6) objects are not yet supported and raise ValueError."""
        header = b"PACK" + struct.pack(">II", 2, 1)
        # type 6 = OFS_DELTA; encode type+size byte: (6 << 4) | 0 = 0x60
        body = bytes([0x60]) + zlib.compress(b"\x00")
        pack_data = header + body
        pack_data += hashlib.sha1(pack_data, usedforsecurity=False).digest()
        with self.assertRaises(ValueError):
            pack.parse(pack_data)

    def test_parse_ref_delta_raises_when_base_not_found(self):
        """REF_DELTA without a resolvable base raises ValueError."""
        base_sha_bytes = bytes.fromhex(compute_sha("blob", b"hello"))
        delta = bytes([0x05, 0x0B, 0x90, 0x05, 0x06]) + b" world"
        delta_size = len(delta)
        type_size_byte = bytes([(7 << 4) | (delta_size & 0x0F)])

        header = b"PACK" + struct.pack(">II", 2, 1)
        body = type_size_byte + base_sha_bytes + zlib.compress(delta)
        pack_data = header + body
        pack_data += hashlib.sha1(pack_data, usedforsecurity=False).digest()

        with self.assertRaises(ValueError):
            pack.parse(pack_data)  # no base_lookup provided


class PktlineDecodeStreamTest(SimpleTestCase):
    def test_returns_lines_before_flush(self):
        data = (
            pktline.encode(b"line one\n")
            + pktline.encode(b"line two\n")
            + pktline.flush()
        )
        lines, remaining = pktline.decode_stream(data)
        self.assertEqual(lines, [b"line one\n", b"line two\n"])
        self.assertEqual(remaining, b"")

    def test_returns_bytes_after_flush(self):
        data = pktline.encode(b"cmd\n") + pktline.flush() + b"PACK binary data"
        lines, remaining = pktline.decode_stream(data)
        self.assertEqual(lines, [b"cmd\n"])
        self.assertEqual(remaining, b"PACK binary data")

    def test_empty_stream(self):
        lines, remaining = pktline.decode_stream(pktline.flush())
        self.assertEqual(lines, [])
        self.assertEqual(remaining, b"")
