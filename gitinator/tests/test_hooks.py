"""
Tests for the git server-side hook registry and built-in hook implementations.
"""

import hashlib

from django.test import TestCase
from django.urls import reverse as url_for

from gitinator import hooks, pack, pktline
from gitinator.git import NULL_SHA
from gitinator.hooks import run_update_hooks
from gitinator.hooks.protect_default_branch import update_hook
from gitinator.models import GitObject
from gitinator.tests.factories import (
    COMMIT_SHA,
    make_branch,
    make_git_object,
    make_repo,
)


def _git_sha(obj_type, data):
    """Compute the git SHA-1 for a raw object: sha1("<type> <size>\\0<data>")."""
    header = f"{obj_type} {len(data)}\x00".encode()
    return hashlib.sha1(header + data, usedforsecurity=False).hexdigest()


class HookListTest(TestCase):
    """Unit tests for the hook list and run_update_hooks."""

    def setUp(self):
        self._saved_hooks = list(hooks._update_hooks)
        hooks._update_hooks.clear()

    def tearDown(self):
        hooks._update_hooks[:] = self._saved_hooks

    def test_empty_list_returns_none(self):
        result = run_update_hooks(None, "refs/heads/main", NULL_SHA, "a" * 40)
        self.assertIsNone(result)

    def test_approving_hook_returns_none(self):
        hooks._update_hooks.append(lambda *a: None)
        result = run_update_hooks(None, "refs/heads/main", NULL_SHA, "a" * 40)
        self.assertIsNone(result)

    def test_rejecting_hook_returns_reason(self):
        hooks._update_hooks.append(lambda *a: "blocked")
        self.assertEqual(
            run_update_hooks(None, "refs/heads/main", NULL_SHA, "a" * 40), "blocked"
        )

    def test_first_rejection_short_circuits(self):
        calls = []

        def hook1(*a):
            calls.append(1)
            return "blocked"

        def hook2(*a):
            calls.append(2)
            return None

        hooks._update_hooks.extend([hook1, hook2])
        run_update_hooks(None, "refs/heads/main", NULL_SHA, "a" * 40)
        self.assertEqual(calls, [1])


class ProtectDefaultBranchTest(TestCase):
    """Unit tests for the protect_default_branch hook function."""

    OLD_SHA = "a" * 40

    def setUp(self):
        self.repo = make_repo(default_branch="main")
        make_git_object(
            self.repo,
            self.OLD_SHA,
            type=GitObject.Type.COMMIT,
            data=b"old commit",
        )

    def test_allows_push_to_non_default_branch(self):
        result = update_hook(self.repo, "refs/heads/feature", self.OLD_SHA, "b" * 40)
        self.assertIsNone(result)

    def test_allows_initial_push_to_default_branch(self):
        new_sha = "b" * 40
        make_git_object(self.repo, new_sha, type=GitObject.Type.COMMIT, data=b"init")
        result = update_hook(self.repo, "refs/heads/main", NULL_SHA, new_sha)
        self.assertIsNone(result)

    def test_allows_fast_forward_push(self):
        ff_data = f"parent {self.OLD_SHA}\n\nff commit".encode()
        ff_sha = _git_sha(GitObject.Type.COMMIT, ff_data)
        make_git_object(self.repo, ff_sha, type=GitObject.Type.COMMIT, data=ff_data)
        result = update_hook(self.repo, "refs/heads/main", self.OLD_SHA, ff_sha)
        self.assertIsNone(result)

    def test_rejects_deletion_of_default_branch(self):
        result = update_hook(self.repo, "refs/heads/main", self.OLD_SHA, NULL_SHA)
        self.assertIsNotNone(result)

    def test_rejects_force_push_to_default_branch(self):
        force_data = b"unrelated commit with no parent"
        force_sha = _git_sha(GitObject.Type.COMMIT, force_data)
        make_git_object(
            self.repo, force_sha, type=GitObject.Type.COMMIT, data=force_data
        )
        result = update_hook(self.repo, "refs/heads/main", self.OLD_SHA, force_sha)
        self.assertIsNotNone(result)


class ProtectDefaultBranchIntegrationTest(TestCase):
    """Integration tests: force-push protection via the HTTP receive-pack endpoint."""

    OLD_SHA = COMMIT_SHA  # "a" * 40, the existing commit in the fixture
    # Fast-forward commit whose data declares OLD_SHA as parent
    FF_DATA = f"parent {COMMIT_SHA}\n\nff commit".encode()
    FF_SHA = _git_sha(GitObject.Type.COMMIT, FF_DATA)
    # Unrelated commit (force push)
    FORCE_DATA = b"unrelated commit"
    FORCE_SHA = _git_sha(GitObject.Type.COMMIT, FORCE_DATA)

    def setUp(self):
        self.repo = make_repo(default_branch="main")
        self.old_commit = make_git_object(
            self.repo,
            self.OLD_SHA,
            type=GitObject.Type.COMMIT,
            data=b"old commit",
        )
        make_branch(self.repo, "main", self.old_commit)
        self.url = url_for(
            "receive_pack",
            kwargs={"group_name": self.repo.group_name, "repo_name": self.repo.name},
        )

    def _build_pack(self, objects):
        class _Obj:
            def __init__(self, t, d):
                self.type, self.data = t, d

        return pack.build([_Obj(t, d) for t, d in objects])

    def _post(self, commands, pack_data=b""):
        body = b""
        for i, (old_sha, new_sha, refname) in enumerate(commands):
            line = f"{old_sha} {new_sha} {refname}".encode()
            if i == 0:
                line += b"\x00report-status"
            line += b"\n"
            body += pktline.encode(line)
        body += pktline.flush()
        body += pack_data
        return self.client.post(
            self.url,
            data=body,
            content_type="application/x-git-receive-pack-request",
        )

    def _lines(self, content):
        return [line for line in pktline.decode(content) if line is not None]

    def test_fast_forward_push_to_default_branch_is_accepted(self):
        pack_data = self._build_pack([(GitObject.Type.COMMIT, self.FF_DATA)])
        response = self._post(
            [(self.OLD_SHA, self.FF_SHA, "refs/heads/main")], pack_data
        )
        lines = self._lines(response.content)
        self.assertIn(b"ok refs/heads/main\n", lines)

    def test_force_push_to_default_branch_is_rejected(self):
        pack_data = self._build_pack([(GitObject.Type.COMMIT, self.FORCE_DATA)])
        response = self._post(
            [(self.OLD_SHA, self.FORCE_SHA, "refs/heads/main")], pack_data
        )
        lines = self._lines(response.content)
        self.assertTrue(
            any(line.startswith(b"ng refs/heads/main ") for line in lines)
        )

    def test_deletion_of_default_branch_is_rejected(self):
        response = self._post([(self.OLD_SHA, NULL_SHA, "refs/heads/main")])
        lines = self._lines(response.content)
        self.assertTrue(
            any(line.startswith(b"ng refs/heads/main ") for line in lines)
        )

    def test_force_push_to_non_default_branch_is_accepted(self):
        feature_commit = make_git_object(
            self.repo, "b" * 40, type=GitObject.Type.COMMIT, data=b"feature"
        )
        make_branch(self.repo, "feature", feature_commit)
        pack_data = self._build_pack([(GitObject.Type.COMMIT, self.FORCE_DATA)])
        response = self._post(
            [("b" * 40, self.FORCE_SHA, "refs/heads/feature")], pack_data
        )
        lines = self._lines(response.content)
        self.assertIn(b"ok refs/heads/feature\n", lines)
