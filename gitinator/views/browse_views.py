"""Browse views for exploring a repository's file tree."""

from django.core.exceptions import BadRequest
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET

from gitinator import git
from gitinator.models import GitObject, GitRef, Repo


def _is_text(data: bytes) -> bool:
    return b"\x00" not in data[:8192]


@require_GET
def browse(request, group_name, repo_name, path=""):
    """Display the tree or blob at path within a repository.

    Query parameters (at most one may be specified):
      branch=<name>   resolve via a branch ref
      tag=<name>      resolve via a tag ref
      commit=<sha>    resolve a specific commit SHA

    Defaults to the repository's default branch when none are provided.
    """
    branch = request.GET.get("branch")
    tag = request.GET.get("tag")
    commit_sha = request.GET.get("commit")

    if sum(x is not None for x in [branch, tag, commit_sha]) > 1:
        raise BadRequest("Specify at most one of: branch, tag, commit")

    try:
        repo = Repo.objects.get(group_name=group_name, name=repo_name)
    except Repo.DoesNotExist:
        raise Http404 from None

    try:
        if branch is not None:
            ref = GitRef.objects.select_related("git_object").get(
                repository=repo, name=branch, type=GitRef.Type.BRANCH
            )
            commit_obj = ref.git_object
        elif tag is not None:
            ref = GitRef.objects.select_related("git_object").get(
                repository=repo, name=tag, type=GitRef.Type.TAG
            )
            commit_obj = ref.git_object
        elif commit_sha is not None:
            commit_obj = GitObject.objects.get(
                repository=repo, sha=commit_sha, type=GitObject.Type.COMMIT
            )
        else:
            ref = GitRef.objects.select_related("git_object").get(
                repository=repo, name=repo.default_branch, type=GitRef.Type.BRANCH
            )
            commit_obj = ref.git_object
    except (GitRef.DoesNotExist, GitObject.DoesNotExist):
        raise Http404 from None

    commit_data = git.parse_commit(bytes(commit_obj.data))

    try:
        tree_obj = GitObject.objects.get(
            repository=repo, sha=commit_data.tree, type=GitObject.Type.TREE
        )
    except GitObject.DoesNotExist:
        raise Http404 from None

    path_parts = [p for p in path.split("/") if p] if path else []

    if branch is not None:
        ref_query = f"?branch={branch}"
    elif tag is not None:
        ref_query = f"?tag={tag}"
    elif commit_sha is not None:
        ref_query = f"?commit={commit_sha}"
    else:
        ref_query = ""

    base_url = reverse(
        "browse", kwargs={"group_name": group_name, "repo_name": repo_name}
    )
    if not path_parts:
        breadcrumbs = [{"label": repo.name, "url": None}]
    else:
        breadcrumbs = [{"label": repo.name, "url": base_url + ref_query}]
        for i in range(len(path_parts) - 1):
            sub_path = "/".join(path_parts[: i + 1])
            url = reverse(
                "browse_path",
                kwargs={
                    "group_name": group_name,
                    "repo_name": repo_name,
                    "path": sub_path,
                },
            )
            breadcrumbs.append({"label": path_parts[i], "url": url + ref_query})
        breadcrumbs.append({"label": path_parts[-1], "url": None})

    path_prefix = "/".join(path_parts) + "/" if path_parts else ""
    entry_url_base = f"/repos/{group_name}/{repo_name}/browse/{path_prefix}"

    current_tree = tree_obj
    for i, part in enumerate(path_parts):
        entries = git.parse_tree(bytes(current_tree.data))
        entry = next((e for e in entries if e.name == part), None)
        if entry is None:
            raise Http404 from None
        try:
            obj = GitObject.objects.get(repository=repo, sha=entry.sha)
        except GitObject.DoesNotExist:
            raise Http404 from None
        if entry.type == "blob":
            if i < len(path_parts) - 1:
                raise Http404 from None
            blob_data = bytes(obj.data)
            text = _is_text(blob_data)
            return render(
                request,
                "gitinator/browse_blob.html",
                {
                    "repo": repo,
                    "path_parts": path_parts,
                    "breadcrumbs": breadcrumbs,
                    "filename": part,
                    "is_text": text,
                    "content": blob_data.decode("utf-8", errors="replace")
                    if text
                    else None,
                    "commit_obj": commit_obj,
                    "ref_query": ref_query,
                },
            )
        current_tree = obj

    entries = git.parse_tree(bytes(current_tree.data))
    return render(
        request,
        "gitinator/browse_tree.html",
        {
            "repo": repo,
            "path_parts": path_parts,
            "breadcrumbs": breadcrumbs,
            "entries": entries,
            "entry_url_base": entry_url_base,
            "commit_obj": commit_obj,
            "ref_query": ref_query,
        },
    )
