from django.db import models


class FacilityScopedQuerySet(models.QuerySet):
    """
    Mixin providing `.for_user(user)`.

    Superusers see everything. Everyone else sees only rows whose
    `facility` FK is in their `facilities` M2M.

    Views must call `.for_user(request.user)` explicitly. We don't
    auto-apply this in a default manager because that would silently
    break admin and management commands.
    """
    def for_user(self, user):
        if user.is_superuser:
            return self
        return self.filter(facility__in=user.facilities.all())


class FacilityScopedManager(models.Manager.from_queryset(FacilityScopedQuerySet)):
    """Manager variant for models with a `facility` FK."""
    pass
