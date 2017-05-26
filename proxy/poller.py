import select
import traceback


class Poller():
    def __init__(self, logger):
        self._pollables = []
        self._logger = logger

    def register(self, pollable):
        self._pollables.append(pollable)

    def run(self, args):
        while True:
            to_remove = []
            try:
                poll = select.poll()
                objects = {}
                for entry in self._pollables:
                    objects[entry.get_fd()] = entry
                    poll.register(entry.get_fd(), entry.get_events())
                # print 'OBJECTS :%s' % objects
                self._logger.debug('Pollables registered %s', objects)

                for fd, event in poll.poll():
                    # print fd, event
                    self._logger.debug('Poll wake: %s, event: %s', fd, event)
                    if event & select.POLLERR:
                        to_remove.append(objects[fd].on_error())

                    elif event & select.POLLIN:
                        # print "POLLIN %s " % objects[fd]
                        to_remove.append(objects[fd].on_read(self, args))

                    elif event & select.POLLHUP:
                        to_remove.append(objects[fd].on_hup())

                    elif event & select.POLLOUT:
                        # print "POLLOUT %s" % objects[fd]
                        to_remove.append(objects[fd].on_write())

            except Exception as e:
                traceback.print_exc()
                self._logger.error(
                    'Poller caghut error %s',
                    e,
                )
                to_remove.append(objects[fd])

            finally:
                # print 'TO REMOVE %s' % to_remove
                if to_remove:
                    # print 'REMOVING %s' % to_remove
                    self._logger.debug('Removing from poll %s', to_remove)
                    # print self._pollables
                    for entry in to_remove:
                        if entry in self._pollables:
                            self._pollables.remove(entry)
