"""
Tests for pack.parse() and pktline.decode_stream().
"""

from django.test import SimpleTestCase

from gitinator import pack, pktline
from gitinator.models import GitObject
from gitinator.tests.factories import BLOB_SHA, COMMIT_SHA, TREE_SHA, make_repo_fixture


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

    def test_parse_raises_for_delta_objects(self):
        # Craft a minimal pack with a type-6 (OFS_DELTA) object header
        import struct
        import zlib

        # Build a pack header for 1 object
        header = b"PACK" + struct.pack(">II", 2, 1)
        # type 6 = OFS_DELTA; encode type+size byte: (6 << 4) | 0 = 0x60
        obj_header = bytes([0x60])
        obj_data = zlib.compress(b"\x00")
        body = obj_header + obj_data
        import hashlib

        pack_data = header + body
        pack_data += hashlib.sha1(pack_data, usedforsecurity=False).digest()
        with self.assertRaises(ValueError):
            pack.parse(pack_data)


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
