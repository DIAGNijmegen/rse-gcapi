from urllib.parse import urljoin

from django.conf import settings
from django.contrib.sites.models import Site
from django.urls import reverse as reverse_org


def reverse(viewname, urlconf=None, args=None, kwargs=None, current_app=None):
    """ Reverse url, but try to use subdomain to designate site where possible.
    This means 'site1' will not get url 'hostname/site/site1' but rather
    'challenge.hostname'
    """
    kwargs = kwargs or {}

    scheme = settings.DEFAULT_SCHEME

    host = Site.objects.get_current().domain.lower()
    domain = f"{scheme}://{host}"

    if "challenge_short_name" in kwargs:
        challenge_short_name = kwargs.pop("challenge_short_name")
        domain = f"{scheme}://{challenge_short_name}.{host}"
        urlconf = urlconf or settings.SUBDOMAIN_URL_CONF
    else:
        urlconf = urlconf or settings.ROOT_URLCONF

    if "views.flatpage" in viewname.lower() and "url" in kwargs:
        # Fix for a long standing bug in django flatpages
        # https://code.djangoproject.com/ticket/15658
        kwargs.update({"url": kwargs["url"].lstrip("/")})

    path = reverse_org(
        viewname,
        urlconf=urlconf,
        args=args,
        kwargs=kwargs,
        current_app=current_app,
    )

    return urljoin(domain.lower(), path)
