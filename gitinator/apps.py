"""Django app configuration"""

from django.apps import AppConfig


class GitinatorConfig(AppConfig):
    name = "gitinator"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.db.models.signals import post_migrate

        from gitinator.bootstrap import ensure_config_repo

        post_migrate.connect(ensure_config_repo, sender=self)
