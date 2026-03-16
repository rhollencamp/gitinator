"""Tests for the repository browse views."""

from django.test import TestCase
from django.urls import reverse as url_for

from gitinator.models import GitObject, GitRef
from gitinator.tests.factories import make_branch, make_git_object, make_repo

# SHAs use distinct repeated hex digits to avoid collisions with factories.py
_BLOB_SHA = "1" * 40
_BLOB_DATA = b"hello world"

_SUB_BLOB_SHA = "4" * 40
_SUB_BLOB_DATA = b"readme content"

# subdir/ tree: contains readme.md
_SUBTREE_SHA = "5" * 40
_SUBTREE_DATA = b"100644 readme.md\x00" + bytes.fromhex(_SUB_BLOB_SHA)

# Binary blob: contains a null byte
_BINARY_BLOB_SHA = "6" * 40
_BINARY_BLOB_DATA = b"PNG\x00binary\x89data"

# Root tree: contains hello.txt (blob), subdir (tree), binary.bin (blob)
_ROOT_TREE_SHA = "2" * 40
_ROOT_TREE_DATA = (
    b"100755 binary.bin\x00"
    + bytes.fromhex(_BINARY_BLOB_SHA)
    + b"100644 hello.txt\x00"
    + bytes.fromhex(_BLOB_SHA)
    + b"40000 subdir\x00"
    + bytes.fromhex(_SUBTREE_SHA)
)

_COMMIT_SHA = "3" * 40
_COMMIT_DATA = (
    f"tree {_ROOT_TREE_SHA}\n"
    "author Test <test@example.com> 1000000000 +0000\n"
    "committer Test <test@example.com> 1000000000 +0000\n"
    "\n"
    "Initial commit\n"
).encode()


def _make_browse_fixture(group_name="myorg", name="myrepo", default_branch="main"):
    repo = make_repo(group_name=group_name, name=name, default_branch=default_branch)
    make_git_object(repo, _BLOB_SHA, type=GitObject.Type.BLOB, data=_BLOB_DATA)
    make_git_object(repo, _SUB_BLOB_SHA, type=GitObject.Type.BLOB, data=_SUB_BLOB_DATA)
    make_git_object(repo, _SUBTREE_SHA, type=GitObject.Type.TREE, data=_SUBTREE_DATA)
    make_git_object(
        repo, _BINARY_BLOB_SHA, type=GitObject.Type.BLOB, data=_BINARY_BLOB_DATA
    )
    make_git_object(
        repo, _ROOT_TREE_SHA, type=GitObject.Type.TREE, data=_ROOT_TREE_DATA
    )
    commit = make_git_object(
        repo, _COMMIT_SHA, type=GitObject.Type.COMMIT, data=_COMMIT_DATA
    )
    make_branch(repo, default_branch, commit)
    return repo


class BrowseRootTreeTest(TestCase):
    def setUp(self):
        self.repo = _make_browse_fixture()
        self.url = url_for(
            "browse",
            kwargs={"group_name": self.repo.group_name, "repo_name": self.repo.name},
        )

    def test_returns_200_for_default_branch(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_uses_browse_tree_template(self):
        response = self.client.get(self.url)
        self.assertTemplateUsed(response, "gitinator/browse_tree.html")

    def test_shows_blob_entry(self):
        response = self.client.get(self.url)
        self.assertContains(response, "hello.txt")

    def test_shows_tree_entry(self):
        response = self.client.get(self.url)
        self.assertContains(response, "subdir")

    def test_returns_200_for_explicit_branch_param(self):
        response = self.client.get(self.url, {"branch": "main"})
        self.assertEqual(response.status_code, 200)

    def test_returns_200_for_tag_param(self):
        commit = self.repo.git_objects.get(sha=_COMMIT_SHA)
        GitRef.objects.create(
            repository=self.repo,
            name="v1.0",
            type=GitRef.Type.TAG,
            git_object=commit,
        )
        response = self.client.get(self.url, {"tag": "v1.0"})
        self.assertEqual(response.status_code, 200)

    def test_returns_200_for_commit_param(self):
        response = self.client.get(self.url, {"commit": _COMMIT_SHA})
        self.assertEqual(response.status_code, 200)

    def test_multiple_params_returns_400(self):
        response = self.client.get(self.url, {"branch": "main", "tag": "v1.0"})
        self.assertEqual(response.status_code, 400)

    def test_branch_and_commit_params_returns_400(self):
        response = self.client.get(self.url, {"branch": "main", "commit": _COMMIT_SHA})
        self.assertEqual(response.status_code, 400)

    def test_all_three_params_returns_400(self):
        response = self.client.get(
            self.url, {"branch": "main", "tag": "v1.0", "commit": _COMMIT_SHA}
        )
        self.assertEqual(response.status_code, 400)

    def test_returns_404_for_missing_repo(self):
        url = url_for("browse", kwargs={"group_name": "myorg", "repo_name": "missing"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_returns_404_for_missing_branch(self):
        response = self.client.get(self.url, {"branch": "nonexistent"})
        self.assertEqual(response.status_code, 404)

    def test_returns_404_for_missing_tag(self):
        response = self.client.get(self.url, {"tag": "nonexistent"})
        self.assertEqual(response.status_code, 404)

    def test_returns_404_for_missing_commit(self):
        response = self.client.get(self.url, {"commit": "f" * 40})
        self.assertEqual(response.status_code, 404)

    def test_entry_links_include_branch_query(self):
        response = self.client.get(self.url, {"branch": "main"})
        self.assertContains(response, "?branch=main")

    def test_entry_links_include_tag_query(self):
        commit = self.repo.git_objects.get(sha=_COMMIT_SHA)
        GitRef.objects.create(
            repository=self.repo,
            name="v1.0",
            type=GitRef.Type.TAG,
            git_object=commit,
        )
        response = self.client.get(self.url, {"tag": "v1.0"})
        self.assertContains(response, "?tag=v1.0")

    def test_returns_405_for_post(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 405)


class BrowseBlobTest(TestCase):
    def setUp(self):
        self.repo = _make_browse_fixture()

    def _blob_url(self, path):
        return url_for(
            "browse_path",
            kwargs={
                "group_name": self.repo.group_name,
                "repo_name": self.repo.name,
                "path": path,
            },
        )

    def test_returns_200_for_text_blob(self):
        response = self.client.get(self._blob_url("hello.txt"))
        self.assertEqual(response.status_code, 200)

    def test_uses_browse_blob_template(self):
        response = self.client.get(self._blob_url("hello.txt"))
        self.assertTemplateUsed(response, "gitinator/browse_blob.html")

    def test_shows_text_content(self):
        response = self.client.get(self._blob_url("hello.txt"))
        self.assertContains(response, "hello world")

    def test_binary_blob_does_not_show_content(self):
        response = self.client.get(self._blob_url("binary.bin"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Binary file not shown.")
        self.assertNotContains(response, "PNG")

    def test_returns_404_for_missing_file(self):
        response = self.client.get(self._blob_url("missing.txt"))
        self.assertEqual(response.status_code, 404)


class BrowseSubdirectoryTest(TestCase):
    def setUp(self):
        self.repo = _make_browse_fixture()

    def _url(self, path):
        return url_for(
            "browse_path",
            kwargs={
                "group_name": self.repo.group_name,
                "repo_name": self.repo.name,
                "path": path,
            },
        )

    def test_returns_200_for_subdirectory(self):
        response = self.client.get(self._url("subdir"))
        self.assertEqual(response.status_code, 200)

    def test_subdirectory_uses_tree_template(self):
        response = self.client.get(self._url("subdir"))
        self.assertTemplateUsed(response, "gitinator/browse_tree.html")

    def test_subdirectory_shows_its_entries(self):
        response = self.client.get(self._url("subdir"))
        self.assertContains(response, "readme.md")

    def test_returns_200_for_blob_in_subdir(self):
        response = self.client.get(self._url("subdir/readme.md"))
        self.assertEqual(response.status_code, 200)

    def test_blob_in_subdir_shows_content(self):
        response = self.client.get(self._url("subdir/readme.md"))
        self.assertContains(response, "readme content")

    def test_returns_404_for_path_beyond_blob(self):
        # hello.txt is a blob; traversing into it should 404
        response = self.client.get(self._url("hello.txt/extra"))
        self.assertEqual(response.status_code, 404)

    def test_returns_404_for_missing_subdirectory(self):
        response = self.client.get(self._url("nosuchdir"))
        self.assertEqual(response.status_code, 404)

    def test_breadcrumb_contains_repo_name(self):
        response = self.client.get(self._url("subdir"))
        self.assertContains(response, self.repo.name)

    def test_breadcrumb_contains_subdir_name(self):
        response = self.client.get(self._url("subdir"))
        self.assertContains(response, "subdir")
