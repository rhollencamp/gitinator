"""
Tests for gitinator.git: object parsing and ref name utilities.
"""

from django.test import SimpleTestCase

from gitinator import git


class ComputeShaTest(SimpleTestCase):
    def test_known_blob(self):
        # git hash-object computes sha1("blob <len>\0<data>")
        # sha of "hello world\n": echo "hello world" | git hash-object --stdin
        data = b"hello world\n"
        sha = git.compute_sha("blob", data)
        self.assertEqual(sha, "3b18e512dba79e4c8300dd08aeb37f8e728b8dad")

    def test_empty_blob(self):
        sha = git.compute_sha("blob", b"")
        self.assertEqual(sha, "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391")


class RefFullNameTest(SimpleTestCase):
    def test_branch(self):
        self.assertEqual(git.ref_full_name("branch", "main"), "refs/heads/main")

    def test_tag(self):
        self.assertEqual(git.ref_full_name("tag", "v1.0"), "refs/tags/v1.0")

    def test_branch_with_slash(self):
        self.assertEqual(
            git.ref_full_name("branch", "feature/foo"), "refs/heads/feature/foo"
        )

    def test_invalid_type(self):
        with self.assertRaises(ValueError):
            git.ref_full_name("remote", "main")


class ParseRefnameTest(SimpleTestCase):
    def test_branch(self):
        ref_type, name = git.parse_refname("refs/heads/main")
        self.assertEqual(ref_type, "branch")
        self.assertEqual(name, "main")

    def test_tag(self):
        ref_type, name = git.parse_refname("refs/tags/v1.0")
        self.assertEqual(ref_type, "tag")
        self.assertEqual(name, "v1.0")

    def test_invalid(self):
        with self.assertRaises(ValueError):
            git.parse_refname("refs/remotes/origin/main")

    def test_roundtrip(self):
        for ref_type, name in [("branch", "main"), ("tag", "v2.3.1")]:
            full = git.ref_full_name(ref_type, name)
            parsed_type, parsed_name = git.parse_refname(full)
            self.assertEqual(parsed_type, ref_type)
            self.assertEqual(parsed_name, name)


class ParseCommitTest(SimpleTestCase):
    def _make_commit(self, tree, parents=(), author="", committer="", message=""):
        lines = [f"tree {tree}"]
        for p in parents:
            lines.append(f"parent {p}")
        if author:
            lines.append(f"author {author}")
        if committer:
            lines.append(f"committer {committer}")
        lines.append("")  # blank line separating header from body
        lines.append(message)
        return "\n".join(lines).encode()

    def test_initial_commit(self):
        data = self._make_commit(
            tree="a" * 40,
            author="Alice <alice@example.com> 1700000000 +0000",
            committer="Alice <alice@example.com> 1700000000 +0000",
            message="Initial commit",
        )
        commit = git.parse_commit(data)
        self.assertEqual(commit.tree, "a" * 40)
        self.assertEqual(commit.parents, [])
        self.assertIn("Alice", commit.author)
        self.assertEqual(commit.message, "Initial commit")

    def test_commit_with_parent(self):
        data = self._make_commit(
            tree="b" * 40,
            parents=["c" * 40],
            message="Second commit",
        )
        commit = git.parse_commit(data)
        self.assertEqual(commit.tree, "b" * 40)
        self.assertEqual(commit.parents, ["c" * 40])
        self.assertEqual(commit.message, "Second commit")

    def test_merge_commit(self):
        data = self._make_commit(
            tree="d" * 40,
            parents=["e" * 40, "f" * 40],
            message="Merge",
        )
        commit = git.parse_commit(data)
        self.assertEqual(commit.parents, ["e" * 40, "f" * 40])


class ParseTreeTest(SimpleTestCase):
    def _encode_entry(self, mode, name, sha_hex):
        """Build raw binary for one tree entry."""
        header = f"{mode} {name}".encode() + b"\x00"
        sha_bytes = bytes.fromhex(sha_hex)
        return header + sha_bytes

    def test_single_blob(self):
        sha = "a" * 40
        data = self._encode_entry("100644", "README.md", sha)
        entries = git.parse_tree(data)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].name, "README.md")
        self.assertEqual(entries[0].sha, sha)
        self.assertEqual(entries[0].mode, "100644")
        self.assertEqual(entries[0].type, "blob")

    def test_subtree_type(self):
        sha = "b" * 40
        data = self._encode_entry("40000", "src", sha)
        entries = git.parse_tree(data)
        self.assertEqual(entries[0].type, "tree")

    def test_executable_blob(self):
        sha = "c" * 40
        data = self._encode_entry("100755", "run.sh", sha)
        entries = git.parse_tree(data)
        self.assertEqual(entries[0].type, "blob")

    def test_multiple_entries(self):
        blob_sha = "a" * 40
        tree_sha = "b" * 40
        data = self._encode_entry("100644", "file.txt", blob_sha) + self._encode_entry(
            "40000", "subdir", tree_sha
        )
        entries = git.parse_tree(data)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].name, "file.txt")
        self.assertEqual(entries[1].name, "subdir")
        self.assertEqual(entries[1].type, "tree")

    def test_empty_tree(self):
        self.assertEqual(git.parse_tree(b""), [])
