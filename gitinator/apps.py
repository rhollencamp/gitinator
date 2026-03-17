"""Django app configuration for gitinator."""

from django.apps import AppConfig


class GitinatorConfig(AppConfig):
    """App config that registers server-side hooks on startup."""

    name = "gitinator"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from gitinator.hooks.protect_default_branch import update_hook
        from gitinator.hooks.registry import register_update_hook

        register_update_hook(update_hook)
