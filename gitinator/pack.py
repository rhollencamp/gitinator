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
    return pack_data + sha1(pack_data).digest()
