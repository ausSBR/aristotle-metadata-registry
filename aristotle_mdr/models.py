from __future__ import unicode_literals
from __future__ import print_function
from __future__ import absolute_import

from django.conf import settings
from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from django.db import models, transaction
from django.db.models import Q
from django.db.models.signals import post_save, m2m_changed, post_delete
from django.dispatch import receiver, Signal
from django.utils import timezone
from django.utils.module_loading import import_string
from django.utils.translation import ugettext_lazy as _

from model_utils.managers import InheritanceManager, InheritanceQuerySet
from model_utils.models import TimeStampedModel
from model_utils import Choices, FieldTracker

import reversion  # import revisions

import datetime
from ckeditor_uploader.fields import RichTextUploadingField as RichTextField
from aristotle_mdr import perms
from aristotle_mdr import messages
from aristotle_mdr.utils import url_slugify_concept, url_slugify_workgroup, url_slugify_registration_authoritity
from aristotle_mdr import comparators

from model_utils.fields import AutoLastModifiedField

import logging
logger = logging.getLogger(__name__)
logger.debug("Logging started for " + __name__)


# 11179 States
# When used these MUST be used as IntegerFields to allow status comparison
STATES = Choices(
    (0, 'notprogressed', _('Not Progressed')),
    (1, 'incomplete', _('Incomplete')),
    (2, 'candidate', _('Candidate')),
    (3, 'recorded', _('Recorded')),
    (4, 'qualified', _('Qualified')),
    (5, 'standard', _('Standard')),
    (6, 'preferred', _('Preferred Standard')),
    (7, 'superseded', _('Superseded')),
    (8, 'retired', _('Retired')),
)


VERY_RECENTLY_SECONDS = 15


concept_visibility_updated = Signal(providing_args=["concept"])


class baseAristotleObject(TimeStampedModel):
    name = models.TextField(
        help_text=_("The primary name used for human identification purposes.")
    )
    definition = RichTextField(
        _('definition'),
        help_text=_("Representation of a concept by a descriptive statement "
                    "which serves to differentiate it from related concepts")
    )
    objects = InheritanceManager()

    class Meta:
        # So the url_name works for items we can't determine
        verbose_name = "item"
        # Can't be abstract as we need unique app wide IDs.
        abstract = True

    def was_modified_very_recently(self):
        return self.modified >= (
            timezone.now() - datetime.timedelta(seconds=VERY_RECENTLY_SECONDS)
        )

    def was_modified_recently(self):
        return self.modified >= timezone.now() - datetime.timedelta(days=1)
    was_modified_recently.admin_order_field = 'modified'
    was_modified_recently.boolean = True
    was_modified_recently.short_description = 'Modified recently?'

    def description_stub(self):
        from django.utils.html import strip_tags
        d = strip_tags(self.definition)
        if len(d) > 150:
            d = d[0:150] + "..."
        return d

    def __str__(self):
        return "{name}".format(name=self.name).encode('utf-8')

    def __unicode__(self):
        return "{name}".format(name=self.name)

    # Defined so we can access it during templates.
    @classmethod
    def get_verbose_name(cls):
        return cls._meta.verbose_name.title()

    @classmethod
    def get_verbose_name_plural(cls):
        return cls._meta.verbose_name_plural.title()

    # @property
    # def url_name(self):
    #     s = self._meta.object_name
    #     s = s[0].lower() + s[1:]
    #     return s

    @property
    def url_name(self):
        # TODO: Changed as we've altered URL handling,but will refactor calls
        # to this away later
        return "item"

    def can_edit(self, user):
        # This should always be overridden
        raise NotImplementedError  # pragma: no cover

    def can_view(self, user):
        # This should always be overridden
        raise NotImplementedError  # pragma: no cover

    @classmethod
    def meta(self):
        # I know what I'm doing, get out the way.
        return self._meta


class unmanagedObject(baseAristotleObject):
    class Meta:
        abstract = True

    def can_edit(self, user):
        return user.is_superuser

    def can_view(self, user):
        return True

    @property
    def item(self):
        return self


class aristotleComponent(models.Model):
    class Meta:
        abstract = True

    def can_edit(self, user):
        return self.parentItem.can_edit(user)

    def can_view(self, user):
        return self.parentItem.can_view(user)


class registryGroup(unmanagedObject):
    managers = models.ManyToManyField(
        User,
        blank=True,
        related_name="%(class)s_manager_in",
        verbose_name=_('Managers')
    )

    class Meta:
        abstract = True

    def can_edit(self, user):
        return user.is_superuser or self.managers.filter(pk=user.pk).exists()

    @property
    def help_name(self):
        return self._meta.model_name


class RegistrationAuthority(registryGroup):
    """
    A registration authority is a proxy group that describes a governance
    process for "standardising" metadata.
    """
    template = "aristotle_mdr/registrationAuthority.html"
    locked_state = models.IntegerField(
        choices=STATES,
        default=STATES.candidate
    )
    public_state = models.IntegerField(
        choices=STATES,
        default=STATES.recorded
    )

    registrars = models.ManyToManyField(
        User,
        blank=True,
        related_name='registrar_in',
        verbose_name=_('Registrars')
    )

    # The below text fields allow for brief descriptions of the context of each
    # state for a particular Registration Authority
    # For example:
    # For a particular Registration Authority standard may mean"
    #   "Approved by a simple majority of the standing council of metadata
    #    standardisation"
    # While "Preferred Standard" may mean:
    #   "Approved by a two-thirds majority of the standing council of metadata
    #    standardisation"

    notprogressed = models.TextField(blank=True)
    incomplete = models.TextField(blank=True)
    candidate = models.TextField(blank=True)
    recorded = models.TextField(blank=True)
    qualified = models.TextField(blank=True)
    standard = models.TextField(blank=True)
    preferred = models.TextField(blank=True)
    superseded = models.TextField(blank=True)
    retired = models.TextField(blank=True)

    tracker = FieldTracker()

    class Meta:
        verbose_name_plural = _("Registration Authorities")

    def get_absolute_url(self):
        return url_slugify_registration_authoritity(self)

    def can_view(self, user):
        return True

    @property
    def unlocked_states(self):
        return range(STATES.notprogressed, self.locked_state)

    @property
    def locked_states(self):
        return range(self.locked_state, self.public_state)

    @property
    def public_states(self):
        return range(self.public_state, STATES.retired + 1)

    def statusDescriptions(self):
        descriptions = [
            self.notprogressed,
            self.incomplete,
            self.candidate,
            self.recorded,
            self.qualified,
            self.standard,
            self.preferred,
            self.superseded,
            self.retired
        ]

        unlocked = [
            (i, STATES[i], descriptions[i]) for i in self.unlocked_states
        ]
        locked = [
            (i, STATES[i], descriptions[i]) for i in self.locked_states
        ]
        public = [
            (i, STATES[i], descriptions[i]) for i in self.public_states
        ]

        return (
            ('unlocked', unlocked),
            ('locked', locked),
            ('public', public)
        )

    def cascaded_register(self, item, state, user, *args, **kwargs):
        if not perms.user_can_change_status(user, item):
            # Return a failure as this item isn't allowed
            return {'success': [], 'failed': [item] + item.registry_cascade_items}

        revision_message = _(
            "Cascade registration of item '%(name)s' (id:%(iid)s)\n"
        ) % {
            'name': item.name,
            'iid': item.id
        }
        revision_message = revision_message + kwargs.get('changeDetails', "")
        seen_items = {'success': [], 'failed': []}

        with transaction.atomic(), reversion.revisions.create_revision():
            reversion.revisions.set_user(user)
            reversion.revisions.set_comment(revision_message)

            for child_item in [item] + item.registry_cascade_items:
                self._register(
                    child_item, state, user, *args, **kwargs
                )
                seen_items['success'] = seen_items['success'] + [child_item]
        return seen_items

    def register(self, item, state, user, *args, **kwargs):
        if not perms.user_can_change_status(user, item):
            # Return a failure as this item isn't allowed
            return {'success': [], 'failed': [item]}

        revision_message = kwargs.get('changeDetails', "")
        if revision_message == "" :
            revision_message = args.get('changeDetails', "")

        with transaction.atomic(), reversion.revisions.create_revision():
            reversion.revisions.set_user(user)
            reversion.revisions.set_comment(revision_message)
            self._register(item, state, user, *args, **kwargs)

        return {'success': [item], 'failed': []}

    def _register(self, item, state, user, *args, **kwargs):

        try :
            changeDetails = kwargs.get('changeDetails', "")
            if changeDetails == "" :
                revision_message = args.get('changeDetails', "")
        except :
            changeDetails = "No Change Details Supplied."
        # If registrationDate is None (like from a form), override it with
        # todays date.
        try :
            registrationDate = kwargs.get('regDate', "")
            if registrationDate == "" :
                registrationDate = args.get('regDate', "")
            if registrationDate == "" :
                registrationDate =  timezone.now().date()
        except :
            registrationDate = timezone.now().date()

        try :
            until_date = kwargs.get('until_date', "")
            if until_date == "" :
                until_date = args.get('until_date', "")
            if until_date == "" :
                until_date = registrationDate
        except :
            until_date = timezone.now().date()

        Status.objects.create(
            concept=item,
            registrationAuthority=self,
            registrationDate=registrationDate,
            state=state,
            changeDetails=changeDetails,
            until_date=until_date
        )

    def giveRoleToUser(self, role, user):
        if role == 'registrar':
            self.registrars.add(user)
        if role == "manager":
            self.managers.add(user)

    def removeRoleFromUser(self, role, user):
        if role == 'registrar':
            self.registrars.remove(user)
        if role == "manager":
            self.managers.remove(user)


@receiver(post_save, sender=RegistrationAuthority)
def update_registration_authority_states(sender, instance, created, **kwargs):
    if not created:
        if instance.tracker.has_changed('public_state') \
           or instance.tracker.has_changed('locked_state'):
            message = (
                "Registration '{ra}' changed its public or locked status "
                "level, items registered by this authority may have stale "
                "visiblity states and need to be manually updated."
            ).format(ra=instance.name)
            logger.critical(message)


class Workgroup(registryGroup):
    """
    A workgroup is a collection of associated users given control to work on a
    specific piece of work. Usually this work will be the creation of a
    specific collection of objects, such as data elements, for a specific
    topic.

    Workgroup owners may choose to 'archive' a workgroup. All content remains
    visible, but the workgroup is hidden in lists and new items cannot be
    created in that workgroup.
    """
    template = "aristotle_mdr/workgroup.html"
    archived = models.BooleanField(
        default=False,
        help_text=_("Archived workgroups can no longer have new items or "
                    "discussions created within them."),
        verbose_name=_('Archived'),
    )

    viewers = models.ManyToManyField(
        User,
        blank=True,
        related_name='viewer_in',
        verbose_name=_('Viewers')
    )
    submitters = models.ManyToManyField(
        User,
        blank=True,
        related_name='submitter_in',
        verbose_name=_('Submitters')
    )
    stewards = models.ManyToManyField(
        User,
        blank=True,
        related_name='steward_in',
        verbose_name=_('Stewards')
    )

    roles = {
        'submitter': _("Submitter"),
        'viewer': _("Viewer"),
        'steward': _("Steward"),
        'manager': _("Manager")
    }

    tracker = FieldTracker()

    def get_absolute_url(self):
        return url_slugify_workgroup(self)

    @property
    def members(self):
        return self.viewers.all() \
            | self.submitters.all() \
            | self.stewards.all() \
            | self.managers.all()

    def can_view(self, user):
        return self.members.filter(pk=user.pk).exists()

    @property
    def classedItems(self):
        # Convenience class as we can't call functions in templates
        return self.items.select_subclasses()

    def giveRoleToUser(self, role, user):
        if role == "manager":
            self.managers.add(user)
        if role == "viewer":
            self.viewers.add(user)
        if role == "submitter":
            self.submitters.add(user)
        if role == "steward":
            self.stewards.add(user)
        self.save()

    def removeRoleFromUser(self, role, user):
        if role == "manager":
            self.managers.remove(user)
        if role == "viewer":
            self.viewers.remove(user)
        if role == "submitter":
            self.submitters.remove(user)
        if role == "steward":
            self.stewards.remove(user)
        self.save()

    def removeUser(self, user):
        self.viewers.remove(user)
        self.submitters.remove(user)
        self.stewards.remove(user)
        self.managers.remove(user)


class discussionAbstract(TimeStampedModel):
    body = models.TextField()
    author = models.ForeignKey(User)

    class Meta:
        abstract = True

    @property
    def edited(self):
        return self.created != self.modified


class DiscussionPost(discussionAbstract):
    workgroup = models.ForeignKey(Workgroup, related_name='discussions')
    title = models.CharField(max_length=256)
    relatedItems = models.ManyToManyField(
        '_concept',
        blank=True,
        related_name='relatedDiscussions',
    )
    closed = models.BooleanField(default=False)

    class Meta:
        ordering = ['-modified']

    @property
    def active(self):
        return not self.closed


class DiscussionComment(discussionAbstract):
    post = models.ForeignKey(DiscussionPost, related_name='comments')

    class Meta:
        ordering = ['created']


# class ReferenceDocument(models.Model):
#     url = models.URLField()
#     definition = models.TextField()
#     object = models.ForeignKey(managedObject)


class ConceptQuerySet(InheritanceQuerySet):
    def visible(self, user):
        """
        Returns a queryset that returns all items that the given user has
        permission to view.

        It is **chainable** with other querysets. For example, both of these
        will work and return the same list::

            ObjectClass.objects.filter(name__contains="Person").visible()
            ObjectClass.objects.visible().filter(name__contains="Person")
        """
        if user.is_superuser:
            return self.all()
        if user.is_anonymous():
            return self.public()
        q = Q(_is_public=True)

        if user.is_active:
            # User can see everything they've made.
            q |= Q(submitter=user)
            if user.profile.workgroups:
                # User can see everything in their workgroups.
                q |= Q(workgroup__in=user.profile.workgroups)
                # q |= Q(workgroup__user__profile=user)
            if user.profile.is_registrar:
                # Registars can see items they have been asked to review
                q |= Q(
                    Q(review_requests__registration_authority__registrars__profile__user=user) & ~Q(review_requests__status=REVIEW_STATES.cancelled)
                )
                # Registars can see items that have been registered in their registration authority
                q |= Q(
                    Q(statuses__registrationAuthority__registrars__profile__user=user)
                )
        extra_q = settings.ARISTOTLE_SETTINGS.get('EXTRA_CONCEPT_QUERYSETS', {}).get('visible', None)
        if extra_q:
            for func in extra_q:
                q |= import_string(func)(user)
        return self.filter(q)

    def editable(self, user):
        """
        Returns a queryset that returns all items that the given user has
        permission to edit.

        It is **chainable** with other querysets. For example, both of these
        will work and return the same list::

            ObjectClass.objects.filter(name__contains="Person").editable()
            ObjectClass.objects.editable().filter(name__contains="Person")
        """
        if user.is_superuser:
            return self.all()
        if user.is_anonymous():
            return self.none()
        q = Q()

        # User can edit everything they've made thats not locked
        q |= Q(submitter=user, _is_locked=False)

        if user.submitter_in.exists() or user.steward_in.exists():
            if user.submitter_in.exists():
                q |= Q(_is_locked=False, workgroup__submitters__profile__user=user)
            if user.steward_in.exists():
                q |= Q(workgroup__stewards__profile__user=user)
            return self.filter(q)
        else:
            return self.none()

    def public(self):
        """
        Returns a list of public items from the queryset.

        This is a chainable query set, that filters on items which have the
        internal `_is_public` flag set to true.

        Both of these examples will work and return the same list::

            ObjectClass.objects.filter(name__contains="Person").public()
            ObjectClass.objects.public().filter(name__contains="Person")
        """
        return self.filter(_is_public=True)


class ConceptManager(InheritanceManager):
    """
    The ``ConceptManager`` is the default object manager for ``concept`` and
    ``_concept`` items, and extends from the django-model-utils
    ``InheritanceManager``.

    It provides access to the ``ConceptQuerySet`` to allow for easy
    permissions-based filtering of ISO 11179 Concept-based items.
    """
    def get_queryset(self):
        return ConceptQuerySet(self.model)

    def __getattr__(self, attr, *args):
        if attr in ['editable', 'visible', 'public']:
            return getattr(self.get_queryset(), attr, *args)
        else:
            return getattr(self.__class__, attr, *args)


class _concept(baseAristotleObject):
    """
    This is the base concrete class that ``Status`` items attach to, and to
    which collection objects refer to. It is not marked abstract in the Django
    Meta class, and **must not be inherited from**. It has relatively few
    fields and is a convenience class to link with in relationships.
    """
    objects = ConceptManager()
    template = "aristotle_mdr/concepts/managedContent.html"
    workgroup = models.ForeignKey(Workgroup, related_name="items", null=True, blank=True)
    submitter = models.ForeignKey(
        User, related_name="created_items",
        null=True, blank=True,
        help_text=_('This is the person who first created an item. Users can always see items they made.'))
    # We will query on these, so want them cached with the items themselves
    # To be usable these must be updated when statuses are changed
    _is_public = models.BooleanField(default=False)
    _is_locked = models.BooleanField(default=False)

    tracker = FieldTracker()

    comparator = comparators.Comparator
    edit_page_excludes = None
    admin_page_excludes = None

    class Meta:
        # So the url_name works for items we can't determine.
        verbose_name = "item"

    @property
    def non_cached_fields_changed(self):
        changed = self.tracker.changed()
        public_changed = changed.pop('_is_public', False)
        locked_changed = changed.pop('_is_locked', False)
        return len(changed.keys()) > 0

    def can_edit(self, user):
        return _concept.objects.filter(pk=self.pk).editable(user).exists()

    def can_view(self, user):
        return _concept.objects.filter(pk=self.pk).visible(user).exists()

    @property
    def item(self):
        """
        Performs a lookup using ``model_utils.managers.InheritanceManager`` to
        find the subclassed item.
        """
        return _concept.objects.get_subclass(pk=self.pk)

    @property
    def concept(self):
        """
        Returns the parent _concept that an item is built on.
        If the item type is _concept, return itself.
        """
        return getattr(self, '_concept_ptr', self)

    @classmethod
    def get_autocomplete_name(self):
        return 'Autocomplete' + "".join(
            self._meta.verbose_name.title().split()
        )

    @staticmethod
    def autocomplete_search_fields(self):
        return ("name__icontains",)

    def get_absolute_url(self):
        return url_slugify_concept(self)

    @property
    def registry_cascade_items(self):
        """
        This returns the items that can be registered along with the this item.
        If a subclass of _concept defines this method, then when an instance
        of that class is registered using a cascading method then that
        instance, all instances returned by this method will all recieve the
        same registration status.

        Reimplementations of this MUST return iterables.
        """
        return []

    @property
    def is_registered(self):
        return self.statuses.count() > 0

    @property
    def is_superseded(self):
        return all(
            STATES.superseded == status.state for status in self.statuses.all()
        ) and self.superseded_by

    @property
    def is_retired(self):
        return all(
            STATES.retired == status.state for status in self.statuses.all()
        ) and self.statuses.count() > 0

    def check_is_public(self, when=timezone.now()):
        """
            A concept is public if any registration authority
            has advanced it to a public state in that RA.
        """
        statuses = self.statuses.all()
        statuses = self.current_statuses(qs=statuses, when=when)
        pub_state = True in [
            s.state >= s.registrationAuthority.public_state for s in statuses
        ]

        q = Q()
        extra = False
        extra_q = settings.ARISTOTLE_SETTINGS.get('EXTRA_CONCEPT_QUERYSETS', {}).get('public', None)
        if extra_q:
            for func in extra_q:
                q |= import_string(func)()
            extra = self.__class__.objects.filter(pk=self.pk).filter(q).exists()
        return pub_state or extra

    def is_public(self):
        return self._is_public
    is_public.boolean = True
    is_public.short_description = 'Public'

    def check_is_locked(self, when=timezone.now()):
        """
        A concept is locked if any registration authority
        has advanced it to a locked state in that RA.
        """
        statuses = self.statuses.all()
        statuses = self.current_statuses(qs=statuses, when=when)
        return True in [
            s.state >= s.registrationAuthority.locked_state for s in statuses
        ]

    def is_locked(self):
        return self._is_locked

    is_locked.boolean = True
    is_locked.short_description = 'Locked'

    def recache_states(self):
        self._is_public = self.check_is_public()
        self._is_locked = self.check_is_locked()
        self.save()
        concept_visibility_updated.send(sender=self.__class__, concept=self)

    def current_statuses(self, qs=None, when=timezone.now()):
        if qs is None:
            qs = self.statuses.all()
        if hasattr(when, 'date'):
            when = when.date()
        registered_before_now = Q(registrationDate__lte=when)
        registation_still_valid = (
            Q(until_date__gte=when) |
            Q(until_date__isnull=True)
        )

        states = qs.filter(
            registered_before_now & registation_still_valid
        ).order_by("registrationAuthority", "-registrationDate", "-created")

        from django.db import connection
        if connection.vendor == 'postgresql':
            states = states.distinct('registrationAuthority')
        else:
            current_ids = []
            seen_ras = []
            for s in states:
                ra = s.registrationAuthority
                if ra not in seen_ras:
                    current_ids.append(s.pk)
                    seen_ras.append(ra)
            # We hit again so we can return this as a queryset
            states = states.filter(pk__in=current_ids)
        return states

    def get_download_items(self):
        """
        When downloading a concept, extra items can be included for download by
        overriding the ``get_download_items`` method on your item. By default
        this returns an empty list, but can be modified to include any number of
        items that inherit from ``_concept``.

        When overriding, each entry in the list must be a two item tuple, with
        the first entry being the python class of the item or items being
        included, and the second being the queryset of items to include.
        """
        return []


class concept(_concept):
    """
    This is an abstract class that all items that should behave like a 11179
    Concept **must inherit from**. This model includes the definitions for many
    long and optional text fields and the self-referential ``superseded_by``
    field. It is not possible to include this model in a ``ForeignKey`` or
    ``ManyToManyField``.
    """
    short_name = models.CharField(max_length=100, blank=True)
    version = models.CharField(max_length=20, blank=True)
    synonyms = models.CharField(max_length=200, blank=True)
    references = RichTextField(blank=True)
    origin_URI = models.URLField(
        blank=True,
        help_text="If imported, the original location of the item"
    )
    comments = RichTextField(
        help_text="Descriptive comments about the metadata item.",
        blank=True
    )
    submitting_organisation = models.CharField(max_length=256, blank=True)
    responsible_organisation = models.CharField(max_length=256, blank=True)

    superseded_by = models.ForeignKey(
        'self',
        related_name='supersedes',
        blank=True,
        null=True
    )

    objects = ConceptManager()

    class Meta:
        abstract = True

    @property
    def help_name(self):
        return self._meta.model_name

    @property
    def item(self):
        """
        Return self, because we already have the correct item.
        """
        return self


REVIEW_STATES = Choices(
    (0, 'submitted', _('Submitted')),
    (5, 'cancelled', _('Cancelled')),
    (10, 'accepted', _('Accepted')),
    (15, 'rejected', _('Rejected')),
)


class ReviewRequestQuerySet(models.QuerySet):
    def visible(self, user):
        """
        Returns a queryset that returns all reviews that the given user has
        permission to view.

        It is **chainable** with other querysets. For example, both of these
        will work and return the same list::

            ObjectClass.objects.filter(name__contains="Person").visible()
            ObjectClass.objects.visible().filter(name__contains="Person")
        """
        if user.is_superuser:
            return self.all()
        if user.is_anonymous():
            return self.none()
        q = Q(requester=user)  # Users can always see reviews they requested
        if user.profile.is_registrar:
            # Registars can see reviews for the registration authority
            q |= Q(
                Q(registration_authority__registrars__profile__user=user) & ~Q(status=REVIEW_STATES.cancelled)
            )
        return self.filter(q)


class ReviewRequestManager(models.Manager):
    def get_queryset(self):
        return ReviewRequestQuerySet(self.model, using=self._db)

    def __getattr__(self, attr, *args):
        if attr in ['visible']:
            return getattr(self.get_queryset(), attr, *args)
        else:
            return getattr(self.__class__, attr, *args)


class ReviewRequest(TimeStampedModel):
    objects = ReviewRequestManager()
    concepts = models.ManyToManyField(_concept, related_name="review_requests")
    registration_authority = models.ForeignKey(
        RegistrationAuthority,
        help_text=_("The registration authority the requester wishes to endorse the metadata item")
    )
    requester = models.ForeignKey(User, help_text=_("The user requesting a review"), related_name='requested_reviews')
    message = models.TextField(blank=True, null=True, help_text=_("An optional message accompanying a request"))
    reviewer = models.ForeignKey(User, null=True, help_text=_("The user performing a review"), related_name='reviewed_requests')
    response = models.TextField(blank=True, null=True, help_text=_("An optional message responding to a request"))
    status = models.IntegerField(
        choices=REVIEW_STATES,
        default=REVIEW_STATES.submitted,
        help_text=_('Status of a review')
    )
    state = models.IntegerField(
        choices=STATES,
        blank=True, null=True,
        help_text=_("The state at which a user wishes a metadata item to be endorsed")
    )


class Status(TimeStampedModel):
    concept = models.ForeignKey(_concept, related_name="statuses")
    registrationAuthority = models.ForeignKey(RegistrationAuthority)
    changeDetails = models.TextField(blank=True, null=True)
    state = models.IntegerField(choices=STATES, default=STATES.incomplete)
    # TODO: Below should be changed to 'effective_date' to match ISO IEC
    # 11179-6 (Section 8.1.2.6.2.2)
    registrationDate = models.DateField(_('Date registration effective'))
    until_date = models.DateField(
        _('Date registration expires'),
        blank=True,
        null=True
    )
    tracker = FieldTracker()

    class Meta:
        verbose_name_plural = "Statuses"

    @property
    def state_name(self):
        return STATES[self.state]

    def __unicode__(self):
        return "{obj} is {stat} for {ra} on {date} - {desc}".format(
            obj=self.concept.name,
            stat=self.state_name,
            ra=self.registrationAuthority,
            desc=self.changeDetails,
            date=self.registrationDate
        )


def recache_concept_states(sender, instance, *args, **kwargs):
    instance.concept.recache_states()
post_save.connect(recache_concept_states, sender=Status)
post_delete.connect(recache_concept_states, sender=Status)


class ObjectClass(concept):
    """
    Set of ideas, abstractions or things in the real world that are
    identified with explicit boundaries and meaning and whose properties and
    behaviour follow the same rules (3.2.88)
    """
    template = "aristotle_mdr/concepts/objectClass.html"

    class Meta:
        verbose_name_plural = "Object Classes"

class RepresentationClass(concept):
    """
    Add as part of SBR meta model requirements
    """
    template = "aristotle_mdr/concepts/representationClass.html"

    class Meta:
        verbose_name_plural = "Representation Classes"
        
class Property(concept):
    """
    Quality common to all members of an :model:`aristotle_mdr.ObjectClass`
    (3.2.100)
    """
    template = "aristotle_mdr/concepts/property.html"

    class Meta:
        verbose_name_plural = "Properties"


class Measure(unmanagedObject):
    template = "aristotle_mdr/unmanaged/measure.html"


class UnitOfMeasure(concept):
    """
    actual units in which the associated values are measured
    :model:`aristotle_mdr.ValueDomain` (3.2.138)
    """

    class Meta:
        verbose_name_plural = "Units Of Measure"

    template = "aristotle_mdr/concepts/unitOfMeasure.html"
    measure = models.ForeignKey(Measure, blank=True, null=True)
    symbol = models.CharField(max_length=20, blank=True)


class DataType(concept):
    """
    set of distinct values, characterized by properties of those values and
    by operations on those values (3.1.9)"""
    template = "aristotle_mdr/concepts/dataType.html"


class ConceptualDomain(concept):
    """
    Concept that expresses its description or valid instance meanings (3.2.21)
    """

    # Implementation note: Since a Conceptual domain "must be either one or
    # both an Enumerated Conceptual or a Described_Conceptual_Domain" there is
    # no reason to model them separately.

    template = "aristotle_mdr/concepts/conceptualDomain.html"
    description = models.TextField(
        _('description'),
        blank=True,
        help_text=('Description or specification of a rule, reference, or '
                   'range for a set of all value meanings for a Conceptual '
                   'Domain')
    )


class ValueMeaning(aristotleComponent):
    class Meta:
        ordering = ['order']
    meaning = models.CharField(max_length=255)
    conceptual_domain = models.ForeignKey(ConceptualDomain)
    order = models.PositiveSmallIntegerField("Position")
    start_date = models.DateField(
        blank=True,
        null=True,
        help_text='Date at which the value meaning became valid'
    )
    end_date = models.DateField(
        blank=True,
        null=True,
        help_text='Date at which the value meaning ceased to be valid'
    )

    def __unicode__(self):
        return "%s: %s - %s" % (
            self.conceptual_domain.name,
            self.value,
            self.meaning
        )

    @property
    def parentItem(self):
        return self.conceptual_domain


class ValueDomain(concept):
    """
    set of permissible values (3.2.140)"""

    # Implementation note: Since a Value domain "must be either one or
    # both an Enumerated Valued or a Described_Value_Domain" there is
    # no reason to model them separately.

    template = "aristotle_mdr/concepts/valueDomain.html"

    data_type = models.ForeignKey(DataType, blank=True, null=True)
    format = models.CharField(max_length=100, blank=True, null=True)
    maximum_length = models.PositiveIntegerField(blank=True, null=True)
    unit_of_measure = models.ForeignKey(UnitOfMeasure, blank=True, null=True)

    conceptual_domain = models.ForeignKey(
        ConceptualDomain,
        blank=True,
        null=True
    )
    description = models.TextField(
        _('description'),
        blank=True,
        help_text=('Description or specification of a rule, reference, or '
                   'range for a set of all values for a Value Domain.')
    )

    # Below is a dirty, dirty hack that came from re-designing permissible
    # values

    # TODO: Fix references to permissible and supplementary values
    @property
    def permissibleValues(self):
        return self.permissiblevalue_set.all()

    @property
    def supplementaryValues(self):
        return self.supplementaryvalue_set.all()


class AbstractValue(aristotleComponent):
    """
    Implementation note: Not the best name, but there will be times to
    subclass a "value" when its not just a permissible value.
    """

    class Meta:
        abstract = True
        ordering = ['order']
    value = models.CharField(max_length=32)
    meaning = models.CharField(max_length=255)
    value_meaning = models.ForeignKey(ValueMeaning, blank=True, null=True)
    # Below will generate exactly the same related name as django, but reversion-compare
    # needs an explicit related_name for some actions.
    valueDomain = models.ForeignKey(ValueDomain, related_name="%(class)s_set")
    order = models.PositiveSmallIntegerField("Position")
    start_date = models.DateField(
        blank=True,
        null=True,
        help_text='Date at which the value became valid'
    )
    end_date = models.DateField(
        blank=True,
        null=True,
        help_text='Date at which the value ceased to be valid'
    )

    def __unicode__(self):
        return "%s: %s - %s" % (
            self.valueDomain.name,
            self.value,
            self.meaning
        )

    @property
    def parentItem(self):
        return self.value_domain


class PermissibleValue(AbstractValue):
    pass


class SupplementaryValue(AbstractValue):
    pass


class DataElementConcept(concept):
    """
    Concept that is an association of a :model:`aristotle_mdr.Property`
    with an :model:`aristotle_mdr.ObjectClass` (3.2.29)"""

    # Redefine in this context as we need 'property' for the 11179 terminology.
    property_ = property
    template = "aristotle_mdr/concepts/dataElementConcept.html"
    objectClass = models.ForeignKey(ObjectClass, blank=True, null=True)
    property = models.ForeignKey(Property, blank=True, null=True)
    conceptualDomain = models.ForeignKey(
        ConceptualDomain,
        blank=True,
        null=True
    )

    @property_
    def registry_cascade_items(self):
        out = []
        if self.objectClass:
            out.append(self.objectClass)
        if self.property:
            out.append(self.property)
        return out

    def get_download_items(self):
        return [
            (ObjectClass, ObjectClass.objects.filter(dataelementconcept=self)),
            (Property, Property.objects.filter(dataelementconcept=self)),
        ]


# Yes this name looks bad - blame 11179:3:2013 for renaming "administered item"
# to "concept".
class DataElement(concept):
    """
    Unit of data that is considered in context to be indivisible (3.2.28)"""

    template = "aristotle_mdr/concepts/dataElement.html"
    dataElementConcept = models.ForeignKey(
        DataElementConcept,
        verbose_name="Data Element Concept",
        blank=True,
        null=True
    )
    valueDomain = models.ForeignKey(
        ValueDomain,
        verbose_name="Value Domain",
        blank=True,
        null=True
    )

    representationClass = models.ForeignKey(
        RepresentationClass,
        verbose_name="Representation Class",
        blank=True,
        null=True
    )
    @property
    def registry_cascade_items(self):
        out = []
        if self.representationClass:
            out.append(self.representationClass)
        if self.dataElementConcept:
            out.append(self.dataElementConcept)
            out += self.dataElementConcept.registry_cascade_items
        return out

    def get_download_items(self):
        return [
            (ObjectClass, ObjectClass.objects.filter(dataelementconcept=self.dataElementConcept)),
            (Property, Property.objects.filter(dataelementconcept=self.dataElementConcept)),
            (DataElementConcept, DataElementConcept.objects.filter(dataelement=self)),
            (ValueDomain, ValueDomain.objects.filter(dataelement=self)),
            (RepresentationClass, RepresentationClass.objects.filter(dataelement=self)),
        ]


class DataElementDerivation(concept):
    """
    Application of a derivation rule to one or more
    input :model:`aristotle_mdr.DataElement`\s to derive one or more
    output :model:`aristotle_mdr.DataElement`\s (3.2.33)"""

    derives = models.ForeignKey(
        DataElement,
        related_name="derived_from",
        blank=True,
        null=True
    )
    inputs = models.ManyToManyField(
        DataElement,
        related_name="input_to_derivation",
        blank=True
    )
    derivation_rule = models.TextField(blank=True)


# Create a 1-1 user profile so we don't need to extend user
# Thanks to http://stackoverflow.com/a/965883/764357
class PossumProfile(models.Model):
    user = models.OneToOneField(
        User,
        related_name='profile'
    )
    savedActiveWorkgroup = models.ForeignKey(
        Workgroup,
        blank=True,
        null=True
    )
    favourites = models.ManyToManyField(
        _concept,
        related_name='favourited_by',
        blank=True
    )

    # Override save for inline creation of objects.
    # http://stackoverflow.com/questions/2813189/django-userprofile-with-unique-foreign-key-in-django-admin
    def save(self, *args, **kwargs):
        try:
            existing = PossumProfile.objects.get(user=self.user)
            self.id = existing.id  # Force update instead of insert.
        except PossumProfile.DoesNotExist:  # pragma: no cover
            pass
        models.Model.save(self, *args, **kwargs)

    @property
    def activeWorkgroup(self):
        return self.savedActiveWorkgroup or None

    @property
    def workgroups(self):
        if self.user.is_superuser:
            return Workgroup.objects.all()
        else:
            return (
                self.user.viewer_in.all() |
                self.user.submitter_in.all() |
                self.user.steward_in.all() |
                self.user.workgroup_manager_in.all()
            ).distinct()

    @property
    def myWorkgroups(self):
        return self.workgroups.filter(archived=False)

    @property
    def editable_workgroups(self):
        if self.user.is_superuser:
            return Workgroup.objects.all()
        else:
            return (
                self.user.submitter_in.all() |
                self.user.steward_in.all()
            ).distinct().filter(archived=False)

    @property
    def is_registrar(self):
        return perms.user_is_registrar(self.user)

    @property
    def discussions(self):
        return DiscussionPost.objects.filter(
            workgroup__in=self.myWorkgroups.all()
        )

    @property
    def registrarAuthorities(self):
        "NOTE: This is a list of Authorities the user is a *registrar* in!."
        if self.user.is_superuser:
            return RegistrationAuthority.objects.all()
        else:
            return self.user.registrar_in.all()

    def is_workgroup_manager(self, wg=None):
        return perms.user_is_workgroup_manager(self.user, wg)

    def is_favourite(self, item):
        return self.favourites.filter(pk=item.pk).exists()

    def toggleFavourite(self, item):
        if self.is_favourite(item):
            self.favourites.remove(item)
        else:
            self.favourites.add(item)


def create_user_profile(sender, instance, created, **kwargs):
    if created:
        profile, created = PossumProfile.objects.get_or_create(user=instance)
post_save.connect(create_user_profile, sender=User)


# """
# A collection is a user specified sharable collections of content.
# Collection owners can add and remove other owners, editors and viewers
#                   and add or remove content from the collection
#            viewers can see content in the collection
# In all cases, people can only see or add content they have permission to view
# in the wider registry.
# """
# class Collection(models.Model):
#  items = models.ManyToManyField(_concept,related_name='in_collections')
#  owner = models.ManyToManyField(User, related_name='owned_collections')
#  viewer = models.ManyToManyField(User, related_name='subscribed_collections')


@receiver(post_save)
def concept_saved(sender, instance, created, **kwargs):
    if not issubclass(sender, _concept):
        return
    if not instance.non_cached_fields_changed:
        # If the only thing that has changed is a cached public/locked status
        # then don't notify.
        return
    if kwargs.get('raw'):
        # Don't run during loaddata
        return
    for p in instance.favourited_by.all():
        messages.favourite_updated(recipient=p.user, obj=instance)
    if instance.workgroup:
        for user in instance.workgroup.viewers.all():
            if created:
                messages.workgroup_item_new(recipient=user, obj=instance)
            else:
                messages.workgroup_item_updated(recipient=user, obj=instance)
    try:
        # This will fail during first load, and if admins delete aristotle.
        system = User.objects.get(username="aristotle")
        for post in instance.relatedDiscussions.all():
            DiscussionComment.objects.create(
                post=post,
                body='The item "{name}" (id:{iid}) has been changed.\n\n\
                    <a href="{url}">View it on the main site.</a>.'.format(
                    name=instance.name,
                    iid=instance.id,
                    url=reverse("aristotle:item", args=[instance.id])
                ),
                author=system,
            )
    except:
        pass


@receiver(post_save, sender=DiscussionComment)
def new_comment_created(sender, **kwargs):
    comment = kwargs['instance']
    post = comment.post
    if kwargs.get('raw'):
        # Don't run during loaddata
        return
    if not kwargs['created']:
        return  # We don't need to notify a topic poster of an edit.
    if comment.author == post.author:
        return  # We don't need to tell someone they replied to themselves
    messages.new_comment_created(comment)


@receiver(post_save, sender=DiscussionPost)
def new_post_created(sender, **kwargs):
    post = kwargs['instance']
    if kwargs.get('raw'):
        # Don't run during loaddata
        return
    if not kwargs['created']:
        return  # We don't need to notify a topic poster of an edit.
    for user in post.workgroup.members.all():
        if user != post.author:
            messages.new_post_created(post, user)
