"""Git object parsing and ref name utilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha1
from typing import Literal

NULL_SHA = "0" * 40


def compute_sha(obj_type: str, data: bytes) -> str:
    """Compute the SHA-1 for a git object using the loose-object format.

    Format: sha1("<type> <size>\\0<data>").
    """
    h = sha1(usedforsecurity=False)
    h.update(f"{obj_type} {len(data)}\x00".encode())
    h.update(data)
    return h.hexdigest()


def ref_full_name(ref_type: str, name: str) -> str:
    """Return the full refname for a branch or tag.

    Examples: refs/heads/main, refs/tags/v1.0.
    """
    if ref_type == "branch":
        return f"refs/heads/{name}"
    if ref_type == "tag":
        return f"refs/tags/{name}"
    raise ValueError(f"Unrecognised ref type: {ref_type}")


def parse_refname(refname: str) -> tuple[Literal["branch", "tag"], str]:
    """Return (type, short_name) from a full ref name.

    Examples: refs/heads/main, refs/tags/v1.0.
    """
    if refname.startswith("refs/heads/"):
        return "branch", refname[len("refs/heads/") :]
    if refname.startswith("refs/tags/"):
        return "tag", refname[len("refs/tags/") :]
    raise ValueError(f"Unrecognised ref name: {refname}")


@dataclass
class CommitData:
    """Parsed representation of a git commit object."""

    tree: str
    parents: list[str] = field(default_factory=list)
    author: str = ""
    committer: str = ""
    message: str = ""


def parse_commit(data: bytes) -> CommitData:
    """Parse raw commit object bytes into a CommitData.

    Git commit format: a header section of key-value lines (tree, parent,
    author, committer, etc.) separated from the message body by a blank line.
    """
    text = data.decode("utf-8", errors="replace")
    header_section, _, message = text.partition("\n\n")

    tree = ""
    parents: list[str] = []
    author = ""
    committer = ""

    for line in header_section.splitlines():
        if line.startswith("tree "):
            tree = line[5:]
        elif line.startswith("parent "):
            parents.append(line[7:])
        elif line.startswith("author "):
            author = line[7:]
        elif line.startswith("committer "):
            committer = line[10:]

    return CommitData(
        tree=tree,
        parents=parents,
        author=author,
        committer=committer,
        message=message,
    )


@dataclass
class TreeEntry:
    """A single entry within a git tree object."""

    name: str
    sha: str  # hex SHA-1
    mode: str  # e.g. "100644", "40000", "100755", "120000"

    @property
    def type(self) -> Literal["blob", "tree"]:
        """Infer object type from mode.

        Mode starting with 4 is a subtree, otherwise a blob.
        """
        return "tree" if self.mode.startswith("4") else "blob"


def build_blob(content: bytes) -> tuple[str, bytes]:
    """Return (sha, data) for a git blob object."""
    sha = compute_sha("blob", content)
    return sha, content


def build_tree(entries: list[TreeEntry]) -> tuple[str, bytes]:
    """Return (sha, data) for a git tree object.

    Entries are sorted by name (git canonical order). Binary format:
    repeated "<mode> <name>\\0<20-byte-sha>" records.
    """
    sorted_entries = sorted(entries, key=lambda e: e.name)
    data = b"".join(
        f"{e.mode} {e.name}\x00".encode() + bytes.fromhex(e.sha) for e in sorted_entries
    )
    sha = compute_sha("tree", data)
    return sha, data


def build_commit(
    tree_sha: str, message: str, author: str, committer: str
) -> tuple[str, bytes]:
    """Return (sha, data) for a git commit object."""
    data = (
        f"tree {tree_sha}\nauthor {author}\ncommitter {committer}\n\n{message}"
    ).encode()
    sha = compute_sha("commit", data)
    return sha, data


def parse_tree(data: bytes) -> list[TreeEntry]:
    """Parse raw tree object bytes into a list of TreeEntry.

    Git tree format: repeated records of "<mode> <name>\\0<20-byte-sha>".
    """
    entries = []
    offset = 0
    while offset < len(data):
        null_pos = data.index(b"\x00", offset)
        header = data[offset:null_pos].decode("utf-8")
        mode, name = header.split(" ", 1)
        sha = data[null_pos + 1 : null_pos + 21].hex()
        entries.append(TreeEntry(name=name, sha=sha, mode=mode))
        offset = null_pos + 21
    return entries
