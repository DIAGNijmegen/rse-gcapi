import os
import sys

from django.core.wsgi import get_wsgi_application

# Appending app_path to path allows us to easily keep the apps in the subfolder
app_path = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
)
sys.path.append(os.path.join(app_path, "grandchallenge"))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# This application object is used by any WSGI server configured to use this
# file. This includes Django's development server, if the WSGI_APPLICATION
# setting points here.

application = get_wsgi_application()

# Apply WSGI middleware here.
# from helloworld.wsgi import HelloWorldApplication
# application = HelloWorldApplication(application)
