from django.conf.urls import include
from django.urls import path, re_path

from grandchallenge.profiles.forms import SignupFormExtra
from grandchallenge.profiles.views import (
    login_redirect,
    profile_edit_redirect,
    profile,
    signup,
    signin,
    signup_complete,
    profile_edit,
)

urlpatterns = [
    path(
        "signup/",
        signup,
        {"signup_form": SignupFormExtra},
        name="profile_signup",
    ),
    path("signin/", signin, name="profile_signin"),
    path("signup_complete/", signup_complete, name="profile_signup_complete"),
    path("login-redirect/", login_redirect, name="login_redirect"),
    path("profile/edit/", profile_edit_redirect, name="profile_redirect_edit"),
    path("profile/", profile, name="profile_redirect"),
    re_path(
        r"^(?P<username>[\@\.\+\w-]+)/edit/$",
        profile_edit,
        name="userena_profile_edit",
    ),
    path("", include("userena.urls")),
]
