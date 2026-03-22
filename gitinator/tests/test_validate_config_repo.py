"""Tests for the validate_config_repo update hook."""

import time

from django.test import TestCase

from gitinator import hooks
from gitinator.git import NULL_SHA, TreeEntry, build_blob, build_commit, build_tree
from gitinator.hooks.validate_config_repo import _NAME_RE, update_hook
from gitinator.models import GitObject, Repo
from gitinator.tests.factories import make_repo


def _store(repo, sha, obj_type, data):
    obj, _ = GitObject.objects.get_or_create(
        repository=repo, sha=sha, defaults={"type": obj_type, "data": data}
    )
    return obj


def _make_commit_with_tree(repo, tree_entries):
    """Build and store a commit whose root tree contains the given flat file paths.

    tree_entries is a list of (path, content_bytes) pairs. Paths may use '/'
    to represent subdirectories — each intermediate tree is built automatically.
    """

    # Build a nested dict from paths, then bottom-up into git tree objects.
    def _insert(node, parts, content):
        if len(parts) == 1:
            node[parts[0]] = content
        else:
            node.setdefault(parts[0], {})
            _insert(node[parts[0]], parts[1:], content)

    tree_dict: dict = {}
    for path, content in tree_entries:
        _insert(tree_dict, path.split("/"), content)

    def _build(node):
        entries = []
        for name, value in node.items():
            if isinstance(value, bytes):
                blob_sha, blob_data = build_blob(value)
                _store(repo, blob_sha, GitObject.Type.BLOB, blob_data)
                entries.append(TreeEntry(name=name, sha=blob_sha, mode="100644"))
            else:
                subtree_sha = _build(value)
                entries.append(TreeEntry(name=name, sha=subtree_sha, mode="40000"))
        tree_sha, tree_data = build_tree(entries)
        _store(repo, tree_sha, GitObject.Type.TREE, tree_data)
        return tree_sha

    root_tree_sha = _build(tree_dict)
    now = f"Gitinator <gitinator@thewaffleshop.net> {int(time.time())} +0000"
    commit_sha, commit_data = build_commit(
        tree_sha=root_tree_sha, message="test\n", author=now, committer=now
    )
    _store(repo, commit_sha, GitObject.Type.COMMIT, commit_data)
    return commit_sha


class NameRegexTest(TestCase):
    """Unit tests for the URL-safe name pattern."""

    def test_simple_alphanumeric(self):
        self.assertIsNotNone(_NAME_RE.match("myrepo"))

    def test_with_hyphen(self):
        self.assertIsNotNone(_NAME_RE.match("my-repo"))

    def test_with_underscore(self):
        self.assertIsNotNone(_NAME_RE.match("my_repo"))

    def test_with_dot(self):
        self.assertIsNotNone(_NAME_RE.match("my.repo"))

    def test_leading_digit(self):
        self.assertIsNotNone(_NAME_RE.match("123repo"))

    def test_rejects_leading_hyphen(self):
        self.assertIsNone(_NAME_RE.match("-repo"))

    def test_rejects_leading_dot(self):
        self.assertIsNone(_NAME_RE.match(".hidden"))

    def test_rejects_space(self):
        self.assertIsNone(_NAME_RE.match("my repo"))

    def test_rejects_slash(self):
        self.assertIsNone(_NAME_RE.match("my/repo"))

    def test_rejects_at_sign(self):
        self.assertIsNone(_NAME_RE.match("my@repo"))


class ValidateConfigRepoHookTest(TestCase):
    """Unit tests for validate_config_repo.update_hook."""

    def setUp(self):
        self.config_repo = Repo.objects.get(group_name="gitinator", name="config")

    def _push(self, tree_entries):
        """Simulate pushing a commit with the given tree entries; return hook result."""
        commit_sha = _make_commit_with_tree(self.config_repo, tree_entries)
        return update_hook(self.config_repo, "refs/heads/main", NULL_SHA, commit_sha)

    # --- Scope guards ---

    def test_no_op_for_non_config_repo(self):
        other = make_repo(group_name="myorg", name="other")
        commit_sha = _make_commit_with_tree(other, [("bad file.yaml", b"")])
        result = update_hook(other, "refs/heads/main", NULL_SHA, commit_sha)
        self.assertIsNone(result)

    def test_no_op_for_deletion(self):
        result = update_hook(self.config_repo, "refs/heads/main", "a" * 40, NULL_SHA)
        self.assertIsNone(result)

    # --- Valid paths ---

    def test_accepts_root_config_yaml(self):
        result = self._push([("config.yaml", b"# ok\n")])
        self.assertIsNone(result)

    def test_accepts_valid_repo_definition(self):
        result = self._push(
            [
                ("config.yaml", b""),
                ("repos/myorg/myrepo/config.yaml", b"default_branch: main\n"),
            ]
        )
        self.assertIsNone(result)

    def test_accepts_multiple_repo_definitions(self):
        result = self._push(
            [
                ("repos/org1/repo-a/config.yaml", b"default_branch: main\n"),
                ("repos/org1/repo_b/config.yaml", b"default_branch: main\n"),
                ("repos/org2/other.repo/config.yaml", b"default_branch: main\n"),
            ]
        )
        self.assertIsNone(result)

    # --- Invalid paths ---

    def test_rejects_unknown_root_file(self):
        result = self._push([("README.md", b"hello\n")])
        self.assertIsNotNone(result)
        self.assertIn("README.md", result)

    def test_rejects_extra_file_in_repo_dir(self):
        result = self._push(
            [
                ("repos/myorg/myrepo/config.yaml", b"default_branch: main\n"),
                ("repos/myorg/myrepo/extra.yaml", b""),
            ]
        )
        self.assertIsNotNone(result)
        self.assertIn("extra.yaml", result)

    def test_rejects_file_directly_under_repos(self):
        result = self._push([("repos/stray.yaml", b"")])
        self.assertIsNotNone(result)

    def test_rejects_file_directly_under_group(self):
        result = self._push([("repos/myorg/stray.yaml", b"")])
        self.assertIsNotNone(result)

    # --- Invalid names ---

    def test_rejects_reserved_group_name(self):
        result = self._push([("repos/gitinator/newrepo/config.yaml", b"")])
        self.assertIsNotNone(result)
        self.assertIn("reserved", result)

    def test_rejects_group_name_with_space(self):
        result = self._push([("repos/my org/myrepo/config.yaml", b"")])
        self.assertIsNotNone(result)
        self.assertIn("my org", result)

    def test_rejects_group_name_with_leading_dot(self):
        result = self._push([("repos/.hidden/myrepo/config.yaml", b"")])
        self.assertIsNotNone(result)

    def test_rejects_repo_name_with_at_sign(self):
        result = self._push([("repos/myorg/my@repo/config.yaml", b"")])
        self.assertIsNotNone(result)
        self.assertIn("my@repo", result)


class ValidateConfigRepoYamlTest(TestCase):
    """Tests for YAML content validation in config.yaml files."""

    def setUp(self):
        self.config_repo = Repo.objects.get(group_name="gitinator", name="config")

    def _push(self, tree_entries):
        commit_sha = _make_commit_with_tree(self.config_repo, tree_entries)
        return update_hook(self.config_repo, "refs/heads/main", NULL_SHA, commit_sha)

    def test_accepts_empty_config_yaml(self):
        result = self._push([("repos/myorg/myrepo/config.yaml", b"")])
        self.assertIsNone(result)

    def test_accepts_null_yaml(self):
        result = self._push([("repos/myorg/myrepo/config.yaml", b"null\n")])
        self.assertIsNone(result)

    def test_accepts_valid_default_branch(self):
        result = self._push(
            [("repos/myorg/myrepo/config.yaml", b"default_branch: develop\n")]
        )
        self.assertIsNone(result)

    def test_rejects_invalid_yaml(self):
        result = self._push([("repos/myorg/myrepo/config.yaml", b"key: [unclosed\n")])
        self.assertIsNotNone(result)
        self.assertIn("invalid YAML", result)
        self.assertIn("repos/myorg/myrepo/config.yaml", result)

    def test_rejects_non_mapping_yaml(self):
        result = self._push([("repos/myorg/myrepo/config.yaml", b"- item1\n- item2\n")])
        self.assertIsNotNone(result)
        self.assertIn("expected a mapping", result)

    def test_rejects_non_string_default_branch(self):
        result = self._push(
            [("repos/myorg/myrepo/config.yaml", b"default_branch: 42\n")]
        )
        self.assertIsNotNone(result)
        self.assertIn("default_branch", result)
        self.assertIn("string", result)


class ValidateConfigRepoRegistryTest(TestCase):
    """Verify the hook is registered in the update hook list."""

    def test_validate_config_repo_hook_is_registered(self):
        from gitinator.hooks.validate_config_repo import update_hook as validate_hook

        self.assertIn(validate_hook, hooks._update_hooks)
