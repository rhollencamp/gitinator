"""Tests for the repository landing page view."""

from django.test import TestCase
from django.urls import reverse as url_for

from gitinator.models import GitObject
from gitinator.tests.factories import make_branch, make_git_object, make_repo

_README_SHA = "d" * 40
_README_DATA = b"# My Project\n\nWelcome to the project."

_BLOB_SHA = "e" * 40
_BLOB_DATA = b"hello"

_BINARY_SHA = "f" * 40
_BINARY_DATA = b"PNG\x00binary"

# Root tree: README.md (blob), hello.txt (blob)
_TREE_SHA = "1" * 40
_TREE_DATA = (
    b"100644 README.md\x00"
    + bytes.fromhex(_README_SHA)
    + b"100644 hello.txt\x00"
    + bytes.fromhex(_BLOB_SHA)
)

# Root tree: binary.md instead of README.md (binary content)
_BINARY_README_TREE_SHA = "2" * 40
_BINARY_README_TREE_DATA = b"100644 README.md\x00" + bytes.fromhex(_BINARY_SHA)

# Root tree: no README.md
_NO_README_TREE_SHA = "3" * 40
_NO_README_TREE_DATA = b"100644 hello.txt\x00" + bytes.fromhex(_BLOB_SHA)

_COMMIT_SHA = "4" * 40
_COMMIT_DATA = (
    f"tree {_TREE_SHA}\n"
    "author Test <test@example.com> 1000000000 +0000\n"
    "committer Test <test@example.com> 1000000000 +0000\n"
    "\n"
    "Initial commit\n"
).encode()

_NO_README_COMMIT_SHA = "5" * 40
_NO_README_COMMIT_DATA = (
    f"tree {_NO_README_TREE_SHA}\n"
    "author Test <test@example.com> 1000000000 +0000\n"
    "committer Test <test@example.com> 1000000000 +0000\n"
    "\n"
    "Initial commit\n"
).encode()

_BINARY_README_COMMIT_SHA = "6" * 40
_BINARY_README_COMMIT_DATA = (
    f"tree {_BINARY_README_TREE_SHA}\n"
    "author Test <test@example.com> 1000000000 +0000\n"
    "committer Test <test@example.com> 1000000000 +0000\n"
    "\n"
    "Initial commit\n"
).encode()


def _landing_url(repo):
    return url_for(
        "repo_landing",
        kwargs={"group_name": repo.group_name, "repo_name": repo.name},
    )


def _make_fixture_with_readme():
    repo = make_repo()
    make_git_object(repo, _README_SHA, type=GitObject.Type.BLOB, data=_README_DATA)
    make_git_object(repo, _BLOB_SHA, type=GitObject.Type.BLOB, data=_BLOB_DATA)
    make_git_object(repo, _TREE_SHA, type=GitObject.Type.TREE, data=_TREE_DATA)
    commit = make_git_object(
        repo, _COMMIT_SHA, type=GitObject.Type.COMMIT, data=_COMMIT_DATA
    )
    make_branch(repo, "main", commit)
    return repo


def _make_fixture_no_readme():
    repo = make_repo(name="norepo")
    make_git_object(repo, _BLOB_SHA, type=GitObject.Type.BLOB, data=_BLOB_DATA)
    make_git_object(
        repo, _NO_README_TREE_SHA, type=GitObject.Type.TREE, data=_NO_README_TREE_DATA
    )
    commit = make_git_object(
        repo,
        _NO_README_COMMIT_SHA,
        type=GitObject.Type.COMMIT,
        data=_NO_README_COMMIT_DATA,
    )
    make_branch(repo, "main", commit)
    return repo


def _make_fixture_binary_readme():
    repo = make_repo(name="binrepo")
    make_git_object(repo, _BINARY_SHA, type=GitObject.Type.BLOB, data=_BINARY_DATA)
    make_git_object(
        repo,
        _BINARY_README_TREE_SHA,
        type=GitObject.Type.TREE,
        data=_BINARY_README_TREE_DATA,
    )
    commit = make_git_object(
        repo,
        _BINARY_README_COMMIT_SHA,
        type=GitObject.Type.COMMIT,
        data=_BINARY_README_COMMIT_DATA,
    )
    make_branch(repo, "main", commit)
    return repo


class RepoLandingEmptyRepoTest(TestCase):
    def setUp(self):
        self.repo = make_repo(name="emptyrepo")
        self.url = _landing_url(self.repo)

    def test_returns_200(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_uses_browse_empty_template(self):
        response = self.client.get(self.url)
        self.assertTemplateUsed(response, "gitinator/browse_empty.html")

    def test_shows_repo_name(self):
        response = self.client.get(self.url)
        self.assertContains(response, self.repo.name)


class RepoLandingWithReadmeTest(TestCase):
    def setUp(self):
        self.repo = _make_fixture_with_readme()
        self.url = _landing_url(self.repo)

    def test_returns_200(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_uses_repo_landing_template(self):
        response = self.client.get(self.url)
        self.assertTemplateUsed(response, "gitinator/repo_landing.html")

    def test_shows_repo_name(self):
        response = self.client.get(self.url)
        self.assertContains(response, self.repo.name)

    def test_shows_file_entries(self):
        response = self.client.get(self.url)
        self.assertContains(response, "README.md")
        self.assertContains(response, "hello.txt")

    def test_shows_readme_content(self):
        response = self.client.get(self.url)
        self.assertContains(response, "My Project")
        self.assertContains(response, "Welcome to the project.")

    def test_returns_405_for_post(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 405)


class RepoLandingWithoutReadmeTest(TestCase):
    def setUp(self):
        self.repo = _make_fixture_no_readme()
        self.url = _landing_url(self.repo)

    def test_returns_200(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_shows_file_entries(self):
        response = self.client.get(self.url)
        self.assertContains(response, "hello.txt")

    def test_does_not_show_readme_section(self):
        response = self.client.get(self.url)
        self.assertNotContains(response, "README.md")


class RepoLandingBinaryReadmeTest(TestCase):
    def setUp(self):
        self.repo = _make_fixture_binary_readme()
        self.url = _landing_url(self.repo)

    def test_returns_200(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_does_not_show_binary_readme_content(self):
        # README.md entry shown in file list but content section not rendered
        response = self.client.get(self.url)
        self.assertNotContains(response, "PNG")


class RepoLandingNotFoundTest(TestCase):
    def test_returns_404_for_missing_repo(self):
        url = url_for(
            "repo_landing", kwargs={"group_name": "myorg", "repo_name": "missing"}
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
