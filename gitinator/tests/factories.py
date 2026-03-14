"""
Test factories for creating model instances.

Use the individual helpers (make_repo, make_git_object, make_branch) to create
specific objects, or make_repo_fixture() to get a fully wired-up repo with a
blob, tree, commit, and branch in one call.
"""

from dataclasses import dataclass

from gitinator.models import GitObject, GitRef, Repo

COMMIT_SHA = "a" * 40
TREE_SHA = "c" * 40
BLOB_SHA = "b" * 40


def make_repo(group_name="myorg", name="myrepo", default_branch="main"):
    return Repo.objects.create(
        group_name=group_name,
        name=name,
        default_branch=default_branch,
    )


def make_git_object(repo, sha, type=GitObject.Type.COMMIT, data=b""):
    return GitObject.objects.create(
        repository=repo,
        sha=sha,
        type=type,
        data=data,
    )


def make_branch(repo, name, git_object):
    return GitRef.objects.create(
        repository=repo,
        name=name,
        type=GitRef.Type.BRANCH,
        git_object=git_object,
    )


@dataclass
class RepoFixture:
    repo: Repo
    blob: GitObject
    tree: GitObject
    commit: GitObject
    branch: GitRef


def make_repo_fixture(
    group_name="myorg",
    name="myrepo",
    default_branch="main",
    blob_sha=BLOB_SHA,
    tree_sha=TREE_SHA,
    commit_sha=COMMIT_SHA,
):
    repo = make_repo(group_name=group_name, name=name, default_branch=default_branch)
    blob = make_git_object(
        repo, blob_sha, type=GitObject.Type.BLOB, data=b"hello world"
    )
    tree = make_git_object(repo, tree_sha, type=GitObject.Type.TREE, data=b"tree data")
    commit = make_git_object(
        repo, commit_sha, type=GitObject.Type.COMMIT, data=b"commit data"
    )
    branch = make_branch(repo, default_branch, commit)
    return RepoFixture(repo=repo, blob=blob, tree=tree, commit=commit, branch=branch)
