"""
Git PACK file building and parsing.

Reference: https://git-scm.com/docs/pack-format
"""

import struct
import zlib
from hashlib import sha1

from gitinator.git import compute_sha

_TYPE_MAP = {
    "commit": 1,
    "tree": 2,
    "blob": 3,
    "tag": 4,
}
_TYPE_MAP_REVERSE = {v: k for k, v in _TYPE_MAP.items()}
_OFS_DELTA = 6
_REF_DELTA = 7


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


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    """Read a variable-length integer (MSB continuation).

    Returns (value, new_offset).
    """
    result = 0
    shift = 0
    while True:
        b = data[offset]
        offset += 1
        result |= (b & 0x7F) << shift
        shift += 7
        if not (b & 0x80):
            break
    return result, offset


def _apply_delta(base: bytes, delta: bytes) -> bytes:
    """Apply a binary delta to base data, returning the reconstructed object data."""
    pos = 0
    _src_size, pos = _read_varint(delta, pos)
    _tgt_size, pos = _read_varint(delta, pos)

    if len(base) != _src_size:
        raise ValueError(
            f"Delta source size mismatch: expected {_src_size}, got {len(base)}"
        )

    result = bytearray()
    while pos < len(delta):
        cmd = delta[pos]
        pos += 1
        if cmd & 0x80:
            # Copy instruction: copy bytes from base into result.
            # Bits 0-3 indicate which offset bytes follow; bits 4-6 indicate size bytes.
            copy_offset = 0
            copy_size = 0
            if cmd & 0x01:
                copy_offset |= delta[pos]
                pos += 1
            if cmd & 0x02:
                copy_offset |= delta[pos] << 8
                pos += 1
            if cmd & 0x04:
                copy_offset |= delta[pos] << 16
                pos += 1
            if cmd & 0x08:
                copy_offset |= delta[pos] << 24
                pos += 1
            if cmd & 0x10:
                copy_size |= delta[pos]
                pos += 1
            if cmd & 0x20:
                copy_size |= delta[pos] << 8
                pos += 1
            if cmd & 0x40:
                copy_size |= delta[pos] << 16
                pos += 1
            if copy_size == 0:
                copy_size = 0x10000
            result.extend(base[copy_offset : copy_offset + copy_size])
        elif cmd:
            # Insert instruction: copy next `cmd` bytes from delta stream into result.
            result.extend(delta[pos : pos + cmd])
            pos += cmd
        else:
            raise ValueError("Invalid delta instruction: reserved 0x00 byte")

    if len(result) != _tgt_size:
        raise ValueError(
            f"Delta target size mismatch: expected {_tgt_size}, got {len(result)}"
        )
    return bytes(result)


def parse(data: bytes, base_lookup=None) -> list[dict]:
    """
    Parse a PACK file into a list of objects.

    Each object is a dict with 'type' (str), 'data' (bytes), and 'sha' (str) keys.
    Supports REF_DELTA (type 7) delta-compressed objects. OFS_DELTA (type 6) is not
    yet supported and will raise ValueError.

    base_lookup: optional callable(sha: str) -> tuple[str, bytes] | None
        Called when a REF_DELTA base object is not present in the pack itself.
        Should return (obj_type, obj_data) or None if not found.
    Raises ValueError for invalid PACK data or unresolvable delta objects.
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

    raw_objects = []
    offset = 12

    for _ in range(count):
        obj_start = offset
        obj_type, _size, offset = _decode_type_size(data, offset)
        try:
            if obj_type == _OFS_DELTA:
                raise ValueError(
                    f"OFS_DELTA (type 6) objects are not supported (offset {obj_start})"
                )
            elif obj_type == _REF_DELTA:
                base_sha = data[offset : offset + 20].hex()
                offset += 20
                decompressor = zlib.decompressobj()
                delta_data = decompressor.decompress(data[offset:])
                offset += len(data[offset:]) - len(decompressor.unused_data)
                raw = {
                    "kind": "ref_delta",
                    "base_sha": base_sha,
                    "delta": delta_data,
                }
            elif obj_type in _TYPE_MAP_REVERSE:
                decompressor = zlib.decompressobj()
                decompressed = decompressor.decompress(data[offset:])
                offset += len(data[offset:]) - len(decompressor.unused_data)
                obj_type_str = _TYPE_MAP_REVERSE[obj_type]
                raw = {
                    "kind": "base",
                    "type": obj_type_str,
                    "data": decompressed,
                    "sha": compute_sha(obj_type_str, decompressed),
                }
            else:
                raise ValueError(f"Unknown object type: {obj_type}")
        except zlib.error as e:
            raise ValueError(
                f"Failed to decompress PACK object at offset {obj_start}: {e}"
            ) from e

        raw_objects.append(raw)

    # Build SHA -> (type, data) for all resolved base objects
    sha_map: dict[str, tuple[str, bytes]] = {}
    for raw in raw_objects:
        if raw["kind"] == "base":
            sha_map[raw["sha"]] = (raw["type"], raw["data"])

    # Iteratively resolve deltas; each pass must make progress to avoid infinite loops
    unresolved = [r for r in raw_objects if r["kind"] == "ref_delta"]
    while unresolved:
        progress = False
        still_unresolved = []

        for raw in unresolved:
            base_sha = raw["base_sha"]
            if base_sha in sha_map:
                base_type, base_data = sha_map[base_sha]
            elif base_lookup is not None:
                result = base_lookup(base_sha)
                if result is None:
                    still_unresolved.append(raw)
                    continue
                base_type, base_data = result
                sha_map[base_sha] = (base_type, base_data)
            else:
                still_unresolved.append(raw)
                continue

            resolved_data = _apply_delta(base_data, raw["delta"])
            raw["kind"] = "resolved"
            raw["type"] = base_type
            raw["data"] = resolved_data
            raw["sha"] = compute_sha(base_type, resolved_data)
            sha_map[raw["sha"]] = (base_type, resolved_data)
            progress = True

        if not progress:
            raise ValueError(
                f"Could not resolve {len(still_unresolved)} delta object(s): "
                "base objects not found in pack or repository"
            )
        unresolved = still_unresolved

    return [
        {"type": r["type"], "data": r["data"], "sha": r["sha"]} for r in raw_objects
    ]
