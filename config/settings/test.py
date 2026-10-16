from .base import *

DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]

# Speed things up in tests
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
