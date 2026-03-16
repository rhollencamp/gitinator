import hashlib
import struct

from django.test import TestCase
from django.urls import reverse as url_for

from gitinator import pack, pktline
from gitinator.models import GitObject, GitRef
from gitinator.tests.factories import (
    COMMIT_SHA,
    make_branch,
    make_git_object,
    make_repo,
    make_repo_fixture,
)


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

    def test_returns_403_for_unsupported_service(self):
        response = self._get_info_refs(service="git-unknown-service")
        self.assertEqual(response.status_code, 403)

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
        # HEAD line is first ref (after service header + flush), contains sha
        # and symref capability
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

    def test_empty_repo_advertises_capabilities_only(self):
        empty_repo = make_repo(group_name="myorg", name="emptyrepo")
        url = url_for(
            "info_refs",
            kwargs={"group_name": empty_repo.group_name, "repo_name": empty_repo.name},
        )
        response = self.client.get(url, {"service": "git-upload-pack"})
        self.assertEqual(response.status_code, 200)
        lines = pktline.decode(response.content)
        # Should have: service header, flush, capabilities^{} line, flush
        self.assertEqual(lines[0], b"# service=git-upload-pack\n")
        self.assertIsNone(lines[1])
        caps_line = lines[2]
        self.assertIn(b"capabilities^{}", caps_line)
        self.assertIn(b"symref=HEAD:refs/heads/main", caps_line)
        self.assertIsNone(lines[3])

    def test_head_uses_default_branch_not_first_alphabetically(self):
        # "alpha" sorts before "main" but default_branch is "main"
        other_sha = "d" * 40
        other_commit = make_git_object(
            self.repo, other_sha, type=GitObject.Type.COMMIT, data=b"other"
        )
        make_branch(self.repo, "alpha", other_commit)

        response = self._get_info_refs()
        lines = pktline.decode(response.content)
        head_line = lines[2]
        sha, rest = head_line.split(b" ", 1)
        ref_name, capabilities = rest.split(b"\x00", 1)
        self.assertEqual(sha.decode(), COMMIT_SHA)
        self.assertEqual(ref_name, b"HEAD")
        self.assertIn(b"symref=HEAD:refs/heads/main", capabilities)


class ReceivePackInfoRefsTest(TestCase):
    def setUp(self):
        fixture = make_repo_fixture()
        self.repo = fixture.repo
        self.commit = fixture.commit
        self.url = url_for(
            "info_refs",
            kwargs={"group_name": self.repo.group_name, "repo_name": self.repo.name},
        )

    def _get_info_refs(self):
        return self.client.get(self.url, {"service": "git-receive-pack"})

    def test_returns_200(self):
        response = self._get_info_refs()
        self.assertEqual(response.status_code, 200)

    def test_returns_correct_content_type(self):
        response = self._get_info_refs()
        self.assertEqual(
            response["Content-Type"], "application/x-git-receive-pack-advertisement"
        )

    def test_cache_control_is_no_cache(self):
        response = self._get_info_refs()
        self.assertEqual(response["Cache-Control"], "no-cache")

    def test_response_starts_with_service_header_and_flush(self):
        response = self._get_info_refs()
        lines = pktline.decode(response.content)
        self.assertEqual(lines[0], b"# service=git-receive-pack\n")
        self.assertIsNone(lines[1])  # flush packet

    def test_response_advertises_refs(self):
        response = self._get_info_refs()
        lines = pktline.decode(response.content)
        # First ref line is after service header (index 0) + flush (index 1)
        first_ref_line = lines[2]
        # Should contain a SHA and ref name with NUL-separated capabilities
        self.assertIn(b"refs/heads/", first_ref_line)
        self.assertIn(b"\x00", first_ref_line)  # capabilities separator

    def test_response_ends_with_flush(self):
        response = self._get_info_refs()
        lines = pktline.decode(response.content)
        self.assertIsNone(lines[-1])

    def test_empty_repo_advertises_capabilities_only(self):
        empty_repo = make_repo(group_name="myorg", name="emptyrepo")
        url = url_for(
            "info_refs",
            kwargs={"group_name": empty_repo.group_name, "repo_name": empty_repo.name},
        )
        response = self.client.get(url, {"service": "git-receive-pack"})
        self.assertEqual(response.status_code, 200)
        lines = pktline.decode(response.content)
        # Should have: service header, flush, capabilities^{} line, flush
        self.assertEqual(lines[0], b"# service=git-receive-pack\n")
        self.assertIsNone(lines[1])
        caps_line = lines[2]
        self.assertIn(b"capabilities^{}", caps_line)
        self.assertIsNone(lines[3])


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


_NULL_SHA = "0" * 40


def _git_sha(obj_type, data):
    """Compute the git SHA-1 for an object: sha1("<type> <size>\\0<data>")."""
    header = f"{obj_type} {len(data)}\x00".encode()
    return hashlib.sha1(header + data, usedforsecurity=False).hexdigest()


class ReceivePackViewTest(TestCase):
    NEW_COMMIT_DATA = b"new commit"
    NEW_COMMIT_SHA = _git_sha(GitObject.Type.COMMIT, NEW_COMMIT_DATA)

    def setUp(self):
        fixture = make_repo_fixture()
        self.repo = fixture.repo
        self.existing_commit = fixture.commit
        self.existing_branch = fixture.branch
        self.url = url_for(
            "receive_pack",
            kwargs={"group_name": self.repo.group_name, "repo_name": self.repo.name},
        )

    def _build_pack(self, objects):
        """Build a PACK file from a list of (type_str, data) tuples."""

        class FakeObj:
            def __init__(self, type_, data):
                self.type = type_
                self.data = data

        return pack.build([FakeObj(t, d) for t, d in objects])

    def _build_request_body(self, commands, pack_data=b""):
        """Build a receive-pack request body: pkt-line commands + raw PACK."""
        body = b""
        for i, (old_sha, new_sha, refname) in enumerate(commands):
            if i == 0:
                line = (
                    f"{old_sha} {new_sha} {refname}".encode() + b"\x00report-status\n"
                )
            else:
                line = f"{old_sha} {new_sha} {refname}".encode() + b"\n"
            body += pktline.encode(line)
        body += pktline.flush()
        body += pack_data
        return body

    def _post_receive_pack(self, commands, pack_data=b""):
        return self.client.post(
            self.url,
            data=self._build_request_body(commands, pack_data),
            content_type="application/x-git-receive-pack-request",
        )

    def _parse_response(self, content):
        """Return list of pkt-line payloads from response (excluding flush)."""
        return [line for line in pktline.decode(content) if line is not None]

    def test_returns_405_for_get(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)

    def test_returns_404_for_missing_repo(self):
        url = url_for(
            "receive_pack", kwargs={"group_name": "myorg", "repo_name": "missing"}
        )
        response = self.client.post(
            url,
            data=self._build_request_body(
                [(_NULL_SHA, self.NEW_COMMIT_SHA, "refs/heads/new-branch")]
            ),
            content_type="application/x-git-receive-pack-request",
        )
        self.assertEqual(response.status_code, 404)

    def test_returns_200_for_valid_push(self):
        pack_data = self._build_pack([(GitObject.Type.COMMIT, self.NEW_COMMIT_DATA)])
        response = self._post_receive_pack(
            [(_NULL_SHA, self.NEW_COMMIT_SHA, "refs/heads/new-branch")],
            pack_data,
        )
        self.assertEqual(response.status_code, 200)

    def test_returns_correct_content_type(self):
        pack_data = self._build_pack([(GitObject.Type.COMMIT, self.NEW_COMMIT_DATA)])
        response = self._post_receive_pack(
            [(_NULL_SHA, self.NEW_COMMIT_SHA, "refs/heads/new-branch")],
            pack_data,
        )
        self.assertEqual(
            response["Content-Type"], "application/x-git-receive-pack-result"
        )

    def test_cache_control_is_no_cache(self):
        pack_data = self._build_pack([(GitObject.Type.COMMIT, self.NEW_COMMIT_DATA)])
        response = self._post_receive_pack(
            [(_NULL_SHA, self.NEW_COMMIT_SHA, "refs/heads/new-branch")],
            pack_data,
        )
        self.assertEqual(response["Cache-Control"], "no-cache")

    def test_response_contains_unpack_ok(self):
        pack_data = self._build_pack([(GitObject.Type.COMMIT, self.NEW_COMMIT_DATA)])
        response = self._post_receive_pack(
            [(_NULL_SHA, self.NEW_COMMIT_SHA, "refs/heads/new-branch")],
            pack_data,
        )
        lines = self._parse_response(response.content)
        self.assertIn(b"unpack ok\n", lines)

    def test_response_contains_ref_status_ok(self):
        pack_data = self._build_pack([(GitObject.Type.COMMIT, self.NEW_COMMIT_DATA)])
        response = self._post_receive_pack(
            [(_NULL_SHA, self.NEW_COMMIT_SHA, "refs/heads/new-branch")],
            pack_data,
        )
        lines = self._parse_response(response.content)
        self.assertIn(b"ok refs/heads/new-branch\n", lines)

    def test_creates_new_branch(self):
        pack_data = self._build_pack([(GitObject.Type.COMMIT, self.NEW_COMMIT_DATA)])
        self._post_receive_pack(
            [(_NULL_SHA, self.NEW_COMMIT_SHA, "refs/heads/new-branch")],
            pack_data,
        )
        from gitinator.models import GitRef

        self.assertTrue(
            GitRef.objects.filter(
                repository=self.repo, name="new-branch", type=GitRef.Type.BRANCH
            ).exists()
        )

    def test_creates_git_objects_from_pack(self):
        pack_data = self._build_pack(
            [
                (GitObject.Type.BLOB, b"new blob"),
                (GitObject.Type.TREE, b"new tree"),
                (GitObject.Type.COMMIT, self.NEW_COMMIT_DATA),
            ]
        )
        self._post_receive_pack(
            [(_NULL_SHA, self.NEW_COMMIT_SHA, "refs/heads/new-branch")],
            pack_data,
        )
        # 3 original + 3 new = 6 total
        self.assertEqual(self.repo.git_objects.count(), 6)

    def test_updates_existing_ref(self):
        pack_data = self._build_pack([(GitObject.Type.COMMIT, self.NEW_COMMIT_DATA)])
        self._post_receive_pack(
            [(COMMIT_SHA, self.NEW_COMMIT_SHA, "refs/heads/main")],
            pack_data,
        )
        from gitinator.models import GitRef

        ref = GitRef.objects.get(repository=self.repo, name="main")
        self.assertEqual(ref.git_object.sha, self.NEW_COMMIT_SHA)

    def test_deletes_ref_when_new_sha_is_zero(self):
        self._post_receive_pack(
            [(COMMIT_SHA, _NULL_SHA, "refs/heads/main")],
            b"",
        )
        from gitinator.models import GitRef

        self.assertFalse(
            GitRef.objects.filter(repository=self.repo, name="main").exists()
        )

    def test_stale_old_sha_on_update_returns_ng(self):
        wrong_old_sha = "e" * 40
        pack_data = self._build_pack([(GitObject.Type.COMMIT, self.NEW_COMMIT_DATA)])
        response = self._post_receive_pack(
            [(wrong_old_sha, self.NEW_COMMIT_SHA, "refs/heads/main")],
            pack_data,
        )
        lines = self._parse_response(response.content)
        self.assertIn(b"ng refs/heads/main stale ref\n", lines)

    def test_stale_old_sha_does_not_update_ref(self):
        wrong_old_sha = "e" * 40
        pack_data = self._build_pack([(GitObject.Type.COMMIT, self.NEW_COMMIT_DATA)])
        self._post_receive_pack(
            [(wrong_old_sha, self.NEW_COMMIT_SHA, "refs/heads/main")],
            pack_data,
        )
        from gitinator.models import GitRef

        ref = GitRef.objects.get(repository=self.repo, name="main")
        self.assertEqual(ref.git_object.sha, COMMIT_SHA)

    def test_missing_object_returns_ng(self):
        missing_sha = "f" * 40
        response = self._post_receive_pack(
            [(_NULL_SHA, missing_sha, "refs/heads/new-branch")],
            b"",
        )
        lines = self._parse_response(response.content)
        self.assertIn(b"ng refs/heads/new-branch object not found\n", lines)

    def test_stale_old_sha_on_delete_returns_ng(self):
        wrong_old_sha = "e" * 40
        response = self._post_receive_pack(
            [(wrong_old_sha, _NULL_SHA, "refs/heads/main")],
            b"",
        )
        lines = self._parse_response(response.content)
        self.assertIn(b"ng refs/heads/main stale ref\n", lines)

    def test_stale_old_sha_on_delete_does_not_delete_ref(self):
        wrong_old_sha = "e" * 40
        self._post_receive_pack(
            [(wrong_old_sha, _NULL_SHA, "refs/heads/main")],
            b"",
        )
        from gitinator.models import GitRef

        self.assertTrue(
            GitRef.objects.filter(repository=self.repo, name="main").exists()
        )

    def test_unsupported_ref_namespace_returns_ng(self):
        response = self._post_receive_pack(
            [(_NULL_SHA, self.NEW_COMMIT_SHA, "refs/notes/commits")],
            b"",
        )
        self.assertEqual(response.status_code, 200)
        lines = self._parse_response(response.content)
        self.assertIn(b"ng refs/notes/commits unsupported ref\n", lines)

    def test_sha_mismatch_returns_ng(self):
        # Pack contains an object whose real SHA differs from the claimed new_sha
        pack_data = self._build_pack([(GitObject.Type.COMMIT, self.NEW_COMMIT_DATA)])
        wrong_sha = "f" * 40
        response = self._post_receive_pack(
            [(_NULL_SHA, wrong_sha, "refs/heads/new-branch")],
            pack_data,
        )
        lines = self._parse_response(response.content)
        self.assertIn(b"ng refs/heads/new-branch object not found\n", lines)

    def test_sha_mismatch_does_not_create_ref(self):
        pack_data = self._build_pack([(GitObject.Type.COMMIT, self.NEW_COMMIT_DATA)])
        wrong_sha = "f" * 40
        self._post_receive_pack(
            [(_NULL_SHA, wrong_sha, "refs/heads/new-branch")],
            pack_data,
        )
        self.assertFalse(
            GitRef.objects.filter(repository=self.repo, name="new-branch").exists()
        )
