from django.contrib import admin

from .models import Batch, Recipe, RecipeIngredient, Tank


@admin.register(Tank)
class TankAdmin(admin.ModelAdmin):
    list_display = ("name", "facility", "capacity_liters", "status")
    list_filter = ("facility", "status")


class RecipeIngredientInline(admin.TabularInline):
    model = RecipeIngredient
    extra = 0


@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = ("name", "version", "style", "target_abv")
    inlines = [RecipeIngredientInline]


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ("batch_number", "recipe", "facility",
                    "status", "brew_date", "packaged_at")
    list_filter = ("status", "facility")
    search_fields = ("batch_number", "recipe__name")
    readonly_fields = ("created_at", "updated_at")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(facility__in=request.user.facilities.all())

    def has_change_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        if obj is None:
            return request.user.role in ("brewer", "admin")
        return (
            request.user.role in ("brewer", "admin")
            and request.user.facilities.filter(pk=obj.facility_id).exists()
        )
