# -*- coding: utf-8 -*-
#
#  privacyIDEA is a fork of LinOTP
#  May 08, 2014 Cornelius Kölbel
#  License:  AGPLv3
#  contact:  http://www.privacyidea.org
#
#  2015-01-30   Adapt for migration to flask
#               Cornelius Kölbel <cornelius@privacyidea.org>
#
#
#  Copyright (C) 2010 - 2014 LSE Leading Security Experts GmbH
#  License:  LSE
#  contact:  http://www.linotp.org
#            http://www.lsexperts.de
#            linotp@lsexperts.de
#
# This code is free software; you can redistribute it and/or
# modify it under the terms of the GNU AFFERO GENERAL PUBLIC LICENSE
# License as published by the Free Software Foundation; either
# version 3 of the License, or any later version.
#
# This code is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU AFFERO GENERAL PUBLIC LICENSE for more details.
#
# You should have received a copy of the GNU Affero General Public
# License along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
__doc__="""The SMS token sends an SMS containing an OTP via some kind of
gateway. The gateways can be an SMTP or HTTP gateway or the special sipgate
protocol.
The Gateways are defined in the SMSProvider Modules.

This code is tested in tests/test_lib_tokens_sms
"""

import time
import datetime
import traceback

from privacyidea.lib.tokens.HMAC import HmacOtp
from privacyidea.api.lib.utils import getParam
from privacyidea.api.lib.utils import required

#from privacyidea.lib.validate import check_pin
#from privacyidea.lib.validate import split_pin_otp

from privacyidea.lib.config import get_from_config, get_privacyidea_config
#from privacyidea.lib.policy import PolicyClass
#from pylons import request, config, tmpl_context as c
from privacyidea.lib.log import log_with
from privacyidea.lib.smsprovider.SMSProvider import get_sms_provider_class
from json import loads
from gettext import gettext as _


from privacyidea.lib.tokens.hotptoken import HotpTokenClass

import logging
log = logging.getLogger(__name__)

keylen = {'sha1': 20,
          'sha256': 32,
          'sha512': 64}


class SmsTokenClass(HotpTokenClass):
    """
    implementation of the sms token class
    """
    def __init__(self, aToken):
        HotpTokenClass.__init__(self, aToken)
        self.set_type(u"sms")
        self.mode = ['challenge']
#        self.Policy = PolicyClass(request, config, c,
#                                  get_privacyIDEA_config())

    @classmethod
    def get_class_type(cls):
        """
        return the generic token class identifier
        """
        return "sms"

    @classmethod
    def get_class_prefix(cls):
        return "PISM"

    @classmethod
    def get_class_info(cls, key=None, ret='all'):
        """
        returns all or a subtree of the token definition

        :param key: subsection identifier
        :type key: string
        :param ret: default return value, if nothing is found
        :type ret: user defined

        :return: subsection if key exists or user defined
        :rtype : s.o.
        """

        res = {'type': 'sms',
               'title': _('SMS Token'),
               'description':
                    _('sms challenge-response token - hmac event based'),
               'init': {'title': {'html': 'smstoken.mako',
                                  'scope': 'enroll.title'},
                        'page': {'html': 'smstoken.mako',
                                 'scope'      : 'enroll'}
                        },
               'config': {'title': {'html': 'smstoken.mako',
                                    'scope': 'config.title'},
                          'page': {'html': 'smstoken.mako',
                                   'scope': 'config'}
               },
               'selfservice': {'enroll': {
                   'title': {'html': 'smstoken.mako',
                             'scope': 'selfservice.title.enroll'
                   },
                   'page': {'html': 'smstoken.mako',
                            'scope': 'selfservice.enroll'}
               }
               }
        }

        if key is not None and key in res:
            ret = res.get(key)
        else:
            if ret == 'all':
                ret = res

        return ret

    @log_with(log)
    def update(self, param, reset_failcount=True):
        """
        process initialization parameters

        :param param: dict of initialization parameters
        :type param: dict
        :return: nothing
        """
        # specific - phone
        phone = getParam(param, "phone", required)
        self.add_tokeninfo("phone", phone)

        # in case of the sms token, only the server must know the otpkey
        # thus if none is provided, we let create one (in the TokenClass)
        if "genkey" not in param and "otpkey" not in param:
            param['genkey'] = 1

        HotpTokenClass.update(self, param, reset_failcount)

    @log_with(log)
    def is_challenge_request(self, passw, user=None, options=None):
        """
        check, if the request would start a challenge

        if the passw contains only the pin, this request would
        trigger a challenge

        in this place as well the policy for a token is checked

        :param passw: password, which might be pin or pin+otp
        :param user: The authenticating user
        :param options: dictionary of additional request parameters

        :return: returns true or false
        """
        # Call the parents challenge request check
        is_challenge = HotpTokenClass.is_challenge_request(self,
                                                           passw, user,
                                                           options)

        return is_challenge

    @log_with(log)
    def create_challenge(self, transactionid, options=None):
        """
        create a challenge, which is submitted to the user

        :param transactionid: the id of this challenge
        :param options: the request context parameters / data
        :return: tuple of (bool, message and data)
                 bool, if submit was successful
                 message is submitted to the user
                 data is preserved in the challenge
                 attributes - additional attributes, which are displayed in the
                    output
        """
        success = False
        sms = ""
        return_message = ""
        attributes = {'state': transactionid}

        if self.is_active() is True:
            counter = self.get_otp_count()
            log.debug("counter=%r" % counter)
            self.inc_otp_counter(counter, reset=False)
            # At this point we must not bail out in case of an
            # Gateway error, since checkPIN is successful. A bail
            # out would cancel the checking of the other tokens
            try:

                if options is not None and type(options) == dict:
                    user = options.get('user', None)
                    #if user:
                    #    _sms_ret, message = self.Policy.get_auth_smstext(
                    #                            realm=user.realm)
                success, return_message = self._send_sms()
            except Exception as e:
                info = ("The PIN was correct, but the "
                        "SMS could not be sent: %r" % e)
                log.warning(info)
                return_message = info

        timeout = self._get_sms_timeout()
        expiry_date = datetime.datetime.now() + \
                                    datetime.timedelta(seconds=timeout)
        data = {'valid_until' : "%s" % expiry_date}

        return success, return_message, data, attributes

    @log_with(log)
    def check_otp(self, anOtpVal, counter, window, options=None):
        """
        check the otpval of a token against a given counter
        in the + window range

        :param passw: the to be verified passw/pin
        :type passw: string

        :return: counter if found, -1 if not found
        :rtype: int
        """
        ret = HotpTokenClass.check_otp(self, anOtpVal, counter, window)
        # TODO: Migration
        #if ret >= 0:
        #    if self.Policy.get_auth_AutoSMSPolicy():
        #        user = None
        #        message = "<otp>"
        #        if options is not None and type(options) == dict:
        #            user = options.get('user', None)
        #            if user:
        #                sms_ret, message = self.Policy.get_auth_smstext(
        ## realm=user.realm)
        #        self.incOtpCounter(ret, reset=False)
        #        success, message = self._send_sms(message=message)
        return ret

    @log_with(log)
    def _send_sms(self, message="<otp>"):
        """
        send sms

        :param message: the sms submit message - could contain placeholders
         like <otp> or <serial>
        :type message: string

        :return: submitted message
        :rtype: string
        """
        ret = None

        phone = self.get_tokeninfo("phone")
        otp = self.get_otp()[2]
        serial = self.get_serial()

        message = message.replace("<otp>", otp)
        message = message.replace("<serial>", serial)

        log.debug("sending SMS to phone number %s " % phone)
        (SMSProvider, SMSProviderClass) = \
            self._get_sms_provider()
        log.debug("smsprovider: %s, class: %s" % (SMSProvider,
                                                  SMSProviderClass))

        try:
            sms = get_sms_provider_class(SMSProvider, SMSProviderClass)()
        except Exception as exc:
            log.error("Failed to load SMSProvider: %r" % exc)
            log.error(traceback.format_exc())
            raise exc

        try:
            # now we need the config from the env
            log.debug("loading SMS configuration for class %s" % sms)
            config = self._get_sms_provider_config()
            log.debug("config: %r" % config)
            sms.load_config(config)
        except Exception as exc:
            log.error("Failed to load sms.providerConfig: %r" % exc)
            log.error(traceback.format_exc())
            raise Exception("Failed to load sms.providerConfig: %r" % exc)

        log.debug("submitMessage: %r, to phone %r" % (message, phone))
        ret = sms.submit_message(phone, message)
        return ret, message

    @log_with(log)
    def _get_sms_provider(self):
        """
        get the SMS Provider class definition

        :return: tuple of SMSProvider and Provider Class as string
        :rtype: tuple of (string, string)
        """
        smsProvider = get_from_config("sms.provider",
                                      default="privacyidea.lib.smsprovider."
                                              "HttpSMSProvider.HttpSMSProvider")
        (SMSProvider, SMSProviderClass) = smsProvider.rsplit(".", 1)
        return SMSProvider, SMSProviderClass

    @log_with(log)
    def _get_sms_provider_config(self):
        """
        load the defined sms provider config definition

        :return: dict of the sms provider definition
        :rtype: dict
        """
        tConfig = get_from_config("sms.providerConfig", "{}")
        config = loads(tConfig)
        return config

    @log_with(log)
    def _get_sms_timeout(self):
        """
        get the challenge time is in the specified range

        :return: the defined validation timeout in seconds
        :rtype:  int
        """
        try:
            timeout = int(get_from_config("sms.providerTimeout", 5 * 60))
        except Exception as ex:  # pragma nocover
            log.warning("SMSProviderTimeout: value error %r - reset to 5*60"
                                                                        % (ex))
            timeout = 5 * 60
        return timeout

