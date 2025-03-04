#!/usr/bin/env python3
#
# Copyright (c) Bo Peng and the University of Texas MD Anderson Cancer Center
# Distributed under the terms of the 3-clause BSD License.

import json
import os
import sys
import time
from subprocess import Popen
from urllib.parse import urljoin

import pytest
import requests
from selenium import webdriver
from selenium.webdriver import Chrome, Firefox, Remote
from test_utils import Notebook
from testpath.tempdir import TemporaryDirectory

pjoin = os.path.join


def _wait_for_server(proc, info_file_path):
    """Wait 30 seconds for the notebook server to start"""
    for i in range(300):
        if proc.poll() is not None:
            raise RuntimeError("Notebook server failed to start")
        if os.path.exists(info_file_path):
            try:
                with open(info_file_path) as f:
                    return json.load(f)
            except ValueError:
                # If the server is halfway through writing the file, we may
                # get invalid JSON; it should be ready next iteration.
                pass
        time.sleep(0.1)
    raise RuntimeError("Didn't find %s in 30 seconds", info_file_path)


@pytest.fixture(scope='session')
def notebook_server():
    info = {}
    temp_dir = TemporaryDirectory()
    td = temp_dir.name
    # do not use context manager because of https://github.com/vatlab/sos-notebook/issues/214
    if True:
        nbdir = info['nbdir'] = pjoin(td, 'notebooks')
        os.makedirs(pjoin(nbdir, u'sub ∂ir1', u'sub ∂ir 1a'))
        os.makedirs(pjoin(nbdir, u'sub ∂ir2', u'sub ∂ir 1b'))
        # print(nbdir)
        info['extra_env'] = {
            'JUPYTER_CONFIG_DIR': pjoin(td, 'jupyter_config'),
            'JUPYTER_RUNTIME_DIR': pjoin(td, 'jupyter_runtime'),
            'IPYTHONDIR': pjoin(td, 'ipython'),
        }
        env = os.environ.copy()
        env.update(info['extra_env'])

        command = [
            sys.executable,
            '-m',
            'jupyterlab',
            '--no-browser',
            '--notebook-dir',
            nbdir,
            # run with a base URL that would be escaped,
            # to test that we don't double-escape URLs
            #'--NotebookApp.base_url=/a@b/',
        ]
        print("command=", command)
        proc = info['popen'] = Popen(command, cwd=nbdir, env=env)
        info_file_path = pjoin(td, 'jupyter_runtime',
                               'jpserver-%i.json' % proc.pid)
        info.update(_wait_for_server(proc, info_file_path))

        print("Notebook server info:", info)
        yield info

    # manually try to clean up, which would fail under windows because
    # a permission error caused by iPython history.sqlite.
    try:
        temp_dir.cleanup()
    except:
        pass
    # Shut the server down
    requests.post(
        urljoin(info['url'], 'api/shutdown'),
        headers={'Authorization': 'token ' + info['token']})


def make_sauce_driver():
    """This function helps travis create a driver on Sauce Labs.

    This function will err if used without specifying the variables expected
    in that context.
    """

    username = os.environ["SAUCE_USERNAME"]
    access_key = os.environ["SAUCE_ACCESS_KEY"]
    capabilities = {
        "tunnel-identifier": os.environ["TRAVIS_JOB_NUMBER"],
        "build": os.environ["TRAVIS_BUILD_NUMBER"],
        "tags": [os.environ['TRAVIS_PYTHON_VERSION'], 'CI'],
        "platform": "Windows 10",
        "browserName": os.environ['JUPYTER_TEST_BROWSER'],
        "version": "latest",
    }
    if capabilities['browserName'] == 'firefox':
        # Attempt to work around issue where browser loses authentication
        capabilities['version'] = '57.0'
    hub_url = "%s:%s@localhost:4445" % (username, access_key)
    print("Connecting remote driver on Sauce Labs")
    driver = Remote(
        desired_capabilities=capabilities,
        command_executor="http://%s/wd/hub" % hub_url)
    return driver


@pytest.fixture(scope='session')
def selenium_driver():

    if "JUPYTER_TEST_BROWSER" not in os.environ:
        os.environ["JUPYTER_TEST_BROWSER"] = 'chrome'

    if os.environ.get('SAUCE_USERNAME'):
        driver = make_sauce_driver()
    elif os.environ.get('JUPYTER_TEST_BROWSER') == 'live':
        driver = Chrome()
    elif os.environ.get('JUPYTER_TEST_BROWSER') == 'chrome':
        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--window-size=1420,1080')
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--disable-gpu')
        driver = Chrome(options=chrome_options)
    elif os.environ.get('JUPYTER_TEST_BROWSER') == 'firefox':
        driver = Firefox()
    else:
        raise ValueError(
            'Invalid setting for JUPYTER_TEST_BROWSER. Valid options include live, chrome, and firefox'
        )

    yield driver

    # Teardown
    driver.quit()


@pytest.fixture(scope='module')
def authenticated_browser(selenium_driver, notebook_server):
    selenium_driver.jupyter_server_info = notebook_server
    selenium_driver.get("{url}?token={token}".format(**notebook_server))
    return selenium_driver


@pytest.fixture(scope="class")
def notebook(authenticated_browser):
    return Notebook.new_notebook(
        authenticated_browser, kernel_name='kernel-sos')
