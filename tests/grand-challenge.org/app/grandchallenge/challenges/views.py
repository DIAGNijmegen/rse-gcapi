from collections import defaultdict, OrderedDict
from itertools import chain

from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Q
from django.views.generic import (
    CreateView,
    ListView,
    UpdateView,
    DeleteView,
    TemplateView,
)

from grandchallenge.challenges.forms import (
    ChallengeCreateForm,
    ChallengeUpdateForm,
    ExternalChallengeUpdateForm,
)
from grandchallenge.challenges.models import (
    Challenge,
    ExternalChallenge,
    ImagingModality,
    TaskType,
    BodyRegion,
)
from grandchallenge.core.permissions.mixins import (
    UserIsChallengeAdminMixin,
    UserIsStaffMixin,
    UserIsNotAnonMixin,
)
from grandchallenge.subdomains.mixins import ChallengeSubdomainObjectMixin
from grandchallenge.subdomains.utils import reverse


class ChallengeCreate(UserIsNotAnonMixin, SuccessMessageMixin, CreateView):
    model = Challenge
    form_class = ChallengeCreateForm
    success_message = "Challenge successfully created"

    def form_valid(self, form):
        form.instance.creator = self.request.user
        return super().form_valid(form)


class ChallengeList(TemplateView):
    template_name = "challenges/challenge_list.html"

    def get_context_data(self, *, object_list=None, **kwargs):
        context = super().get_context_data()

        challenges = chain(
            Challenge.objects.filter(hidden=False)
            .order_by("-created")
            .prefetch_related("creator"),
            ExternalChallenge.objects.filter(hidden=False)
            .order_by("-created")
            .prefetch_related("creator"),
        )

        challenges_by_year = defaultdict(list)
        hosts = set()
        host_count = defaultdict(int)

        for c in challenges:
            challenges_by_year[c.year].append(c)
            hosts.add(c.host_filter)
            host_count[c.host_filter.host] += 1

        modalities = ImagingModality.objects.all()
        task_types = TaskType.objects.all()
        regions = BodyRegion.objects.all().prefetch_related(
            "bodystructure_set"
        )

        # Cannot use a defaultdict in django template so convert to dict,
        # and this must be ordered by year for display
        context.update(
            {
                "modalities": modalities,
                "body_regions": regions,
                "task_types": task_types,
                "challenges_by_year": OrderedDict(
                    sorted(
                        challenges_by_year.items(),
                        key=lambda t: t[0],
                        reverse=True,
                    )
                ),
                "hosts": sorted(
                    # Order the hosts and only display hosts with more than
                    # 1 challenge
                    [h for h in hosts if h.host and host_count[h.host] > 1],
                    key=lambda h: host_count[h.host],
                    reverse=True,
                ),
            }
        )

        return context


class UsersChallengeList(UserIsNotAnonMixin, ListView):
    model = Challenge
    template_name = "challenges/challenge_users_list.html"

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_superuser:
            queryset = queryset.filter(
                Q(participants_group__in=self.request.user.groups.all())
                | Q(admins_group__in=self.request.user.groups.all())
            )
        return queryset


class ChallengeUpdate(
    UserIsChallengeAdminMixin,
    SuccessMessageMixin,
    ChallengeSubdomainObjectMixin,
    UpdateView,
):
    model = Challenge
    slug_field = "short_name__iexact"
    slug_url_kwarg = "challenge_short_name"
    form_class = ChallengeUpdateForm
    success_message = "Challenge successfully updated"
    template_name_suffix = "_update"


class ExternalChallengeCreate(
    UserIsStaffMixin, SuccessMessageMixin, CreateView
):
    model = ExternalChallenge
    form_class = ExternalChallengeUpdateForm
    success_message = (
        "Your challenge has been successfully submitted. "
        "An admin will review your challenge before it is published."
    )

    def form_valid(self, form):
        form.instance.creator = self.request.user
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("challenges:list")


class ExternalChallengeUpdate(
    UserIsStaffMixin, SuccessMessageMixin, UpdateView
):
    model = ExternalChallenge
    slug_field = "short_name__iexact"
    slug_url_kwarg = "short_name"
    form_class = ExternalChallengeUpdateForm
    template_name_suffix = "_update"
    success_message = "Challenge updated"

    def get_success_url(self):
        return reverse("challenges:list")


class ExternalChallengeList(UserIsStaffMixin, ListView):
    model = ExternalChallenge


class ExternalChallengeDelete(UserIsStaffMixin, DeleteView):
    model = ExternalChallenge
    slug_field = "short_name__iexact"
    slug_url_kwarg = "short_name"
    success_message = "External challenge was successfully deleted"

    def get_success_url(self):
        return reverse("challenges:external-list")

    def delete(self, request, *args, **kwargs):
        messages.success(self.request, self.success_message)
        return super().delete(request, *args, **kwargs)
