# -*- coding: utf-8 -*-
## @package proxy.__main__
# HTTP Proxy with management capebilities.
## @file __main__.py
# Implementation of @ref proxy.__main__
#
import argparse
import cache
import constants
import http_proxy
import logging
import http_server
import os
import poller
import time
import traceback

## Package name.
PACKAGE_NAME = 'HTTP_Proxy'
## Package version.
PACKAGE_VERSION = '0.0.0'
## Log prefix.
LOG_PREFIX = 'my'


## Parse program argument.
# @returns (dict) program arguments.
#
def parse_args():
    ## Log level.
    LOG_STR_LEVELS = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL,
    }

    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--bind-address',
        default='0.0.0.0',
        help='Bind address, default: %(default)s',
    )
    parser.add_argument(
        '--proxy-bind-port',
        default=constants.DEFAULT_PROXY_PORT,
        type=int,
        help='Proxy bind port, default: %(default)s',
    )
    parser.add_argument(
        '--server-bind-port',
        default=constants.DEFAULT_SERVER_PORT,
        type=int,
        help='Server bind port, default: %(default)s',
    )
    parser.add_argument(
        '--base',
        default='.',
        help='Base directory to search files in, default: %(default)s',
    )
    parser.add_argument(
        '--log-level',
        dest='log_level_str',
        default='INFO',
        choices=LOG_STR_LEVELS.keys(),
        help='Log level',
    )
    parser.add_argument(
        '--log-file',
        dest='log_file',
        metavar='FILE',
        default=os.devnull,
        help='Logfile to write to, default: %(default)s',
    )
    args = parser.parse_args()
    args.base = os.path.normpath(os.path.realpath(args.base))
    return args


## Setup logging file.
# @returns logging object
#
def setup_logging(stream=None, level=logging.INFO):
    logger = logging.getLogger(LOG_PREFIX)
    logger.propagate = False
    logger.setLevel(level)

    try:
        if stream is not None:
            h = logging.StreamHandler(stream)
            h.setLevel(logging.DEBUG)
            h.setFormatter(
                logging.Formatter(
                    fmt=(
                        '%(asctime)-15s '
                        '[%(levelname)-s] '
                        '%(name)s::%(funcName)s:%(lineno)d '
                        '%(message)s'
                    ),
                ),
            )
            logger.addHandler(h)
    except IOError:
        logging.warning('Cannot initialize logging', exc_info=True)

    return logger


## Closes all open sockets
def close_all(poll):
    for p in poll._pollables:
        p.close_socket()


## Main implementation.
def main():
    application_context = {
        'statistics': {
            'throughput': [0, time.time()],
        },
        'connections': 0,
    }
    args = parse_args()
    logger = setup_logging(
        stream=open(args.log_file, 'a'),
        level=args.log_level_str,
    )
    logger.info('Startup %s-%s', PACKAGE_NAME, PACKAGE_VERSION)
    logger.debug('Args: %s', args)

    try:
        # Create poll.
        poll = poller.Poller(logger)
        # Create cache handler.
        cache_handler = cache.Cache(logger)
        # Create proxy listener.
        proxy_listener = http_proxy.ProxyListen(
            args.bind_address,
            args.proxy_bind_port,
            cache_handler,
            application_context,
            logger,
        )
        # Create server listener.
        server_listener = http_server.ServerListen(
            args.bind_address,
            args.server_bind_port,
            cache_handler,
            application_context,
            logger,
        )
        poll.register(proxy_listener)
        poll.register(server_listener)
        poll.run(args)

    except Exception:
        traceback.print_exc()

    finally:
        print 'exit'
        close_all(poll)
        logger.info('All sockets closed, shutting down log')


## Error used for handling disconnecting sockets.
class Disconnect(RuntimeError):
    def __init__(self):
        super(Disconnect, self).__init__("Disconnect")


if __name__ == '__main__':
    main()
