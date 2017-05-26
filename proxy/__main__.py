# -*- coding: utf-8 -*-

import argparse
import cache
import constants
import http_socket
import logging
import manage
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


def parse_args():
    ## Parse program argument.

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
        default=constants.DEFAULT_HTTP_PORT,
        type=int,
        help='Proxy bind port, default: %(default)s',
    )
    parser.add_argument(
        '--server-bind-port',
        default=constants.DEFAULT_HTTP_PORT,
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
                        '[%(levelname)-7s] '
                        '%(name)s::%(funcName)s:%(lineno)d '
                        '%(message)s'
                    ),
                ),
            )
            logger.addHandler(h)
    except IOError:
        logging.warning('Cannot initialize logging', exc_info=True)

    return logger


def close_all(poll):
    for p in poll._pollables:
        p.close_socket()


def main():
    application_context = {
        'statistics': {
            'throughput': [0, time.time()],
        },
    }
    args = parse_args()
    logger = setup_logging(
        stream=open(args.log_file, 'a'),
        level=args.log_level_str,
    )
    logger.info('Startup %s-%s', PACKAGE_NAME, PACKAGE_VERSION)
    logger.debug('Args: %s', args)

    try:
        poll = poller.Poller(logger)
        cache_handler = cache.Cache(logger)
        proxy_listener = http_socket.HttpListen(
            args.bind_address,
            args.proxy_bind_port,
            cache_handler,
            application_context,
            logger,
        )
        server_listener = manage.ManageListen(
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
        # logger.shutdown()


class Disconnect(RuntimeError):
    def __init__(self):
        super(Disconnect, self).__init__("Disconnect")


if __name__ == '__main__':
    main()
