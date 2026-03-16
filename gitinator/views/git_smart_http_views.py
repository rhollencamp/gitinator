"""
Git HTTP protocol views.

Reference: https://git-scm.com/docs/gitprotocol-http
"""

from django.db import transaction
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseNotFound
from django.views.decorators.http import require_GET, require_POST

from gitinator import git, pack, pktline
from gitinator.models import GitObject, GitRef, Repo

_NULL_SHA = "0" * 40
_SUPPORTED_SERVICES = {"git-upload-pack", "git-receive-pack"}


@require_GET
def info_refs(request, group_name, repo_name):
    """
    Advertise repository refs for smart HTTP clients (dumb HTTP not supported).

    Responds to GET /group/repo.git/info/refs?service=<service>.
    Supports git-upload-pack and git-receive-pack.
    """
    service = request.GET.get("service")
    if service not in _SUPPORTED_SERVICES:
        return HttpResponseForbidden("Unsupported service")

    try:
        repo = Repo.objects.get(group_name=group_name, name=repo_name)
    except Repo.DoesNotExist:
        return HttpResponseNotFound()

    response = pktline.encode(f"# service={service}\n".encode()) + pktline.flush()

    if service == "git-upload-pack":
        response += _build_upload_pack_advertisement(repo)
    else:
        response += _build_receive_pack_advertisement(repo)

    response = HttpResponse(
        response, status=200, content_type=f"application/x-{service}-advertisement"
    )
    response["Cache-Control"] = "no-cache"
    return response


def _build_upload_pack_advertisement(repo):
    refs = list(repo.git_refs.select_related("git_object").order_by("type", "name"))

    if not refs:
        # Empty repo: advertise capabilities with null SHA
        null_sha = _NULL_SHA.encode()
        capabilities = f"symref=HEAD:refs/heads/{repo.default_branch}".encode()
        line = pktline.encode(null_sha + b" capabilities^{}\x00" + capabilities + b"\n")
        return line + pktline.flush()

    ref_lines = []
    default_branch = repo.default_branch
    default_ref = next(
        (r for r in refs if r.type == GitRef.Type.BRANCH and r.name == default_branch),
        None,
    )
    if default_ref is not None:
        capabilities = f"symref=HEAD:refs/heads/{default_branch}".encode()
        head_sha = default_ref.git_object.sha.encode()
        ref_lines.append(pktline.encode(head_sha + b" HEAD\x00" + capabilities + b"\n"))

    for ref in refs:
        full_name = git.ref_full_name(ref.type, ref.name).encode()
        sha = ref.git_object.sha.encode()
        ref_lines.append(pktline.encode(sha + b" " + full_name + b"\n"))

    return b"".join(ref_lines) + pktline.flush()


def _build_receive_pack_advertisement(repo):
    refs = list(repo.git_refs.select_related("git_object").order_by("type", "name"))
    capabilities = b"report-status delete-refs"

    if not refs:
        # Empty repo: advertise capabilities with null SHA
        null_sha = _NULL_SHA.encode()
        line = pktline.encode(null_sha + b" capabilities^{}\x00" + capabilities + b"\n")
        return line + pktline.flush()

    ref_lines = []
    for i, ref in enumerate(refs):
        full_name = git.ref_full_name(ref.type, ref.name).encode()
        sha = ref.git_object.sha.encode()
        if i == 0:
            ref_lines.append(
                pktline.encode(sha + b" " + full_name + b"\x00" + capabilities + b"\n")
            )
        else:
            ref_lines.append(pktline.encode(sha + b" " + full_name + b"\n"))

    return b"".join(ref_lines) + pktline.flush()


@require_POST
def receive_pack(request, group_name, repo_name):
    """
    Accept a git push: store incoming objects and update refs.

    Responds to POST /group/repo/git-receive-pack with a pkt-line status
    report (unpack ok + per-ref ok/error lines).
    """
    try:
        repo = Repo.objects.get(group_name=group_name, name=repo_name)
    except Repo.DoesNotExist:
        return HttpResponseNotFound()

    commands_raw, pack_data = pktline.decode_stream(request.body)

    # Parse ref-update commands. First line may have NUL-separated capabilities.
    commands = []
    for line in commands_raw:
        payload = line.split(b"\x00", 1)[0]  # strip capabilities
        payload = payload.rstrip(b"\n")
        old_sha, new_sha, refname = payload.split(b" ", 2)
        commands.append((old_sha.decode(), new_sha.decode(), refname.decode()))

    # Parse incoming objects and verify each object's SHA matches its content
    received_shas: set[str] = set()
    if pack_data:
        parsed_objects = pack.parse(pack_data)
        received_shas = {obj["sha"] for obj in parsed_objects}
        GitObject.objects.bulk_create(
            [
                GitObject(
                    repository=repo,
                    sha=obj["sha"],
                    type=obj["type"],
                    data=obj["data"],
                )
                for obj in parsed_objects
            ],
            ignore_conflicts=True,
        )

    # Verify each new_sha is either in the received pack or already in the repo.
    # This catches packs where object content doesn't match the claimed SHA.
    existing_shas = set(
        GitObject.objects.filter(
            repository=repo,
            sha__in=[new_sha for _, new_sha, _ in commands if new_sha != _NULL_SHA],
        ).values_list("sha", flat=True)
    )

    # Apply ref updates. Each command runs in its own atomic block with a
    # row-level lock so the stale-ref check and write are indivisible.
    ref_statuses = []  # list of (refname, "ok"|"ng", reason_or_None)
    for old_sha, new_sha, refname in commands:
        try:
            ref_type, ref_name = git.parse_refname(refname)
        except ValueError:
            ref_statuses.append((refname, "ng", "unsupported ref"))
            continue
        if (
            new_sha != _NULL_SHA
            and new_sha not in received_shas
            and new_sha not in existing_shas
        ):
            ref_statuses.append((refname, "ng", "object not found"))
            continue
        try:
            with transaction.atomic():
                if new_sha == _NULL_SHA:
                    # Delete: verify old_sha matches current value
                    qs = (
                        GitRef.objects.select_for_update()
                        .select_related("git_object")
                        .filter(repository=repo, name=ref_name, type=ref_type)
                    )
                    if old_sha != _NULL_SHA:
                        current = qs.first()
                        if current is None or current.git_object.sha != old_sha:
                            ref_statuses.append((refname, "ng", "stale ref"))
                            continue
                    qs.delete()
                elif old_sha == _NULL_SHA:
                    # Create
                    git_object = GitObject.objects.get(repository=repo, sha=new_sha)
                    GitRef.objects.create(
                        repository=repo,
                        name=ref_name,
                        type=ref_type,
                        git_object=git_object,
                    )
                else:
                    # Update: verify old_sha matches current value
                    qs = (
                        GitRef.objects.select_for_update()
                        .select_related("git_object")
                        .filter(repository=repo, name=ref_name, type=ref_type)
                    )
                    current = qs.first()
                    if current is None or current.git_object.sha != old_sha:
                        ref_statuses.append((refname, "ng", "stale ref"))
                        continue
                    git_object = GitObject.objects.get(repository=repo, sha=new_sha)
                    qs.update(git_object=git_object)
        except GitObject.DoesNotExist:
            ref_statuses.append((refname, "ng", "object not found"))
            continue
        ref_statuses.append((refname, "ok", None))

    body = pktline.encode(b"unpack ok\n")
    for refname, status, reason in ref_statuses:
        if status == "ok":
            body += pktline.encode(f"ok {refname}\n".encode())
        else:
            body += pktline.encode(f"ng {refname} {reason}\n".encode())
    body += pktline.flush()

    response = HttpResponse(body, content_type="application/x-git-receive-pack-result")
    response["Cache-Control"] = "no-cache"
    return response


@require_POST
def upload_pack(request, group_name, repo_name):
    """
    Serve a git pack file in response to a client's want/have negotiation.

    Responds to POST /group/repo/git-upload-pack with a pkt-line NAK followed
    by a PACK file containing all objects in the repository.
    """
    try:
        repo = Repo.objects.get(group_name=group_name, name=repo_name)
    except Repo.DoesNotExist:
        return HttpResponseNotFound()
    objects = list(repo.git_objects.all())

    # We always respond with NAK (no common base found) rather than negotiating
    # via ACK/have lines. This means we always send a full pack even if the client
    # already has some objects. Git clients handle duplicate objects gracefully, so
    # this is correct but wasteful on bandwidth for incremental fetches.
    body = pktline.encode(b"NAK\n") + pack.build(objects)

    response = HttpResponse(body, content_type="application/x-git-upload-pack-result")
    response["Cache-Control"] = "no-cache"
    return response
