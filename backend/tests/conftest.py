# -*- coding: utf-8 -*-
"""pytest bootstrap: set environment BEFORE importing the app so the
fail-fast SECRET_KEY / JWT_SECRET checks pass, and keep tests off the real
database (MONGO_URI empty -> app runs in mock/demo mode, db=None)."""
import os
import sys

os.environ['FLASK_ENV'] = 'development'
os.environ['SECRET_KEY'] = 'test-secret-key'
os.environ['JWT_SECRET'] = 'test-jwt-secret-key'
os.environ['MONGO_URI'] = ''
os.environ['REDIS_URL'] = 'redis://localhost:6399'

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
