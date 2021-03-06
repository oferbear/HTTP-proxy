## @package proxy.pollable
# Module for Pollable object.
## @file pollable.py
# Implementation of @ref proxy.pollable
#


## Pollable interface.
class Pollable(object):
    def on_read(self, poller, args):
        pass

    def on_write(self):
        pass

    def on_error(self):
        pass

    def get_fd(self):
        pass

    def get_events(self):
        pass

    def register(self):
        pass
