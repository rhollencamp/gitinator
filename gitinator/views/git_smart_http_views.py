"""
Git HTTP protocol views.

Reference: https://git-scm.com/docs/gitprotocol-http
"""

from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotFound
from django.views.decorators.http import require_GET, require_POST

from gitinator import pack, pktline
from gitinator.models import GitRef, Repo


@require_GET
def info_refs(request, group_name, repo_name):
    """
    Advertise repository refs for smart HTTP clients (dumb HTTP not supported).

    Responds to GET /group/repo.git/info/refs?service=git-upload-pack.
    Returns a pkt-line stream: service header, flush, then one line per ref
    (HEAD first with capabilities, then branches/tags), terminated by a flush.
    """
    service = request.GET.get("service")
    if service != "git-upload-pack":
        return HttpResponseBadRequest("Only git-upload-pack is supported")

    try:
        repo = Repo.objects.get(group_name=group_name, name=repo_name)
    except Repo.DoesNotExist:
        return HttpResponseNotFound()
    refs = list(repo.git_refs.select_related("git_object").order_by("type", "name"))

    body = b""

    # Service header + flush
    body += pktline.encode(b"# service=git-upload-pack\n")
    body += pktline.flush()

    # Build ref advertisement lines
    ref_lines = []
    for ref in refs:
        if ref.type == GitRef.Type.BRANCH:
            full_name = f"refs/heads/{ref.name}".encode()
        else:
            full_name = f"refs/tags/{ref.name}".encode()

        sha = ref.git_object.sha.encode()

        if not ref_lines:
            # First ref is HEAD; include capabilities after NUL byte
            default_branch = repo.default_branch
            capabilities = f"symref=HEAD:refs/heads/{default_branch}".encode()
            ref_lines.append(pktline.encode(sha + b" HEAD\x00" + capabilities + b"\n"))

        ref_lines.append(pktline.encode(sha + b" " + full_name + b"\n"))

    for line in ref_lines:
        body += line

    body += pktline.flush()

    response = HttpResponse(
        body, status=200, content_type=f"application/x-{service}-advertisement"
    )
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
