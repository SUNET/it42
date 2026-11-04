import os

from django.core.wsgi import get_wsgi_application

from it42.common.role import settings_module

os.environ.setdefault("DJANGO_SETTINGS_MODULE", settings_module())
application = get_wsgi_application()
