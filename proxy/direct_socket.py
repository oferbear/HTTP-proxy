## @package proxy.direct_socket
# Module for DirectSocketUp, DirectSocketDown objects.
#

import constants
import errno
import fcntl
import os
import pollable
import select
import socket


## DirectSocketUp for sending and receiving HTTPS requests and responses.
#
# Created from ProxySocket class, when CONNECT requsts arrive.
# Receives requests from the browser client server. Then moves the requests to
# the DirectSocketDown object.
#
class DirectSocketUp(pollable.Pollable):
    ## Constructor.
    # @param socket (socket)
    # @param address to connect to (str)
    # @param port (int)
    # @param poll object (poll).
    # @param ProxySocket object (ProxySocket)
    # @param application_context (dict)
    # @param logger (logging.Logger)
    #
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
        self._peer = DirectSocketDown(
            address,
            port,
            self,
            application_context,
            logger,
        )
        poll.register(self)
        poll.register(self._peer)

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

    ## Function to be called when poller have a POLLIN event.
    # DirectSocketUp is in the process of receving request from the source
    # server.
    # @param poll object (poll).
    # @param args (dict) program arguments.
    # @returns (DirectSocketUp) object to be removed from poll.
    #
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

    ## Function to be called when poller have a POLLOUT event.
    # ProxySocket is in the process of sending response to the source server.
    # This function sends everything from the to_send buffer.
    # @returns (DirectSocketUp) object to be removed from poll.
    #
    def on_write(self):
        try:
            self._to_send = self.send_all()

            if not self._to_send and self._closing:
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

    ## Returns sockets file discriptor.
    # @returns (str) sockets file discriptor.
    #
    def get_fd(self):
        return self._socket.fileno()

    ## Returns poll events.
    # @returns (int) poll events.
    #
    def get_events(self):
        events = select.POLLERR | select.POLLIN
        if (
            self._to_send and
            len(self._peer._to_send) < constants.TO_SEND_MAXSIZE
        ):
            events |= select.POLLOUT
        return events

    # Receives string from socket and adds it to received buffer.
    # @param max_length (int) max header length.
    # @param blocksize (int) length of bytes to receive.
    #
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
            if e.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                self._logger.error(
                    'DirectSocketUp %s socket error: %s',
                    self._socket.fileno(),
                    e,
                )
                raise

    ## Sends everything possible from to_send buffer.
    # @returns (str) string from buffer that couldn't be sent.
    #
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
                    'DirectSocketUp %s socket error: %s',
                    self._socket.fileno(),
                    e,
                )
                raise

        return buf

    ## Closing socket.
    #
    def close_socket(self):
        self._logger.debug(
            'DirectSocketUp socket %s is closing' %
            self._socket.fileno()
        )
        self._socket.close()


## DirectSocketDown for sending and receiving HTTP requests and responses.
#
# Created from DirectSocketUp class.
# Sends requests to the destination server and receives his response.
#
class DirectSocketDown(pollable.Pollable):
    ## Constructor.
    # @param address to connect to (str)
    # @param port (int)
    # @param ProxySocket object (ProxySocket)
    # @param application_context (dict)
    # @param logger (logging.Logger)
    #
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
            self._socket.connect((address, port))
        except socket.error as e:
            if e.errno != errno.EINPROGRESS:
                self._logger.error(
                    'DirectSocketDown %s error connecting %s',
                    self._socket.fileno(),
                    e,
                )
                self._peer._to_send = 'HTTP/1.1 403 Forbidden\r\n\r\n'

        self._peer._to_send = 'HTTP/1.1 200 Connection established\r\n\r\n'
        self._logger.debug(
            'DirectSocketDown %s created',
            self._socket.fileno(),
        )

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

    ## Function to be called when poller have a POLLIN event.
    # DirectSocketDown is in the process of receving response from the
    # destination server.
    # @param poll object (poll).
    # @param args (dict) program arguments.
    # @returns (DirectSocketDown) object to be removed from poll.
    #
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

    ## Function to be called when poller have a POLLOUT event.
    # DirectSocketDown is in the process of sending request to the destination
    # server.
    # This function sends everything from the to_send buffer.
    # @returns (DirectSocketDown) object to be removed from poll.
    #
    def on_write(self):
        try:
            self._to_send = self.send_all()

            if not self._to_send and self._closing:
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

    ## Returns sockets file discriptor.
    # @returns (str) sockets file discriptor.
    #
    def get_fd(self):
        return self._socket.fileno()

    ## Returns poll events.
    # @returns (int) poll events.
    #
    def get_events(self):
        events = select.POLLERR | select.POLLIN
        if (
            self._to_send and
            len(self._peer._to_send) < constants.TO_SEND_MAXSIZE
        ):
            events |= select.POLLOUT
        return events

    # Receives string from socket and adds it to received buffer.
    # @param max_length (int) max header length.
    # @param blocksize (int) length of bytes to receive.
    #
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
            if e.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                self._logger.error(
                    'DirectSocketDown %s socket error: %s',
                    self._socket.fileno(),
                    e,
                )
                raise RuntimeError('Disconnect')

    ## Sends everything possible from to_send buffer.
    # @returns (str) string from buffer that couldn't be sent.
    #
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
                    'DirectSocketDown %s socket error: %s',
                    self._socket.fileno(),
                    e,
                )
                raise

        return buf

    ## Closing socket.
    #
    def close_socket(self):
        self._logger.debug(
            'DirectSocketDown socket %s is closing' %
            self._socket.fileno()
        )
        self._socket.close()
