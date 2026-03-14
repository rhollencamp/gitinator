from django.test import TestCase
from django.urls import reverse

from gitinator import pktline
from gitinator.models import GitObject, GitRef, Repo

COMMIT_SHA = "a" * 40


class InfoRefsViewTest(TestCase):
    def setUp(self):
        self.repo = Repo.objects.create(
            group_name="myorg",
            name="myrepo",
            default_branch="main",
        )
        self.commit = GitObject.objects.create(
            repository=self.repo,
            sha=COMMIT_SHA,
            type=GitObject.Type.COMMIT,
            data=b"",
        )
        GitRef.objects.create(
            repository=self.repo,
            name="main",
            type=GitRef.Type.BRANCH,
            git_object=self.commit,
        )
        self.url = reverse(
            "info_refs", kwargs={"group_name": "myorg", "repo_name": "myrepo"}
        )

    def _get_info_refs(self, service="git-upload-pack"):
        return self.client.get(self.url, {"service": service})

    def test_returns_200_for_git_upload_pack(self):
        response = self._get_info_refs()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"], "application/x-git-upload-pack-advertisement"
        )

    def test_returns_400_for_unsupported_service(self):
        response = self._get_info_refs(service="git-receive-pack")
        self.assertEqual(response.status_code, 400)

    def test_returns_405_for_post(self):
        response = self.client.post(self.url, {"service": "git-upload-pack"})
        self.assertEqual(response.status_code, 405)

    def test_response_body_starts_with_service_header(self):
        response = self._get_info_refs()
        lines = pktline.decode(response.content)
        self.assertEqual(lines[0], b"# service=git-upload-pack\n")
        self.assertIsNone(lines[1])  # flush packet

    def test_response_body_advertises_head(self):
        response = self._get_info_refs()
        lines = pktline.decode(response.content)
        # HEAD line is first ref (after service header + flush), contains sha and symref capability
        head_line = lines[2]
        sha, rest = head_line.split(b" ", 1)
        ref_name, capabilities = rest.split(b"\x00", 1)
        self.assertEqual(sha.decode(), COMMIT_SHA)
        self.assertEqual(ref_name, b"HEAD")
        self.assertIn(b"symref=HEAD:refs/heads/main", capabilities)

    def test_response_body_advertises_branch(self):
        response = self._get_info_refs()
        lines = pktline.decode(response.content)
        ref_lines = [l for l in lines[2:] if l is not None]
        branch_line = next(
            l for l in ref_lines if b"refs/heads/main" in l and b"\x00" not in l
        )
        sha, ref_name = branch_line.rstrip(b"\n").split(b" ", 1)
        self.assertEqual(sha.decode(), COMMIT_SHA)
        self.assertEqual(ref_name, b"refs/heads/main")

    def test_response_body_ends_with_flush(self):
        response = self._get_info_refs()
        lines = pktline.decode(response.content)
        self.assertIsNone(lines[-1])
