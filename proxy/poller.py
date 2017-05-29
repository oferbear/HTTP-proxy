## @package proxy.poller
# Module for Poller object.
## @file poller.py
# Implementation of @ref proxy.poller
#

import select
import traceback


## Poller object for creating poll and registering pollables to it.
#
# Created from __main__.
#
class Poller():
    ## Constructor.
    # @param logger (logging.Logger)
    #
    def __init__(self, logger):
        self._pollables = []
        self._logger = logger

    ## Register pollable to poll.
    # @param pollable (Pollable)
    #
    def register(self, pollable):
        self._pollables.append(pollable)

    ## Run the poll.
    # @param args (dict)
    #
    def run(self, args):
        while True:
            to_remove = []
            try:
                poll = select.poll()
                objects = {}
                for entry in self._pollables:
                    objects[entry.get_fd()] = entry
                    poll.register(entry.get_fd(), entry.get_events())
                self._logger.debug('Pollables registered %s', objects)

                for fd, event in poll.poll():
                    self._logger.debug('Poll wake: %s, event: %s', fd, event)
                    if event & select.POLLERR:
                        to_remove.append(objects[fd].on_error())

                    elif event & select.POLLIN:
                        to_remove.append(objects[fd].on_read(self, args))

                    elif event & select.POLLHUP:
                        to_remove.append(objects[fd].on_hup())

                    elif event & select.POLLOUT:
                        to_remove.append(objects[fd].on_write())

            except Exception as e:
                traceback.print_exc()
                self._logger.error(
                    'Poller caghut error %s',
                    e,
                )
                to_remove.append(objects[fd])

            finally:
                if to_remove:
                    self._logger.debug('Removing from poll %s', to_remove)
                    for entry in to_remove:
                        if entry in self._pollables:
                            self._pollables.remove(entry)
