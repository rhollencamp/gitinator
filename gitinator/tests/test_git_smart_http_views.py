import hashlib
import struct

from django.test import TestCase
from django.urls import reverse as url_for

from gitinator import pktline
from gitinator.tests.factories import COMMIT_SHA, make_repo_fixture


class InfoRefsViewTest(TestCase):
    def setUp(self):
        fixture = make_repo_fixture()
        self.repo = fixture.repo
        self.commit = fixture.commit
        self.url = url_for(
            "info_refs",
            kwargs={"group_name": self.repo.group_name, "repo_name": self.repo.name},
        )

    def _get_info_refs(self, service="git-upload-pack"):
        return self.client.get(self.url, {"service": service})

    def test_returns_200_for_git_upload_pack(self):
        response = self._get_info_refs()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"], "application/x-git-upload-pack-advertisement"
        )

    def test_cache_control_is_no_cache(self):
        response = self._get_info_refs()
        self.assertEqual(response["Cache-Control"], "no-cache")

    def test_returns_404_for_missing_repo(self):
        url = url_for(
            "info_refs", kwargs={"group_name": "myorg", "repo_name": "missing"}
        )
        response = self.client.get(url, {"service": "git-upload-pack"})
        self.assertEqual(response.status_code, 404)

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
        ref_lines = [line for line in lines[2:] if line is not None]
        branch_line = next(
            line
            for line in ref_lines
            if b"refs/heads/main" in line and b"\x00" not in line
        )
        sha, ref_name = branch_line.rstrip(b"\n").split(b" ", 1)
        self.assertEqual(sha.decode(), COMMIT_SHA)
        self.assertEqual(ref_name, b"refs/heads/main")

    def test_response_body_ends_with_flush(self):
        response = self._get_info_refs()
        lines = pktline.decode(response.content)
        self.assertIsNone(lines[-1])


class UploadPackViewTest(TestCase):
    def setUp(self):
        fixture = make_repo_fixture()
        self.repo = fixture.repo
        self.blob = fixture.blob
        self.tree = fixture.tree
        self.commit = fixture.commit
        self.url = url_for(
            "upload_pack",
            kwargs={"group_name": self.repo.group_name, "repo_name": self.repo.name},
        )

    def _build_request_body(self, wants, capabilities=None):
        body = b""
        for i, sha in enumerate(wants):
            line = f"want {sha}".encode()
            if i == 0 and capabilities:
                line += b"\x00" + b" ".join(capabilities)
            line += b"\n"
            body += pktline.encode(line)
        body += pktline.flush()
        body += pktline.encode(b"done\n")
        return body

    def _post_upload_pack(self, wants=None):
        if wants is None:
            wants = [COMMIT_SHA]
        return self.client.post(
            self.url,
            data=self._build_request_body(wants),
            content_type="application/x-git-upload-pack-request",
        )

    def _parse_pack(self, response_content):
        """Return raw PACK bytes from the response (strip leading NAK pktline)."""
        nak_line = pktline.encode(b"NAK\n")
        self.assertTrue(response_content.startswith(nak_line))
        return response_content[len(nak_line) :]

    def test_returns_200_for_valid_request(self):
        response = self._post_upload_pack()
        self.assertEqual(response.status_code, 200)

    def test_cache_control_is_no_cache(self):
        response = self._post_upload_pack()
        self.assertEqual(response["Cache-Control"], "no-cache")

    def test_returns_correct_content_type(self):
        response = self._post_upload_pack()
        self.assertEqual(
            response["Content-Type"], "application/x-git-upload-pack-result"
        )

    def test_returns_405_for_get(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)

    def test_response_starts_with_nak(self):
        response = self._post_upload_pack()
        nak_line = pktline.encode(b"NAK\n")
        self.assertTrue(response.content.startswith(nak_line))

    def test_response_contains_pack_after_nak(self):
        response = self._post_upload_pack()
        pack_data = self._parse_pack(response.content)
        self.assertTrue(pack_data.startswith(b"PACK"))

    def test_pack_version_is_2(self):
        response = self._post_upload_pack()
        pack_data = self._parse_pack(response.content)
        version = struct.unpack(">I", pack_data[4:8])[0]
        self.assertEqual(version, 2)

    def test_pack_object_count(self):
        response = self._post_upload_pack()
        pack_data = self._parse_pack(response.content)
        count = struct.unpack(">I", pack_data[8:12])[0]
        self.assertEqual(count, 3)  # blob + tree + commit

    def test_pack_checksum_is_valid(self):
        response = self._post_upload_pack()
        pack_data = self._parse_pack(response.content)
        expected = hashlib.sha1(pack_data[:-20]).digest()
        self.assertEqual(pack_data[-20:], expected)

    def test_returns_404_for_missing_repo(self):
        url = url_for(
            "upload_pack", kwargs={"group_name": "myorg", "repo_name": "missing"}
        )
        response = self.client.post(
            url,
            data=self._build_request_body([COMMIT_SHA]),
            content_type="application/x-git-upload-pack-request",
        )
        self.assertEqual(response.status_code, 404)
