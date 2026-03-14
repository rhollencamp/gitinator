from django.db import models


class Repo(models.Model):
    group_name = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    default_branch = models.CharField(max_length=255)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["name", "group_name"], name="unique_repo_name_per_group"
            ),
        ]


class GitObject(models.Model):
    class Type(models.TextChoices):
        BLOB = "blob"
        TREE = "tree"
        COMMIT = "commit"
        TAG = "tag"

    repository = models.ForeignKey(
        Repo, on_delete=models.CASCADE, related_name="git_objects"
    )
    sha = models.CharField(max_length=40)
    type = models.CharField(max_length=6, choices=Type.choices)
    data = models.BinaryField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["repository", "sha"], name="unique_git_object_sha_per_repo"
            ),
            models.CheckConstraint(
                condition=models.Q(type__in=["blob", "tree", "commit", "tag"]),
                name="valid_git_object_type",
            ),
        ]


class GitRef(models.Model):
    class Type(models.TextChoices):
        BRANCH = "branch"
        TAG = "tag"

    repository = models.ForeignKey(
        Repo, on_delete=models.CASCADE, related_name="git_refs"
    )
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=6, choices=Type.choices)
    git_object = models.ForeignKey(
        GitObject, on_delete=models.RESTRICT, related_name="git_refs"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["repository", "name", "type"], name="unique_git_ref_per_repo"
            ),
            models.CheckConstraint(
                condition=models.Q(type__in=["branch", "tag"]),
                name="valid_git_ref_type",
            ),
        ]
