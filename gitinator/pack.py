"""
Git PACK file building.

Reference: https://git-scm.com/docs/pack-format
"""

import struct
import zlib
from hashlib import sha1

_TYPE_MAP = {
    "commit": 1,
    "tree": 2,
    "blob": 3,
    "tag": 4,
}


def _encode_type_size(obj_type, size):
    """Encode object type and uncompressed size as variable-length header bytes."""
    result = []
    b = (obj_type << 4) | (size & 0x0F)
    size >>= 4
    while size > 0:
        result.append(b | 0x80)
        b = size & 0x7F
        size >>= 7
    result.append(b)
    return bytes(result)


def _encode_object(git_object):
    obj_type = _TYPE_MAP[git_object.type]
    data = bytes(git_object.data)
    header = _encode_type_size(obj_type, len(data))
    return header + zlib.compress(data)


def build(objects):
    """Build a PACK file from a list of GitObject instances."""
    pack_header = b"PACK" + struct.pack(">II", 2, len(objects))
    pack_body = b"".join(_encode_object(obj) for obj in objects)
    pack_data = pack_header + pack_body
    return pack_data + sha1(pack_data, usedforsecurity=False).digest()


_TYPE_MAP_REVERSE = {v: k for k, v in _TYPE_MAP.items()}
_DELTA_TYPES = {6, 7}  # OFS_DELTA and REF_DELTA


def _decode_type_size(data: bytes, offset: int) -> tuple[int, int, int]:
    """
    Decode a variable-length type+size header at the given offset.

    Returns (obj_type, size, new_offset).
    The first byte encodes type in bits 6-4 and the low 4 bits of size.
    Subsequent bytes (if MSB set) encode more size bits.
    """
    b = data[offset]
    offset += 1
    obj_type = (b >> 4) & 0x07
    size = b & 0x0F
    shift = 4
    while b & 0x80:
        b = data[offset]
        offset += 1
        size |= (b & 0x7F) << shift
        shift += 7
    return obj_type, size, offset


def parse(data: bytes) -> list[dict]:
    """
    Parse a PACK file into a list of objects.

    Each object is a dict with 'type' (str) and 'data' (bytes) keys.
    Only non-delta object types (commit, tree, blob, tag) are supported.
    Raises ValueError for invalid PACK data or unsupported delta objects.
    """
    if len(data) < 32:
        raise ValueError("PACK data too short")
    if data[:4] != b"PACK":
        raise ValueError("Invalid PACK magic bytes")
    version = struct.unpack(">I", data[4:8])[0]
    if version != 2:
        raise ValueError(f"Unsupported PACK version: {version}")
    expected_checksum = sha1(data[:-20], usedforsecurity=False).digest()
    if data[-20:] != expected_checksum:
        raise ValueError("PACK checksum mismatch")
    count = struct.unpack(">I", data[8:12])[0]

    objects = []
    offset = 12
    for _ in range(count):
        obj_type, _size, offset = _decode_type_size(data, offset)
        if obj_type in _DELTA_TYPES:
            raise ValueError(f"Delta objects (type {obj_type}) are not supported")
        if obj_type not in _TYPE_MAP_REVERSE:
            raise ValueError(f"Unknown object type: {obj_type}")
        # Decompress zlib data starting at offset
        decompressor = zlib.decompressobj()
        decompressed = decompressor.decompress(data[offset:])
        # Advance offset by the number of compressed bytes consumed
        offset += len(data[offset:]) - len(decompressor.unused_data)
        objects.append({"type": _TYPE_MAP_REVERSE[obj_type], "data": decompressed})

    return objects
