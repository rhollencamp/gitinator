"""Tests for gitinator.config_sync and the sync_config_repos post-receive hook."""

import time

from django.test import TestCase

from gitinator import hooks
from gitinator.config_sync import sync_repos_from_config
from gitinator.git import TreeEntry, build_blob, build_commit, build_tree
from gitinator.hooks.sync_config_repos import post_receive_hook
from gitinator.models import GitObject, GitRef, Repo
from gitinator.tests.factories import make_repo


def _store(repo, sha, obj_type, data):
    return GitObject.objects.create(repository=repo, sha=sha, type=obj_type, data=data)


def _build_config_tree(repo, repo_defs):
    """Store git objects for repos/{group}/{name}/config.yaml and return root tree SHA.

    repo_defs is a list of (group_name, repo_name, default_branch) tuples.
    """
    by_group: dict[str, list[tuple[str, str]]] = {}
    for group_name, repo_name, default_branch in repo_defs:
        by_group.setdefault(group_name, []).append((repo_name, default_branch))

    repos_dir_entries = []
    for group_name, repos in by_group.items():
        repo_tree_entries = []
        for repo_name, default_branch in repos:
            yaml_content = f"default_branch: {default_branch}\n".encode()
            blob_sha, blob_data = build_blob(yaml_content)
            _store(repo, blob_sha, GitObject.Type.BLOB, blob_data)

            repo_tree_sha, repo_tree_data = build_tree(
                [TreeEntry(name="config.yaml", sha=blob_sha, mode="100644")]
            )
            _store(repo, repo_tree_sha, GitObject.Type.TREE, repo_tree_data)
            repo_tree_entries.append(
                TreeEntry(name=repo_name, sha=repo_tree_sha, mode="40000")
            )

        group_tree_sha, group_tree_data = build_tree(repo_tree_entries)
        _store(repo, group_tree_sha, GitObject.Type.TREE, group_tree_data)
        repos_dir_entries.append(
            TreeEntry(name=group_name, sha=group_tree_sha, mode="40000")
        )

    repos_tree_sha, repos_tree_data = build_tree(repos_dir_entries)
    _store(repo, repos_tree_sha, GitObject.Type.TREE, repos_tree_data)

    root_tree_sha, root_tree_data = build_tree(
        [TreeEntry(name="repos", sha=repos_tree_sha, mode="40000")]
    )
    _store(repo, root_tree_sha, GitObject.Type.TREE, root_tree_data)
    return root_tree_sha


def _commit_tree(repo, tree_sha):
    """Store a commit pointing at tree_sha and return the commit GitObject."""
    now = f"Gitinator <gitinator@thewaffleshop.net> {int(time.time())} +0000"
    commit_sha, commit_data = build_commit(
        tree_sha=tree_sha, message="test commit\n", author=now, committer=now
    )
    return _store(repo, commit_sha, GitObject.Type.COMMIT, commit_data)


def _make_test_config_repo_with_blob(group_name, repo_name, blob_content):
    """Create a config repo whose single config.yaml contains arbitrary bytes.

    Used to exercise error-handling paths for invalid or non-dict YAML.
    """
    config_repo = make_repo(group_name="testorg", name="config", default_branch="main")
    blob_sha, blob_data = build_blob(blob_content)
    _store(config_repo, blob_sha, GitObject.Type.BLOB, blob_data)

    repo_tree_sha, repo_tree_data = build_tree(
        [TreeEntry(name="config.yaml", sha=blob_sha, mode="100644")]
    )
    _store(config_repo, repo_tree_sha, GitObject.Type.TREE, repo_tree_data)

    group_tree_sha, group_tree_data = build_tree(
        [TreeEntry(name=repo_name, sha=repo_tree_sha, mode="40000")]
    )
    _store(config_repo, group_tree_sha, GitObject.Type.TREE, group_tree_data)

    repos_tree_sha, repos_tree_data = build_tree(
        [TreeEntry(name=group_name, sha=group_tree_sha, mode="40000")]
    )
    _store(config_repo, repos_tree_sha, GitObject.Type.TREE, repos_tree_data)

    root_tree_sha, root_tree_data = build_tree(
        [TreeEntry(name="repos", sha=repos_tree_sha, mode="40000")]
    )
    _store(config_repo, root_tree_sha, GitObject.Type.TREE, root_tree_data)

    commit = _commit_tree(config_repo, root_tree_sha)
    GitRef.objects.create(
        repository=config_repo, name="main", type=GitRef.Type.BRANCH, git_object=commit
    )
    return config_repo


def _make_test_config_repo(repo_defs):
    """Create a fresh non-gitinator repo pre-loaded with a repos/ tree.

    Used to test sync_repos_from_config in isolation without touching the
    real gitinator/config repo.
    """
    config_repo = make_repo(group_name="testorg", name="config", default_branch="main")
    root_tree_sha = _build_config_tree(config_repo, repo_defs)
    commit = _commit_tree(config_repo, root_tree_sha)
    GitRef.objects.create(
        repository=config_repo, name="main", type=GitRef.Type.BRANCH, git_object=commit
    )
    return config_repo


def _make_test_config_repo_empty():
    """Create a fresh non-gitinator config repo with no repos/ directory."""
    config_repo = make_repo(group_name="testorg", name="config", default_branch="main")
    blob_sha, blob_data = build_blob(b"# Gitinator configuration\n")
    _store(config_repo, blob_sha, GitObject.Type.BLOB, blob_data)
    root_tree_sha, root_tree_data = build_tree(
        [TreeEntry(name="config.yaml", sha=blob_sha, mode="100644")]
    )
    _store(config_repo, root_tree_sha, GitObject.Type.TREE, root_tree_data)
    commit = _commit_tree(config_repo, root_tree_sha)
    GitRef.objects.create(
        repository=config_repo, name="main", type=GitRef.Type.BRANCH, git_object=commit
    )
    return config_repo


def _update_config_repo_with_defs(config_repo, repo_defs):
    """Add a new commit with repo_defs to config_repo's default branch.

    Returns the new commit SHA.
    """
    root_tree_sha = _build_config_tree(config_repo, repo_defs)
    commit = _commit_tree(config_repo, root_tree_sha)
    GitRef.objects.filter(
        repository=config_repo, name=config_repo.default_branch, type=GitRef.Type.BRANCH
    ).update(git_object=commit)
    return commit.sha


class SyncReposFromConfigTest(TestCase):
    """Unit tests for sync_repos_from_config."""

    def test_no_repos_dir_creates_nothing(self):
        config_repo = _make_test_config_repo_empty()
        before = Repo.objects.count()
        sync_repos_from_config(config_repo)
        self.assertEqual(Repo.objects.count(), before)

    def test_creates_repo_from_config(self):
        config_repo = _make_test_config_repo([("myorg", "myrepo", "main")])
        sync_repos_from_config(config_repo)
        repo = Repo.objects.get(group_name="myorg", name="myrepo")
        self.assertEqual(repo.default_branch, "main")

    def test_updates_default_branch(self):
        existing = make_repo(group_name="myorg", name="myrepo", default_branch="master")
        config_repo = _make_test_config_repo([("myorg", "myrepo", "main")])
        sync_repos_from_config(config_repo)
        existing.refresh_from_db()
        self.assertEqual(existing.default_branch, "main")

    def test_creates_multiple_repos(self):
        config_repo = _make_test_config_repo(
            [
                ("org1", "repo1", "main"),
                ("org1", "repo2", "develop"),
                ("org2", "other", "trunk"),
            ]
        )
        sync_repos_from_config(config_repo)
        self.assertTrue(Repo.objects.filter(group_name="org1", name="repo1").exists())
        self.assertTrue(Repo.objects.filter(group_name="org1", name="repo2").exists())
        self.assertTrue(Repo.objects.filter(group_name="org2", name="other").exists())

    def test_skips_gitinator_config_entry(self):
        # Even if someone commits repos/gitinator/config/config.yaml, it is ignored.
        config_repo = _make_test_config_repo([("gitinator", "config", "main")])
        before_count = Repo.objects.count()
        sync_repos_from_config(config_repo)
        self.assertEqual(Repo.objects.count(), before_count)

    def test_empty_yaml_creates_repo_with_default_branch(self):
        config_repo = _make_test_config_repo_with_blob("myorg", "myrepo", b"")
        sync_repos_from_config(config_repo)
        repo = Repo.objects.get(group_name="myorg", name="myrepo")
        self.assertEqual(repo.default_branch, "main")

    def test_skips_invalid_yaml(self):
        config_repo = _make_test_config_repo_with_blob("myorg", "myrepo", b"{{{")
        before = Repo.objects.count()
        sync_repos_from_config(config_repo)
        self.assertEqual(Repo.objects.count(), before)

    def test_skips_non_dict_yaml(self):
        config_repo = _make_test_config_repo_with_blob("myorg", "myrepo", b"42\n")
        before = Repo.objects.count()
        sync_repos_from_config(config_repo)
        self.assertEqual(Repo.objects.count(), before)

    def test_missing_default_branch_ref_is_safe(self):
        config_repo = make_repo(
            group_name="testorg", name="nocfg", default_branch="main"
        )
        before = Repo.objects.count()
        # No branch ref created — should not raise and should create no new repos
        sync_repos_from_config(config_repo)
        self.assertEqual(Repo.objects.count(), before)


class PostReceiveHookTest(TestCase):
    """Unit tests for the sync_config_repos post-receive hook."""

    def test_no_op_for_non_config_repo(self):
        other_repo = make_repo(group_name="myorg", name="myrepo")
        post_receive_hook(other_repo, [("0" * 40, "a" * 40, "refs/heads/main")])
        # No repos should have been created beyond the one we just made
        self.assertFalse(
            Repo.objects.exclude(pk=other_repo.pk).filter(group_name="myorg").exists()
        )

    def test_no_op_when_non_default_branch_updated(self):
        config_repo = Repo.objects.get(group_name="gitinator", name="config")
        _update_config_repo_with_defs(config_repo, [("myorg", "myrepo", "main")])
        # Push to a feature branch, not main
        post_receive_hook(config_repo, [("0" * 40, "a" * 40, "refs/heads/feature")])
        self.assertFalse(
            Repo.objects.filter(group_name="myorg", name="myrepo").exists()
        )

    def test_syncs_when_default_branch_updated(self):
        config_repo = Repo.objects.get(group_name="gitinator", name="config")
        head_sha = _update_config_repo_with_defs(
            config_repo, [("myorg", "newrepo", "main")]
        )
        post_receive_hook(config_repo, [("0" * 40, head_sha, "refs/heads/main")])
        self.assertTrue(
            Repo.objects.filter(group_name="myorg", name="newrepo").exists()
        )


class PostReceiveHookRegistryTest(TestCase):
    """Verify post_receive_hook is registered in the hook list."""

    def test_post_receive_hook_is_registered(self):
        self.assertIn(post_receive_hook, hooks._post_receive_hooks)
