"""Tests for gitinator.bootstrap: config repo initialization."""

from django.test import TestCase

from gitinator.bootstrap import ensure_config_repo
from gitinator.git import parse_commit, parse_tree
from gitinator.models import GitObject, GitRef, Repo


class EnsureConfigRepoTest(TestCase):
    def test_creates_repo_with_correct_coordinates(self):
        ensure_config_repo()
        repo = Repo.objects.get(group_name="gitinator", name="config")
        self.assertEqual(repo.default_branch, "main")

    def test_idempotent(self):
        ensure_config_repo()
        ensure_config_repo()
        self.assertEqual(
            Repo.objects.filter(group_name="gitinator", name="config").count(), 1
        )

    def test_main_branch_exists(self):
        ensure_config_repo()
        repo = Repo.objects.get(group_name="gitinator", name="config")
        self.assertTrue(
            GitRef.objects.filter(
                repository=repo, name="main", type=GitRef.Type.BRANCH
            ).exists()
        )

    def test_commit_tree_contains_config_yaml(self):
        ensure_config_repo()
        repo = Repo.objects.get(group_name="gitinator", name="config")
        branch = GitRef.objects.get(
            repository=repo, name="main", type=GitRef.Type.BRANCH
        )
        commit = parse_commit(branch.git_object.data)
        tree_obj = GitObject.objects.get(repository=repo, sha=commit.tree)
        entries = parse_tree(tree_obj.data)
        names = [e.name for e in entries]
        self.assertIn("config.yaml", names)

    def test_config_yaml_is_nonempty(self):
        ensure_config_repo()
        repo = Repo.objects.get(group_name="gitinator", name="config")
        branch = GitRef.objects.get(
            repository=repo, name="main", type=GitRef.Type.BRANCH
        )
        commit = parse_commit(branch.git_object.data)
        tree_obj = GitObject.objects.get(repository=repo, sha=commit.tree)
        entries = parse_tree(tree_obj.data)
        (config_entry,) = [e for e in entries if e.name == "config.yaml"]
        blob = GitObject.objects.get(repository=repo, sha=config_entry.sha)
        self.assertGreater(len(blob.data), 0)
