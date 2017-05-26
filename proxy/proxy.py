import constants
import errno
import fcntl
import os
import pollable
import select
import socket


class UpStream(pollable.Pollable):
    def __init__(
        self,
        socket,
        address,
        port,
        poll,
        http_socket,
        application_context,
        logger,
    ):
        self._http_socket = http_socket
        self._socket = socket
        self._to_send = 'HTTP/1.1 200 Connection established\r\n\r\n'
        self._closing = False
        self._application_context = application_context
        self._logger = logger
        self._peer = DownStream(
            address,
            port,
            self,
            application_context,
            logger,
        )
        poll.register(self)
        poll.register(self._peer)
        # print "PROXY UPSTREAM CREATED"

    @property
    def socket(self):
        return self._socket

    @socket.setter
    def socket(self, s):
        self._socket = s

    @property
    def received(self):
        return self._received

    @received.setter
    def received(self, r):
        self._received = r

    @property
    def to_send(self):
        return self._to_send

    @to_send.setter
    def to_send(self, r):
        self._to_send = r

    def on_error(self):
        raise RuntimeError
        return None

    def on_read(self, poll, args):
        try:
            if len(self._peer._to_send) <= constants.TO_SEND_MAXSIZE:
                self.add_buf()

        except RuntimeError:
            self.close_socket()
            if self._peer:
                self._peer._closing = True
            return self

        return None

    def on_write(self):
        try:
            # print 'UP SENDING %s' % self._to_send
            self._to_send = self.send_all()

            if not self._to_send and self._closing:
                # print 'hey??'
                self.close_socket()
                if self._peer:
                    self._peer._closing = True
                return self
        except RuntimeError:
            self.close_socket()
            if self._peer:
                self._peer._closing = True
            return self

        return None

    def get_fd(self):
        return self._socket.fileno()

    def get_events(self):
        events = select.POLLERR | select.POLLIN
        # if self._peer._to_send:
        #    events |= select.POLLIN
        if (
            self._to_send and
            len(self._peer._to_send) < constants.TO_SEND_MAXSIZE
        ):
            events |= select.POLLOUT
        # print 'PROXY EVENTS %s' % events
        return events

    def add_buf(
        self,
        max_length=constants.MAX_HEADER_LENGTH,
        block_size=constants.BLOCK_SIZE,
    ):
        try:
            t = self._socket.recv(block_size)
            if not t:
                raise RuntimeError('Disconnect')
            self._peer._to_send += t

        except socket.error as e:
            # print e.errno
            if e.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                self._logger.error(
                    'UpStream %s socket error: %s',
                    self._socket.fileno(),
                    e,
                )
                raise

    def send_all(self):
        try:
            buf = self._to_send
            while buf:
                bytes_sent = self._socket.send(buf)
                self._application_context[
                    'statistics'
                ]['throughput'][0] += bytes_sent
                buf = buf[bytes_sent:]

        except socket.error as e:
            if e.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                self._logger.error(
                    'UpStream %s socket error: %s',
                    self._socket.fileno(),
                    e,
                )
                raise

        return buf

    def close_socket(self):
        # print '%s PROXY UPSTREAM is closing' % str(self._socket.fileno())
        self._logger.debug(
            'UpStream socket %s is closing' %
            self._socket.fileno()
        )
        self._socket.close()


class DownStream(pollable.Pollable):
    def __init__(self, address, port, peer, application_context, logger):
        self._to_send = ''
        self._peer = peer
        self._bytes_sent = 0
        self._closing = False
        self._application_context = application_context
        self._logger = logger
        self._socket = socket.socket(
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
        )
        fcntl.fcntl(
            self._socket.fileno(),
            fcntl.F_SETFL, fcntl.fcntl(self._socket.fileno(), fcntl.F_GETFL) |
            os.O_NONBLOCK,
        )
        try:
            # print "PORT " + str(port)
            self._socket.connect((address, port))
            # print "CLIENT CONNECTED"
        except socket.error as e:
            # print "ERROR CONNECTING %s" % str(e)
            self._logger.error(
                'DownStream %s error connecting %s',
                self._socket.fileno(),
                e
            )
            if e.errno != errno.EINPROGRESS:
                # self._state = CLOSING_STATE
                self._peer._to_send = 'HTTP/1.1 403 Forbidden\r\n\r\n'

        self._peer._to_send = 'HTTP/1.1 200 Connection established\r\n\r\n'
        # self._received = ''
        # print "PROXY DOWNSTREAM CREATED"
        self._logger.debug('DownStream %s created', self._socket.fileno())

    @property
    def socket(self):
        return self._socket

    @socket.setter
    def socket(self, s):
        self._socket = s

    @property
    def received(self):
        return self._received

    @received.setter
    def received(self, r):
        self._received = r

    @property
    def to_send(self):
        return self._to_send

    @to_send.setter
    def to_send(self, r):
        self._to_send = r

    def on_error(self):
        raise RuntimeError
        return None

    def on_read(self, poll, args):
        try:
            if len(self._peer._to_send) <= constants.TO_SEND_MAXSIZE:
                # print 'PROXY DOWN ADDING BUF'
                self.add_buf()

        except RuntimeError:
            self.close_socket()
            if self._peer:
                self._peer._closing = True
            return self

        return None

    def on_write(self):
        try:

            # print 'DOWN SENDING %s' % self._to_send
            self._to_send = self.send_all()

            if not self._to_send and self._closing:
                # print 'hey??'
                self.close_socket()
                if self._peer:
                    self._peer._closing = True
                return self

        except RuntimeError:
            self.close_socket()
            if self._peer:
                self._peer._closing = True
            return self

        return None

    def get_fd(self):
        return self._socket.fileno()

    def get_events(self):
        events = select.POLLERR | select.POLLIN
        # if self._peer._to_send:
        #    events |= select.POLLIN
        if (
            self._to_send and
            len(self._peer._to_send) < constants.TO_SEND_MAXSIZE
        ):
            events |= select.POLLOUT
        # print 'PROXY EVENTS %s' % events
        return events

    def add_buf(
        self,
        max_length=constants.MAX_HEADER_LENGTH,
        block_size=constants.BLOCK_SIZE,
    ):
        try:
            t = self._socket.recv(block_size)
            # print 'ADDED PROXY DOWN %s' % t
            if not t:
                raise RuntimeError('Disconnect')
            self._peer._to_send += t

        except socket.error as e:
            # print e.errno
            if e.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                self._logger.error(
                    'DownStream %s socket error: %s',
                    self._socket.fileno(),
                    e,
                )
                raise RuntimeError('Disconnect')

    def send_all(self):
        try:
            buf = self._to_send
            while buf:
                bytes_sent = self._socket.send(buf)
                self._application_context[
                    'statistics'
                ]['throughput'][0] += bytes_sent
                buf = buf[bytes_sent:]

        except socket.error as e:
            if e.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                self._logger.error(
                    'DownStream %s socket error: %s',
                    self._socket.fileno(),
                    e,
                )
                raise

        return buf

    def close_socket(self):
        # print '%s PROXY DOWNSTREAM is closing' % str(self._socket.fileno())
        self._logger.debug(
            'DownStream socket %s is closing' %
            self._socket.fileno()
        )
        self._socket.close()
