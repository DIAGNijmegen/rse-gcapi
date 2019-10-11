from django.conf import settings
from django.contrib.sites.models import Site
from django.core.mail import send_mail

from grandchallenge.evaluation.templatetags.evaluation_extras import user_error
from grandchallenge.subdomains.utils import reverse


def send_failed_job_email(job):
    message = (
        f"Unfortunately the evaluation for the submission to "
        f"{job.submission.challenge.short_name} failed with an error. "
        f"The error message is:\n\n"
        f"{user_error(job.output)}\n\n"
        f"You may wish to try and correct this, or contact the challenge "
        f"organizers. The following information may help them:\n"
        f"User: {job.submission.creator.username}\n"
        f"Job ID: {job.pk}\n"
        f"Submission ID: {job.submission.pk}"
    )
    recipient_emails = [o.email for o in job.submission.challenge.get_admins()]
    recipient_emails.append(job.submission.creator.email)
    for email in recipient_emails:
        send_mail(
            subject=(
                f"[{Site.objects.get_current().domain.lower()}] "
                f"[{job.submission.challenge.short_name.lower()}] "
                f"Evaluation Failed"
            ),
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
        )


def send_new_result_email(result):
    challenge = result.job.submission.challenge

    recipient_emails = [o.email for o in challenge.get_admins()]
    message = (
        f"There is a new result for {challenge.short_name} from "
        f"{result.job.submission.creator.username}."
    )
    if result.published:
        leaderboard_url = reverse(
            "evaluation:result-list",
            kwargs={"challenge_short_name": challenge.short_name},
        )
        message += (
            f"You can view the result on the leaderboard here: "
            f"{leaderboard_url}"
        )
        recipient_emails.append(result.job.submission.creator.email)
    else:
        message += (
            f"You can publish the result on the leaderboard here: "
            f"{result.get_absolute_url()}"
        )
    for email in recipient_emails:
        send_mail(
            subject=(
                f"[{Site.objects.get_current().domain.lower()}] "
                f"[{challenge.short_name.lower()}] "
                f"New Result"
            ),
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
        )
