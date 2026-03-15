"""
Pkt-line encoding and decoding for the git protocol.

Reference: https://git-scm.com/docs/gitprotocol-http
"""

FLUSH = None


def encode(data: bytes) -> bytes:
    """Encode a single pkt-line record."""
    length = len(data) + 4
    return f"{length:04x}".encode() + data


def flush() -> bytes:
    """Return a flush packet."""
    return b"0000"


def decode(data: bytes) -> list:
    """
    Parse a pkt-line stream into a list of payloads.
    Flush packets are represented as None.
    """
    lines = []
    offset = 0
    while offset < len(data):
        length = int(data[offset : offset + 4], 16)
        if length == 0:
            lines.append(FLUSH)
            offset += 4
        else:
            lines.append(data[offset + 4 : offset + length])
            offset += length
    return lines


def decode_stream(data: bytes) -> tuple[list[bytes], bytes]:
    """
    Parse pkt-lines until the first flush packet.

    Returns a tuple of (lines, remaining_bytes) where lines contains the
    decoded payloads before the flush and remaining_bytes is everything
    after the flush (e.g. raw PACK data in a receive-pack request).
    """
    lines = []
    offset = 0
    while offset < len(data):
        length = int(data[offset : offset + 4], 16)
        if length == 0:
            offset += 4
            break
        lines.append(data[offset + 4 : offset + length])
        offset += length
    return lines, data[offset:]
