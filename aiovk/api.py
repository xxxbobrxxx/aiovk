# coding=utf8

import logging
import asyncio
import json

import aiohttp

from aiovk.utils import stringify_values, json_iter_parse, RequestsLikeResponse
from aiovk.exceptions import (VkAuthError, VkAPIMethodError, CAPTCHA_IS_NEEDED,
                              AUTHORIZATION_FAILED)
from aiovk.mixins import AuthMixin, InteractiveMixin


VERSION = '2.0a4'


logger = logging.getLogger('aiovk')


class Session(object):
    API_URL = 'https://api.vk.com/method/'

    def __init__(self, access_token=None, *, pause_between_requests=None):

        logger.info('API.__init__(access_token=%(access_token)r)', {'access_token': access_token})

        # self.api_version = api_version
        # self.default_timeout = default_timeout
        self.access_token = access_token
        self.access_token_is_needed = False
        self.pause_between_requests = pause_between_requests

        # self.requests_session = requests.Session()
        self.requests_session = aiohttp.ClientSession()

    @property
    @asyncio.coroutine
    def access_token(self):
        logger.info('Check that we need new access token')
        if self.access_token_is_needed:
            logger.info('We need new access token. Try to get it.')
            self.access_token, self._access_token_expires_in = yield from self.get_access_token()
            logger.info('Got new access token')
        logger.info('access_token = %r, expires in %s', self.censored_access_token, self._access_token_expires_in)
        return self._access_token

    @access_token.setter
    def access_token(self, value):
        self._access_token = value
        self._access_token_expires_in = None
        self.access_token_is_needed = not self._access_token

    @property
    def censored_access_token(self):
        if self._access_token:
            return '{}***{}'.format(self._access_token[:4], self._access_token[-4:])

    def get_user_login(self):
        logger.info('Do nothing to get user login')

    @asyncio.coroutine
    def get_access_token(self):
        """
        Dummy method
        """
        logger.info('API.get_access_token()')
        return self._access_token, self._access_token_expires_in

    @asyncio.coroutine
    def make_request(self, method_request, **method_kwargs):

        logger.info('Prepare API Method request')

        response = yield from self.send_api_request(method_request)
        response.raise_for_status()

        # there are may be 2 dicts in one JSON
        # for example: {'error': ...}{'response': ...}
        errors = []
        error_codes = []
        for data in json_iter_parse((yield from response.text())):
            if 'error' in data:
                error_data = data['error']
                if error_data['error_code'] == CAPTCHA_IS_NEEDED:
                    return self.on_captcha_is_needed(error_data, method_request)

                error_codes.append(error_data['error_code'])
                errors.append(error_data)

            if 'response' in data:
                for error in errors:
                    logger.warning(str(error))

                return data['response']

        if AUTHORIZATION_FAILED in error_codes:  # invalid access token
            logger.info('Authorization failed. Access token will be dropped')
            self.access_token = None
            return (yield from self.make_request(method_request, **method_kwargs))
        elif method_request._raw:

            return json.loads((yield from response.text()))

        else:
            raise VkAPIMethodError(errors[0])

    @asyncio.coroutine
    def send_api_request(self, request):

        if not request._raw:

            url = self.API_URL + request._method_name
            timeout = request._api._timeout

        else:

            url = request._method_name
            timeout = request._timeout

        method_args = request._api._method_default_args.copy()
        method_args.update(stringify_values(request._method_args))
        if (yield from self.access_token):

            method_args['access_token'] = yield from self.access_token

        response = yield from self.send_request(url, method_args, timeout)
        return response

    @asyncio.coroutine
    def send_request(self, url, data, timeout):

        # dirty realization
        yield from asyncio.sleep(self.pause_between_requests)
        response = yield from asyncio.wait_for(
            self.requests_session.post(url, data=data),
            timeout=timeout,
        )
        return RequestsLikeResponse(response)

    def on_captcha_is_needed(self, error_data, method_request):
        """
        Default behavior on CAPTCHA is to raise exception
        Reload this in child
        """
        raise VkAPIMethodError(error_data)

    def auth_code_is_needed(self, content, session):
        """
        Default behavior on 2-AUTH CODE is to raise exception
        Reload this in child
        """
        raise VkAuthError('Authorization error (2-factor code is needed)')

    def auth_captcha_is_needed(self, content, session):
        """
        Default behavior on CAPTCHA is to raise exception
        Reload this in child
        """
        raise VkAuthError('Authorization error (captcha)')

    def phone_number_is_needed(self, content, session):
        """
        Default behavior on PHONE NUMBER is to raise exception
        Reload this in child
        """
        logger.error('Authorization error (phone number is needed)')
        raise VkAuthError('Authorization error (phone number is needed)')


class API(object):
    def __init__(self, session, timeout=10, **method_default_args):
        self._session = session
        self._timeout = timeout
        self._method_default_args = method_default_args

    def __getattr__(self, method_name):
        return Request(self, method_name)

    def __call__(self, method_name, **method_kwargs):
        return getattr(self, method_name)(**method_kwargs)

    def upload(self, url, *, timeout=None, **method_kwargs):

        return Request(self, url, True, timeout)(**method_kwargs)


class Request(object):
    __slots__ = ('_api', '_method_name', '_method_args', '_raw', '_timeout')

    def __init__(self, api, method_name, raw=False, timeout=None):
        self._api = api
        self._method_name = method_name
        self._raw = raw
        self._timeout = timeout

    def __getattr__(self, method_name):
        return Request(self._api, self._method_name + '.' + method_name)

    def __call__(self, **method_args):
        self._method_args = method_args
        return self._api._session.make_request(self)


class AuthSession(AuthMixin, Session):
    pass


class InteractiveSession(InteractiveMixin, Session):
    pass


class InteractiveAuthSession(InteractiveMixin, AuthSession):
    pass
