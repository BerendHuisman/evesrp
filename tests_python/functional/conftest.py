from __future__ import absolute_import

import os
import socket
from six.moves.socketserver import ThreadingMixIn
import threading
import tempfile
from wsgiref import simple_server

import pytest
from selenium import webdriver
from selenium.webdriver.common.keys import Keys


class ThreadingWSGIServer(ThreadingMixIn, simple_server.WSGIServer):
    
    # So we can use addresses accidentally left in use (like by a badly closing
    # test run).
    allow_reuse_address = True


@pytest.yield_fixture(scope='session')
def driver():
    browser = os.environ.get('SELENIUM_DRIVER', 'PhantomJS')
    # Check to see if we're running on Travis. Explicitly check the value
    # of TRAVIS as tox sets it to an empty string.
    if os.environ.get('TRAVIS') == 'true':
        username = os.environ['SAUCE_USERNAME']
        access_key = os.environ['SAUCE_ACCESS_KEY']
        default_capabilities = getattr(webdriver.DesiredCapabilities,
                                       browser.upper())
        capabilities = default_capabilities.copy()
        capabilities['tunnel-identifier'] = os.environ['TRAVIS_JOB_NUMBER']
        capabilities['build'] = os.environ['TRAVIS_BUILD_NUMBER']
        capabilities['tags'] = ['CI']
        sauce_url = "{}:{}@localhost:4445".format( username, access_key)
        command_url = "http://{}/wd/hub".format(sauce_url)
        driver = webdriver.Remote(desired_capabilities=capabilities,
                                      command_executor=command_url)
    else:
        driver = getattr(webdriver, browser)()
    yield driver
    driver.quit()


@pytest.yield_fixture
def app_server(evesrp_app):
    # Use port 0 to get a port assigned to us by the OS
    server = simple_server.make_server('', 0, evesrp_app,
                                       server_class=ThreadingWSGIServer)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.start()
    yield server
    server.shutdown()
    server_thread.join()


@pytest.fixture
def server_port(app_server):
    port = app_server.socket.getsockname()[1]
    return port


@pytest.fixture
def server_address(app_server):
    host, port = app_server.socket.getsockname()
    if host in ('0.0.0.0', '::'):
        host = 'localhost'
    address = "http://{}:{}".format(host, port)
    return address


@pytest.yield_fixture
def app_config(app_config):
    # If using an SQLite in-memory DB, change it to an actual file DB so it can
    # be shared between threads (I'm not going to try enforcing a recent SQLite
    # version to use shared in-memory databases across threads).
    if app_config['SQLALCHEMY_DATABASE_URI'] == 'sqlite:///':
        _, path = tempfile.mkstemp()
        app_config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///{}'.format(path)
    else:
        path = None
    yield app_config
    if path is not None:
        os.remove(path)
