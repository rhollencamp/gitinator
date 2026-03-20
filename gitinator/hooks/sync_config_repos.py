"""Post-receive hook that syncs repository definitions from the config repo."""


def post_receive_hook(repo, ref_updates):
    """Sync Repo objects from config when gitinator/config's default branch is updated.

    Fires after a successful push. Only acts when the pushed repo is
    gitinator/config and the default branch is among the updated refs.
    """
    if repo.group_name != "gitinator" or repo.name != "config":
        return

    default_branch_ref = f"refs/heads/{repo.default_branch}"
    if not any(refname == default_branch_ref for _, _, refname in ref_updates):
        return

    # Deferred to avoid importing models before the Django app registry is ready.
    from gitinator.config_sync import sync_repos_from_config

    sync_repos_from_config(repo)
