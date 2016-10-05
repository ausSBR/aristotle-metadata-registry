from django.db.models import Q
from django.conf import settings
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.contrib.admin.filters import RelatedFieldListFilter
import aristotle_mdr.models as MDR
import aristotle_mdr.forms as MDRForms
from aristotle_mdr import perms
from django.core.urlresolvers import reverse
from reversion_compare.admin import CompareVersionAdmin

import reversion

from aristotle_mdr.register import register_concept
reversion.revisions.register(MDR.Status)
reversion.revisions.register(MDR._concept, follow=['statuses', 'workgroup'])
reversion.revisions.register(MDR.Workgroup)


class StatusInline(admin.TabularInline):
    """
    Inline editor for registration status records
    """

    model = MDR.Status
    form = MDRForms.admin.StatusInlineForm
    extra = 0

    """
    The default queryset will return all objects of a given type.
    This limits the returned Status Records to only those where
    they are in a Registration Authority in which the current user
    has permission to change the status of objects.
    """
    def get_queryset(self, request):
        qs = super(StatusInline, self).get_queryset(request)
        if not request.user.is_superuser:
            qs = qs.filter(registrationAuthority__in=request.user.registrar_in.all())
        return qs

    def has_change_permission(self, request, obj=None):
        if obj is not None:
            return perms.user_can_change_status(request.user, obj)
        return super(StatusInline, self).has_change_permission(request, obj=None)

    def has_add_permission(self, request):
        if perms.user_is_registrar(request.user):
            return True
        return super(StatusInline, self).has_add_permission(request)


class WorkgroupFilter(RelatedFieldListFilter):
    def __init__(self, field, request, *args, **kwargs):
        super(WorkgroupFilter, self).__init__(field, request, *args, **kwargs)
        if not request.user.is_superuser:
            self.lookup_choices = [(w.id, w) for w in request.user.profile.workgroups.all()]


class WorkgroupAdmin(CompareVersionAdmin):
    fieldsets = [
        (None, {'fields': ['name', 'definition']}),
        ('Members', {'fields': ['managers', 'stewards', 'submitters', 'viewers']}),
    ]
    filter_horizontal = ['managers', 'stewards', 'submitters', 'viewers']
    list_display = ('name', 'definition', 'archived')
    list_filter = ('archived',)
    search_fields = ('name', 'definition')

    def get_queryset(self, request):
        qs = super(WorkgroupAdmin, self).get_queryset(request)
        if request.user.is_superuser:
            return qs
        else:
            return request.user.profile.workgroups.all()

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        if obj is None:
            if request.GET.get('t', None) == "registrygroup_ptr":
                return True
            else:
                return True in (
                    request.user.has_perm(
                        'aristotle_mdr.admin_in_{name}'.format(name=w.name)
                    ) for w in request.user.profile.workgroups.all()
                )
        elif perms.user_can_edit(request.user, obj):
            return True
        else:
            return super(WorkgroupAdmin, self).has_change_permission(request, obj=None)


class ConceptAdmin(CompareVersionAdmin, admin.ModelAdmin):

    form = MDRForms.admin.AdminConceptForm
    list_display = ['name', 'description_stub', 'created', 'modified', 'workgroup', 'is_public', 'is_locked']  # ,'status']
    list_filter = ['created', 'modified', ('workgroup', WorkgroupFilter)]  # , 'statuses']
    search_fields = ['name', 'synonyms']
    inlines = [StatusInline]

    date_hierarchy = 'created'  # ,'modified']

    fieldsets = [
        (None, {'fields': ['name', 'definition', 'workgroup']}),
        ('Additional names', {
            'classes': ('grp-collapse grp-closed',),
            'fields': ['synonyms', 'short_name', 'version']
        }),
        # ('Registry', {'fields': ['workgroup']}),
        ('Relationships', {
            'classes': ('grp-collapse grp-closed',),
            'fields': ['origin_URI', 'superseded_by', 'deprecated'],
        }),
    ]
    name_suggest_fields = []
    actions_on_top = True
    actions_on_bottom = False

    """
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "workgroup":
            kwargs['queryset'] = request.user.profile.editable_workgroups.all()
            kwargs['initial'] = request.user.profile.activeWorkgroup
        return super(ConceptAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)
    """

    def get_form(self, request, obj=None, **kwargs):
        # Thanks: http://stackoverflow.com/questions/6321916
        # Thanks: http://stackoverflow.com/questions/2683689
        conceptForm = super(ConceptAdmin, self).get_form(request, obj, **kwargs)

        class ModelFormMetaClass(conceptForm):
            def __new__(cls, *args, **kwargs):
                kwargs['request'] = request
                kwargs['name_suggest_fields'] = self.name_suggest_fields
                if self.name_suggest_fields:
                    SEPARATORS = getattr(settings, 'ARISTOTLE_SETTINGS', {}).get('SEPARATORS', {})
                    kwargs['separator'] = SEPARATORS[self.model.__name__]
                return conceptForm(*args, **kwargs)

        return ModelFormMetaClass

    def has_change_permission(self, request, obj=None):
        if obj is None:
            return True
        else:
            return perms.user_can_edit(request.user, obj)

    def has_add_permission(self, request):
        return perms.user_is_editor(request.user)

    def has_delete_permission(self, request, obj=None):
        if obj is None:
            return perms.user_is_editor(request.user)
        else:
            return request.user.has_perm("aristotle_mdr.delete_concept_from_admin", obj)

    def get_queryset(self, request):
        queryset = super(ConceptAdmin, self).get_queryset(request)
        if not request.user.is_superuser:
            if not self.has_change_permission(request):
                queryset = queryset.none()
            else:
                queryset = queryset.editable(request.user).all()
        return queryset

    # On save or add, redirect to the live page.
    # Implementing this would be nice:
    #      http://www.szotten.com/david/custom-redirects-in-the-django-admin.html
    def response_add(self, request, obj, post_url_continue=None):
        response = super(ConceptAdmin, self).response_add(request, obj)
        if '_save' in request.POST and post_url_continue is None:
            response['location'] = reverse("aristotle:item", args=(obj.id,))
        return response

    def response_change(self, request, obj, post_url_continue=None):
        response = super(ConceptAdmin, self).response_change(request, obj)
        if '_save' in request.POST and post_url_continue is None:
            response['location'] = reverse("aristotle:item", args=(obj.id,))
        return response


# For ValueDomains
class CodeValueInline(admin.TabularInline):
    form = MDRForms.PermissibleValueForm
    # fields = ("value","meaning")
    sortable_field_name = "order"
    extra = 1


class PermissibleValueInline(CodeValueInline):
    model = MDR.PermissibleValue


class SupplementaryValueInline(CodeValueInline):
    model = MDR.SupplementaryValue


class RegistrationAuthorityAdmin(admin.ModelAdmin):
    list_display = ['name', 'definition', 'created', 'modified']
    list_filter = ['created', 'modified']
    filter_horizontal = ['managers', 'registrars']

    fieldsets = [
        (None, {'fields': ['name', 'definition']}),
        ('Members', {'fields': ['managers', 'registrars']}),
        ('Visibility and control', {'fields': ['locked_state', 'public_state']}),
        ('Status descriptions',
            {'fields': ['notprogressed', 'incomplete', 'candidate', 'recorded', 'qualified', 'standard', 'preferred', 'superseded', 'retired']}),
    ]

admin.site.register(MDR.RegistrationAuthority, RegistrationAuthorityAdmin)
admin.site.register(MDR.Workgroup, WorkgroupAdmin)

admin.site.register(MDR.Measure)
# admin.site.register(MDR.)


# Define an inline admin descriptor for Employee model
# which acts a bit like a singleton
class AristotleProfileInline(admin.StackedInline):
    model = MDR.PossumProfile
    form = MDRForms.admin.AristotleProfileForm
    exclude = ('savedActiveWorkgroup', 'favourites')
    can_delete = False
    verbose_name_plural = 'Membership details'


# Define a new User admin
class AristotleUserAdmin(UserAdmin):

    inlines = [AristotleProfileInline]

    def save_formset(self, request, form, formset, change):
        super(AristotleUserAdmin, self).save_formset(request, form, formset, change)
        for f in formset.forms:
            f.save_memberships(user=form.instance)


# Re-register UserAdmin
if User in admin.site._registry:
    admin.site.unregister(User)
admin.site.register(User, AristotleUserAdmin)


register_concept(MDR.ObjectClass)
register_concept(MDR.RepresentationClass)
register_concept(MDR.Property)
register_concept(
    MDR.ValueDomain,
    extra_fieldsets=[('Representation', {'fields': ['format', 'maximum_length', 'unit_of_measure', 'data_type', 'description']})],
    extra_inlines=[PermissibleValueInline, SupplementaryValueInline],
    reversion={
        'follow': ['permissiblevalue_set', 'supplementaryvalue_set'],
        'follow_classes': [MDR.PermissibleValue, MDR.SupplementaryValue]
    }
)

register_concept(
    MDR.DataElementConcept,
    name_suggest_fields=['objectClass', 'property'],
    extra_fieldsets=[('Components', {'fields': ['objectClass', 'property']})],
    reversion={
        'follow': ['objectClass', 'property'],
    }
)

register_concept(
    MDR.DataElement,
    name_suggest_fields=['dataElementConcept', 'valueDomain'],
    extra_fieldsets=[('Components', {'fields': ['dataElementConcept', 'valueDomain']})],
    reversion={
        'follow': ['dataElementConcept', 'valueDomain'],
    }
)

register_concept(
    MDR.DataElementDerivation,
    extra_fieldsets=[('Derivation', {'fields': ['derivation_rule', 'derives', 'inputs']})]
)

register_concept(MDR.ConceptualDomain)
register_concept(MDR.DataType)

register_concept(
    MDR.UnitOfMeasure,
    extra_fieldsets=[('Measures', {'fields': ['measure']})]
)
