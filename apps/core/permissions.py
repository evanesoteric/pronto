"""
Permission classes for DRF viewsets.

Two independent axes:
  - Facility access: does the user's `facilities` M2M include the object's
    facility (or is the user a superuser)?
  - Role: does the user's `role` match what the view requires?

Both are enforced at the view layer. The ORM layer enforces facility
scoping via FacilityScopedManager; the two should agree.
"""
from rest_framework.permissions import BasePermission, SAFE_METHODS


class HasFacilityAccess(BasePermission):
    """
    Object-level permission: the object's `.facility` must be one of the
    user's facilities, unless the user is a superuser.

    Views should combine this with queryset filtering for list actions —
    this class only fires on detail actions (retrieve, update, destroy,
    custom actions on a single object).
    """
    message = "You do not have access to this facility."

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True

        facility = getattr(obj, "facility", None)
        if facility is None:
            # Objects without a facility FK (e.g. Item) are visible
            # to anyone authenticated — the ledger scoping happens at
            # the lot level, not the item level.
            return True

        return request.user.facilities.filter(pk=facility.pk).exists()


class RoleRequired(BasePermission):
    """
    View-level permission: `view.required_roles` must include the
    user's role, unless the user is a superuser.

    If `required_roles` is not set on the view, this permission passes
    (i.e. it's a no-op and only the other permissions apply).
    """
    message = "Your role does not permit this action."

    def has_permission(self, request, view):
        if request.user.is_superuser:
            return True

        required = getattr(view, "required_roles", None)
        if not required:
            return True

        return request.user.role in required


class ReadOnly(BasePermission):
    """
    Allow only safe methods (GET, HEAD, OPTIONS). Useful for viewsets
    where the ledger is append-only through services but readable
    through the API.
    """
    message = "This resource is read-only through the API."

    def has_permission(self, request, view):
        return request.method in SAFE_METHODS


class IsBrewerOrAdmin(BasePermission):
    """Convenience class for the common production write permission."""
    message = "Only brewers and admins may perform this action."

    def has_permission(self, request, view):
        if request.user.is_superuser:
            return True
        return request.user.role in ("brewer", "admin")
