import autocomplete_light

from django import forms
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _

import aristotle_mdr.models as mdr
from aristotle_mdr.forms.creation_wizards import UserAwareModelForm
from aristotle_mdr.forms import ChangeStatusForm


class RequestReviewForm(UserAwareModelForm):
    class Meta:
        model = mdr.ReviewRequest
        fields = ['state', 'registration_authority', 'message']


class RequestReviewCancelForm(UserAwareModelForm):
    class Meta:
        model = mdr.ReviewRequest
        fields = []


class RequestReviewRejectForm(UserAwareModelForm):
    class Meta:
        model = mdr.ReviewRequest
        fields = ['response']


class RequestReviewAcceptForm(ChangeStatusForm):
    response = forms.CharField(
        max_length=512,
        required=True,
        label=_("Reply to the original review request below."),
        widget=forms.Textarea
    )

    # TODO: This is from aristotle_mdr.bulk_actions.ChangeStateForm - See if this can share a superclass
    def make_changes(self, items):
        import reversion
        if not self.user.profile.is_registrar:
            raise PermissionDenied
        ras = self.cleaned_data['registrationAuthorities']
        state = self.cleaned_data['state']
        # items = self.items_to_change
        reg_date = self.cleaned_data['registrationDate']
        cascade = self.cleaned_data['cascadeRegistration']
        change_details = self.cleaned_data['changeDetails']
        failed = []
        success = []
        with transaction.atomic(), reversion.revisions.create_revision():
            reversion.revisions.set_user(self.user)
            if reg_date is None:
                reg_date = timezone.now().date()
            for item in items:
                for ra in ras:
                    # SBR If it is a concept object then work our the realised concecpt ( Data Element, Object etc )
                    if isinstance(item, mdr._concept):
                        cascadeItem = item.item

                    if cascade:
                        if cascadeItem:
                            item = cascadeItem

                        r = ra.cascaded_register(
                            item, state, self.user, reg_date=reg_date,
                            change_details=change_details
                        )
                    else:
                        r = ra.register(
                            item, state, self.user, reg_date=reg_date,
                            change_details=change_details
                        )
                    for f in r['failed']:
                        failed.append(f)
                    for s in r['success']:
                        success.append(s)
            failed = list(set(failed))
            success = list(set(success))
            message = _(
                "%(num_items)s %(item)s registered in %(num_ra)s %(ra)s."
            ) % {
                'num_items': len(success),
                'item': 'items' if len(success) > 1 else 'item',
                'num_ra': len(ras),
                'ra': 'authorities' if len(ras) > 1 else 'authority',
                'fail_message': "Some items failed, they had the id's: "+",".join(
                    sorted([str(i.id) for i in failed])
                ) if len(failed) > 0 else ""
            }
            reversion.revisions.set_comment(change_details + "\n\n" + message)
            return message
