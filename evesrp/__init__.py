from __future__ import absolute_import
from decimal import Decimal
import locale
import os
import requests
import warnings
from flask import Flask, current_app, g
from flask.ext import sqlalchemy
from flask.ext.wtf.csrf import CsrfProtect
import six
from sqlalchemy.engine import Engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.schema import MetaData
from werkzeug.utils import import_string
from .transformers import Transformer


db = sqlalchemy.SQLAlchemy()
# Patch Flask-SQLAlchemy to use a custom Metadata instance with a naming scheme
# for constraints.
def _patch_metadata():
    naming_convention = {
        'fk': ('fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s'
                '_%(referred_column_0_name)s'),
        'pk': 'pk_%(table_name)s',
        'ix': 'ix_%(table_name)s_%(column_0_name)s',
        'ck': 'ck_%(table_name)s_%(constraint_name)s',
        'uq': 'uq_%(table_name)s_%(column_0_name)s',
    }
    metadata = MetaData(naming_convention=naming_convention)
    base = declarative_base(cls=sqlalchemy.Model, name='Model',
                            metaclass=sqlalchemy._BoundDeclarativeMeta,
                            metadata=metadata)
    base.query = sqlalchemy._QueryProperty(db)
    db.Model = base
_patch_metadata()


from .util import DB_STATS, AcceptRequest


__version__ = u'0.9.7-dev'


requests_session = requests.Session()


# Set default locale
locale.setlocale(locale.LC_ALL, '')


csrf = CsrfProtect()


# Ensure models are declared
from . import models
from .auth import models as auth_models
from .auth import AuthMethod


def create_app(config=None, **kwargs):
    app = Flask('evesrp', **kwargs)
    app.request_class = AcceptRequest
    app.config.from_object('evesrp.default_config')
    if config is not None:
        app.config.from_pyfile(config)
    if app.config['SECRET_KEY'] is None and 'SECRET_KEY' in os.environ:
        app.config['SECRET_KEY'] = os.environ['SECRET_KEY']

    # Register SQLAlchemy monitoring before the DB is connected
    app.before_request(sqlalchemy_before)

    db.init_app(app)

    from .views.login import login_manager
    login_manager.init_app(app)

    before_csrf = list(app.before_request_funcs[None])
    csrf.init_app(app)
    # Remove the context processor that checks CSRF values. All it is used for
    # is the template function.
    app.before_request_funcs[None] = before_csrf

    from .views import index, error_page, divisions, login, requests, api
    app.add_url_rule(rule=u'/', view_func=index)
    for error_code in (400, 403, 404, 500):
        app.register_error_handler(error_code, error_page)
    app.register_blueprint(divisions.blueprint, url_prefix='/division')
    app.register_blueprint(login.blueprint)
    app.register_blueprint(requests.blueprint, url_prefix='/request')
    app.register_blueprint(api.api, url_prefix='/api')
    app.register_blueprint(api.filters, url_prefix='/api/filter')

    from .views import request_count
    app.add_template_global(request_count)

    from .json import SRPEncoder
    app.json_encoder=SRPEncoder

    _config_requests_session(app)
    _config_url_converters(app)
    _config_authmethods(app)
    _config_killmails(app)

    # Configure the Jinja context
    # Inject variables into the context
    from .auth import PermissionType
    @app.context_processor
    def inject_enums():
        return {
            'ActionType': models.ActionType,
            'PermissionType': PermissionType,
            'app_version': __version__,
            'site_name': app.config['SRP_SITE_NAME'],
            'url_for_page': requests.url_for_page,
        }
    # Auto-trim whitespace
    app.jinja_env.trim_blocks = True
    app.jinja_env.lstrip_blocks = True

    return app


# SQLAlchemy performance logging
def sqlalchemy_before():
    if DB_STATS.total_queries > 0:
        current_app.logger.debug(u"{} queries in {} ms.".format(
                DB_STATS.total_queries,
                round(DB_STATS.total_time * 1000, 3)))
    DB_STATS.clear()
    g.DB_STATS = DB_STATS


# Utility function for creating instances from dicts
def _instance_from_dict(instance_descriptor):
    type_name = instance_descriptor.pop('type')
    Type = import_string(type_name)
    return Type(**instance_descriptor)


# Utility function for raising config deprecation warnings
def _deprecated_object_instance(key, value):
    warnings.warn(u"Non-basic data types in configuration values are deprecated"
                 u"({}: {})".format(key, value), DeprecationWarning,
                 stacklevel=2)


# Auth setup
def _config_authmethods(app):
    auth_methods = []
    # Once the deprecated config value support is removed, this can be
    # rewritten as a dict comprehension
    for method in app.config['SRP_AUTH_METHODS']:
        if isinstance(method, dict):
            auth_methods.append(_instance_from_dict(method))
        elif isinstance(method, AuthMethod):
            _deprecated_object_instance('SRP_AUTH_METHODS', method)
            auth_methods.append(method)
    app.auth_methods = auth_methods


# Request detail URL setup
def _config_url_converters(app):
    url_transformers = {}
    for config_key, config_value in app.config.items():
        # Skip null config values
        if config_value is None:
            continue
        # Look for config keys in the format 'SRP_*_URL_TRANSFORMERS'
        if not config_key.endswith('_URL_TRANSFORMERS')\
                or not config_key.startswith('SRP_'):
            continue
        attribute = config_key.replace('SRP_', '', 1)
        attribute = attribute.replace('_URL_TRANSFORMERS', '', 1)
        attribute = attribute.lower()
        # Create Transformer instances for this attribute
        transformers = {}
        for transformer_config in config_value:
            if isinstance(transformer_config, tuple):
                # Special case for Transformers: A 2-tuple in the form:
                # (u'Transformer Name',
                #     'http://example.com/transformer/slug/{}')
                transformer = Transformer(*transformer_config)
            elif isinstance(transformer_config, dict):
                # Standard instance dictionary format
                # Provide a default type value
                transformer_config.setdefault('type',
                        'evesrp.transformers.Transformer')
                transformer = _instance_from_dict(transformer_config)
            elif isinstance(transformer_config, Transformer):
                # DEPRECATED: raw Transformer instance
                _deprecated_object_instance(config_key, transformer_config)
                transformer = transformer_config
            transformers[transformer.name] = transformer
        url_transformers[attribute] = transformers
    app.url_transformers = url_transformers


# Requests session setup
def _config_requests_session(app):
    try:
        ua_string = app.config['SRP_USER_AGENT_STRING']
    except KeyError as outer_exc:
        try:
            ua_string = 'EVE-SRP/{version} ({email})'.format(
                    email=app.config['SRP_USER_AGENT_EMAIL'],
                    version=__version__)
        except KeyError as inner_exc:
            raise inner_exc
    requests_session = requests.Session()
    requests_session.headers.update({'User-Agent': ua_string})
    app.requests_session = requests_session


# Killmail verification
def _config_killmails(app):
    killmail_sources = []
    # For now, use a loop with checks. After removing the depecated config
    # method it can be rewritten as a list comprehension
    for source in app.config['SRP_KILLMAIL_SOURCES']:
        if isinstance(source, six.string_types):
            killmail_sources.append(import_string(source))
        elif isinstance(source, type):
            _deprecated_object_instance('SRP_KILLMAIL_SOURCES', source)
            killmail_sources.append(source)
    app.killmail_sources = killmail_sources


# Work around DBAPI-specific issues with Decimal subclasses.
# Specifically, almost everything besides pysqlite and psycopg2 raise
# exceptions if an instance of a Decimal subclass as opposed to an instance of
# Decimal itself is passed in as a value for a Numeric column.
@db.event.listens_for(Engine, 'before_execute', retval=True)
def _workaround_decimal_subclasses(conn, clauseelement, multiparams, params):
    def filter_decimal_subclasses(parameters):
        for key in six.iterkeys(parameters):
            value = parameters[key]
            # Only get instances of subclasses of Decimal, not direct
            # Decimal instances
            if type(value) != Decimal and isinstance(value, Decimal):
                parameters[key] = Decimal(value)

    if multiparams:
        for mp in multiparams:
            if isinstance(mp, dict):
                filter_decimal_subclasses(mp)
            elif isinstance(mp, list):
                for parameters in mp:
                    filter_decimal_subclasses(parameters)
    return clauseelement, multiparams, params
