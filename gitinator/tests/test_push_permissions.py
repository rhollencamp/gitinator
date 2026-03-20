"""
Tests for HTTP Basic Auth and admin-only push permission enforcement.
"""

import base64

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse as url_for

from gitinator import pack, pktline
from gitinator.git import NULL_SHA
from gitinator.models import GitObject
from gitinator.tests.factories import (
    COMMIT_SHA,
    make_branch,
    make_git_object,
    make_repo,
)


def _auth_header(username, password):
    credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {credentials}"


class ReceivePackAuthTest(TestCase):
    """Integration tests: authentication and admin-only push via HTTP receive-pack."""

    def setUp(self):
        self.repo = make_repo(default_branch="main")
        old_commit = make_git_object(
            self.repo,
            COMMIT_SHA,
            type=GitObject.Type.COMMIT,
            data=b"old commit",
        )
        make_branch(self.repo, "main", old_commit)
        self.url = url_for(
            "receive_pack",
            kwargs={"group_name": self.repo.group_name, "repo_name": self.repo.name},
        )
        self.admin = User.objects.create_user("admin", password="secret", is_staff=True)
        self.regular = User.objects.create_user(
            "regular", password="secret", is_staff=False
        )

    def _build_push_body(self):
        """Build a minimal pkt-line push body for a new branch."""
        new_obj = make_git_object(
            self.repo, "b" * 40, type=GitObject.Type.COMMIT, data=b"new commit"
        )
        pack_data = pack.build([new_obj])
        line = f"{NULL_SHA} {'b' * 40} refs/heads/feature\x00report-status\n".encode()
        return pktline.encode(line) + pktline.flush() + pack_data

    def _post(self, body, auth_header=None):
        headers = {}
        if auth_header:
            headers["HTTP_AUTHORIZATION"] = auth_header
        return self.client.post(
            self.url,
            data=body,
            content_type="application/x-git-receive-pack-request",
            **headers,
        )

    def test_unauthenticated_push_returns_401(self):
        response = self._post(self._build_push_body())
        self.assertEqual(response.status_code, 401)
        self.assertIn("WWW-Authenticate", response)

    def test_non_admin_push_returns_401(self):
        response = self._post(
            self._build_push_body(), _auth_header("regular", "secret")
        )
        self.assertEqual(response.status_code, 401)

    def test_admin_push_succeeds(self):
        body = self._build_push_body()
        response = self._post(body, _auth_header("admin", "secret"))
        self.assertEqual(response.status_code, 200)
        lines = [line for line in pktline.decode(response.content) if line is not None]
        self.assertIn(b"ok refs/heads/feature\n", lines)

    def test_invalid_credentials_return_401(self):
        response = self._post(self._build_push_body(), _auth_header("admin", "wrong"))
        self.assertEqual(response.status_code, 401)


class InfoRefsReceivePackAuthTest(TestCase):
    """Tests that info_refs requires staff auth for the git-receive-pack service."""

    def setUp(self):
        self.repo = make_repo(default_branch="main")
        self.url = url_for(
            "info_refs",
            kwargs={"group_name": self.repo.group_name, "repo_name": self.repo.name},
        )
        self.admin = User.objects.create_user("admin", password="secret", is_staff=True)
        User.objects.create_user("regular", password="secret", is_staff=False)

    def test_unauthenticated_receive_pack_info_refs_returns_401(self):
        response = self.client.get(self.url, {"service": "git-receive-pack"})
        self.assertEqual(response.status_code, 401)
        self.assertIn("WWW-Authenticate", response)

    def test_non_admin_receive_pack_info_refs_returns_401(self):
        response = self.client.get(
            self.url,
            {"service": "git-receive-pack"},
            HTTP_AUTHORIZATION=_auth_header("regular", "secret"),
        )
        self.assertEqual(response.status_code, 401)

    def test_admin_receive_pack_info_refs_returns_200(self):
        response = self.client.get(
            self.url,
            {"service": "git-receive-pack"},
            HTTP_AUTHORIZATION=_auth_header("admin", "secret"),
        )
        self.assertEqual(response.status_code, 200)

    def test_upload_pack_info_refs_does_not_require_auth(self):
        response = self.client.get(self.url, {"service": "git-upload-pack"})
        self.assertEqual(response.status_code, 200)
