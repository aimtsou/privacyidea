# -*- coding: utf-8 -*-
#
#  privacyIDEA is a fork of LinOTP
#  Nov 11, 2014 Cornelius Kölbel
#  License:  AGPLv3
#  contact:  http://www.privacyidea.org
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
__doc__="""The config module takes care about storing server configuration in
the Config database table.

It provides functions to retrieve (get) and and set configuration.

The code is tested in tests/test_lib_config
"""

import logging
import sys
import inspect

from flask import current_app

from .log import log_with
from ..models import Config, db

from .crypto import encryptPassword
from .crypto import decryptPassword
from .resolvers.UserIdResolver import UserIdResolver
from privacyidea.lib.cache import cache
from datetime import datetime

log = logging.getLogger(__name__)

ENCODING = 'utf-8'


@cache.memoize(10)
def get_privacyidea_config():
    # timestamp = Config.query.filter_by(Key="privacyidea.timestamp").first()
    return get_from_config()


@log_with(log)
@cache.memoize(10)
def get_from_config(key=None, default=None):
    """
    :param Key: A key to retrieve
    :type Key: string
    :param default: The default value, if the Config does not exist in the DB
    :return: If key is None, then a dictionary is returned. I a certain key
              is given a string/bool is returned.
    """
    rvalue = ""
    if key:
        q = Config.query.filter_by(Key=key).first()
        if q:
            rvalue = q.Value
            if q.Type == "password":
                rvalue = decryptPassword(rvalue)
        else:
            rvalue = default
    else:
        rvalue = {}
        q = Config.query.all()
        for entry in q:
            value = entry.Value
            if entry.Type == "password":
                value = decryptPassword(value)
            rvalue[entry.Key] = value

    return rvalue


@cache.memoize(10)
def get_resolver_types():
    """
    Return a simple list of the type names of the resolvers.
    :return: array of resolvertypes like 'passwdresolver'
    :rtype: array
    """
    resolver_types = []
    if "pi_resolver_types" in current_app.config:
        resolver_types = current_app.config["pi_resolver_types"]
    else:
        (_r_classes, r_types) = get_resolver_class_dict()
        resolver_types = r_types.values()
        current_app.config["pi_resolver_types"] = resolver_types
    
    return resolver_types


@cache.memoize(10)
def get_resolver_classes():
    """
    Returns a list of the available resolver classes like:
    [<class 'privacyidea.lib.resolvers.PasswdIdResolver.IdResolver'>,
    <class 'privacyidea.lib.resolvers.UserIdResolver.UserIdResolver'>]

    :return: array of resolver classes
    :rtype: array
    """
    resolver_classes = []
    if "pi_resolver_classes" in current_app.config:
        resolver_classes = current_app.config["pi_resolver_classes"]
    else:
        (r_classes, _r_types) = get_resolver_class_dict()
        resolver_classes = r_classes.values()
        current_app.config["pi_resolver_classes"] = resolver_classes
    
    return resolver_classes


@cache.memoize(10)
def get_token_class_dict():
    """
    get a dictionary of the token classes and a dictionary of the
    token types:

    ({'privacyidea.lib.tokens.hotptoken.HotpTokenClass':
      <class 'privacyidea.lib.tokens.hotptoken.HotpTokenClass'>,
      'privacyidea.lib.tokens.totptoken.TotpTokenClass':
      <class 'privacyidea.lib.tokens.totptoken.TotpTokenClass'>},

      {'privacyidea.lib.tokens.hotptoken.HotpTokenClass':
      'hotp',
      'privacyidea.lib.tokens.totptoken.TotpTokenClass':
      'totp'})

    :return: tuple of two dicts
    """
    from .tokenclass import TokenClass

    tokenclass_dict = {}
    tokentype_dict = {}
    modules = get_token_module_list()
    for module in modules:
        for name in dir(module):
            obj = getattr(module, name)
            if inspect.isclass(obj) and issubclass(obj, TokenClass):
                # We must not process imported classes!
                if obj.__module__ == module.__name__:
                    try:
                        class_name = "%s.%s" % (module.__name__, obj.__name__)
                        tokenclass_dict[class_name] = obj
                        if hasattr(obj, 'get_class_type'):
                            tokentype_dict[class_name] = obj.get_class_type()
                    except Exception as e:  # pragma nocover
                        log.error("error constructing token_class_dict: %r" % e)

    return tokenclass_dict, tokentype_dict


@cache.memoize(10)
def get_token_class(tokentype):
    """
    This takes a token type like "hotp" and returns a class
    like <class privacidea.lib.tokens.hotptoken.HotpTokenClass>
    :return: The tokenclass for the given type
    :rtype: tokenclass
    """
    class_dict, type_dict = get_token_class_dict()
    tokenmodule = ""
    tokenclass = None
    for module, ttype in type_dict.iteritems():
        if ttype.lower() == tokentype.lower():
            tokenmodule = module
            break
    if tokenmodule:
        tokenclass = class_dict.get(tokenmodule)

    return tokenclass


@cache.memoize(10)
def get_token_types():
    """
    Return a simple list of the type names of the tokens.
    :return: array of tokentypes like 'hotp', 'totp'...
    :rtype: array
    """
    tokentypes = []
    if "pi_token_types" in current_app.config:
        tokentypes = current_app.config["pi_token_types"]
    else:
        (_t_classes, t_types) = get_token_class_dict()
        tokentypes = t_types.values()
        current_app.config["pi_token_types"] = tokentypes

    return tokentypes


@cache.memoize(10)
def get_token_prefix(tokentype=None, default=None):
    """
    Return the token prefix for a tokentype as it is defined in the
    tokenclass. If no tokentype is specified, we return a dictionary
    with the tokentypes as keys.
    :param tokentype: the type of the token like "hotp" or "totp"
    :type tokentype: basestring
    :param default: If the tokentype is not found, we return default
    :type default: basestring
    :return: the prefix of the tokentype or the dict with all prefixes
    :rtype: string or dict
    """
    prefix_dict = {}
    for tokenclass in get_token_classes():
        prefix_dict[tokenclass.get_class_type()] = tokenclass.get_class_prefix()

    if tokentype:
        ret = prefix_dict.get(tokentype, default)
    else:
        ret = prefix_dict
    return ret


@cache.memoize(10)
def get_token_classes():
    """
    Returns a list of the available token classes like:
    [<class 'privacyidea.lib.tokens.totptoken.TotpTokenClass'>,
    <class 'privacyidea.lib.tokens.hotptoken.HotpTokenClass'>]

    :return: array of token classes
    :rtype: array
    """
    token_classes = []
    if "pi_token_classes" in current_app.config:
        token_classes = current_app.config["pi_token_classes"]
    else:
        (t_classes, _t_types) = get_token_class_dict()
        token_classes = t_classes.values()
        current_app.config["pi_token_classes"] = token_classes

    return token_classes


@cache.memoize(10)
def get_resolver_class_dict():
    """
    get a dictionary of the resolver classes and a dictionary
    of the resolver types:
    
    ({'privacyidea.lib.resolvers.PasswdIdResolver.IdResolver':
      <class 'privacyidea.lib.resolvers.PasswdIdResolver.IdResolver'>,
      'privacyidea.lib.resolvers.PasswdIdResolver.UserIdResolver':
      <class 'privacyidea.lib.resolvers.UserIdResolver.UserIdResolver'>},

      {'privacyidea.lib.resolvers.PasswdIdResolver.IdResolver':
      'passwdresolver',
      'privacyidea.lib.resolvers.PasswdIdResolver.UserIdResolver':
      'UserIdResolver'})

    :return: tuple of two dicts.
    """
    resolverclass_dict = {}
    resolverprefix_dict = {}

    modules = get_resolver_module_list()
    base_class_repr = "privacyidea.lib.resolvers.UserIdResolver.UserIdResolver"
    for module in modules:
        log.debug("module: %s" % module)
        for name in dir(module):
            obj = getattr(module, name)
            # There are other classes like HMAC in the lib.tokens module,
            # which we do not want to load.
            if inspect.isclass(obj) and (issubclass(obj, UserIdResolver) or
                                             obj == UserIdResolver):
                # We must not process imported classes!
                # if obj.__module__ == module.__name__:
                try:
                    class_name = "%s.%s" % (module.__name__, obj.__name__)
                    resolverclass_dict[class_name] = obj

                    prefix = class_name.split('.')[1]
                    if hasattr(obj, 'getResolverClassType'):
                        prefix = obj.getResolverClassType()

                    resolverprefix_dict[class_name] = prefix

                except Exception as e:  # pragma nocover
                    log.error("error constructing resolverclass_list: %r"
                                 % e)

    return (resolverclass_dict, resolverprefix_dict)


@log_with(log)
@cache.memoize(10)
def get_resolver_list():
    """
    get the list of the module names of the resolvers like
    "resolvers.PasswdIdResolver".

    :return: list of resolver names from the config file
    :rtype: set
    """
    module_list = set()

    module_list.add("resolvers.PasswdIdResolver")
    module_list.add("resolvers.LDAPIdResolver")
    module_list.add("resolvers.SCIMIdResolver")
    module_list.add("resolvers.SQLIdResolver")

    # Dynamic Resolver modules
    # TODO: Migration
    # config_modules = config.get("privacyideaResolverModules", '')
    config_modules = None
    log.debug("%s" % config_modules)
    if config_modules:
        # in the config *.ini files we have some line continuation slashes,
        # which will result in ugly module names, but as they are followed by
        # \n they could be separated as single entries by the following two
        # lines
        lines = config_modules.splitlines()
        coco = ",".join(lines)
        for module in coco.split(','):
            if module.strip() != '\\':
                module_list.add(module.strip())

    return module_list


@log_with(log)
@cache.memoize(10)
def get_token_list():
    """
    get the list of the tokens
    :return: list of token names from the config file
    """
    module_list = set()

    # TODO: migrate the implementations and uncomment
    module_list.add("tokens.daplugtoken")
    module_list.add("tokens.hotptoken")
    module_list.add("tokens.motptoken")
    module_list.add("tokens.passwordtoken")
    module_list.add("tokens.remotetoken")
    module_list.add("tokens.spasstoken")
    module_list.add("tokens.sshkeytoken")
    module_list.add("tokens.totptoken")
    module_list.add("tokens.yubicotoken")
    module_list.add("tokens.yubikeytoken")
    module_list.add("tokens.radiustoken")
    module_list.add("tokens.smstoken")
    #module_list.add(".tokens.emailtoken.")
    #module_list.add(".tokens.ocra2token")

    #module_list.add(".tokens.tagespassworttoken")
    #module_list.add(".tokens.vascotoken")
    
    # Dynamic Resolver modules
    # TODO: Migration
    # config_modules = config.get("privacyideaResolverModules", '')
    config_modules = None
    log.debug("%s" % config_modules)
    if config_modules:
        # in the config *.ini files we have some line continuation slashes,
        # which will result in ugly module names, but as they are followed by
        # \n they could be separated as single entries by the following two
        # lines
        lines = config_modules.splitlines()
        coco = ",".join(lines)
        for module in coco.split(','):
            if module.strip() != '\\':
                module_list.add(module.strip())

    return module_list


@log_with(log)
@cache.memoize(10)
def get_token_module_list():
    """
    return the list of modules of the available token classes

    :return: list of token modules
    """
    # def load_resolver_modules
    module_list = get_token_list()
    log.debug("using the module list: %s" % module_list)

    modules = []
    for mod_name in module_list:
        if mod_name == '\\' or len(mod_name.strip()) == 0:
            continue

        # load all token class implementations
        #if mod_name in sys.modules:
        #    module = sys.modules[mod_name]
        #    log.debug('module %s loaded' % (mod_name))
        #    modules.append(module)
        #else:
        try:
            log.debug("import module: %s" % mod_name)
            exec("import %s" % mod_name)
            module = eval(mod_name)
            modules.append(module)
        except Exception as exx:  # pragma nocover
            module = None
            log.warning('unable to load resolver module : %r (%r)'
                        % (mod_name, exx))

    return modules


@cache.memoize(10)
def get_resolver_module_list():
    """
    return the list of modules of the available resolver classes
    like passw, sql, ldap

    :return: list of resolver modules
    """

    # def load_resolver_modules
    module_list = get_resolver_list()
    log.debug("using the module list: %s" % module_list)

    modules = []
    for mod_name in module_list:
        if mod_name == '\\' or len(mod_name.strip()) == 0:
            continue

        # TODO: This seems superflous, as a module will only be
        # loaded once into sys.modules. So it should not matter if it is
        # already loaded
        # load all token class implementations
        #if mod_name in sys.modules:
        #    module = sys.modules[mod_name]
        #    log.debug('module %s loaded' % (mod_name))
        #else:
        try:
            log.debug("import module: %s" % mod_name)
            exec("import %s" % mod_name)
            module = eval(mod_name)

        except Exception as exx:  # pragma nocover
            module = None
            log.warning('unable to load resolver module : %r (%r)'
                        % (mod_name, exx))

        if module is not None:
            modules.append(module)

    return modules


def set_privacyidea_config(key, value, typ="", desc=""):
    ret = 0
    # We need to check, if the value already exist
    q1 = Config.query.filter_by(Key=key).count()
    if typ == "password":
        # store value in encrypted way
        value = encryptPassword(value)
    if q1 > 0:
        # The value already exist, we need to update
        data = {'Value': value}
        if typ:
            data.update({'Type': typ})
        if desc:
            data.update({'Description': desc})
        Config.query.filter_by(Key=key).update(data)
        ret = "update"
    else:
        new_entry = Config(key, value, typ, desc)
        db.session.add(new_entry)
        ret = "insert"
        
    # Do the timestamp
    if Config.query.filter_by(Key="__timestamp__").count() > 0:
        Config.query.filter_by(Key="__timestamp__")\
            .update({'Value': datetime.now()})
    else:
        new_timestamp = Config("__timestamp__", datetime.now())
        db.session.add(new_timestamp)
    db.session.commit()
    return ret


def delete_privacyidea_config(key):
    """
    Delete a config entry
    """
    ret = 0
    # We need to check, if the value already exist
    q = Config.query.filter_by(Key=key).first()
    if q:
        db.session.delete(q)
        db.session.commit()
        ret = True
    return ret


@cache.memoize(10)
def get_inc_fail_count_on_false_pin():
    """
    Return if the Failcounter should be increased if only tokens
    with a false PIN were identified.
    :return: True of False
    :rtype: bool
    """
    r = get_from_config(key="IncFailCountOnFalsePin", default=True)
    if not isinstance(r, bool):
        # if it is a string we convert it
        r = r.lower() == "true"
    return r


@cache.memoize(10)
def get_prepend_pin():
    """
    Get the status of the "PrependPin" Config

    :return: True or False
    :rtype: bool
    """
    r = get_from_config(key="PrependPin", default="true")
    # The values are strings, so we need to compare:
    r = (r.lower() == "true" or r == "1")
    return r


def set_prepend_pin(prepend=True):
    """
    Set the status of the "PrependPin" Config
    :param prepend: If the PIN should be prepended or not
    :return: None
    """
    set_privacyidea_config("PrependPin", prepend)


