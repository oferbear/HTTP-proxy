## @package proxy.proxy_client
# Module for ProxyClientSocket object.
## @file proxy_client.py
# Implementation of @ref proxy.proxy_client
#

import constants
import errno
import fcntl
import os
import pollable
import select
import socket
import util

## States for parsing HTTP response
(
    REQUEST_STATE,
    HEADERS_STATE,
    CONTENT_STATE,
    CLOSING_STATE,
) = range(4)


## ProxyClientSocket for sending and receiving HTTP requests and responses.
#
# Created from ProxySocket class.
# Sends requests to the destination server and parse his response.
#
class ProxyClientSocket(pollable.Pollable):
    ## Constructor.
    # @param address - desitnation address (str)
    # @param port - bind port (int)
    # @param peer - ProxySocket class (ProxySocket)
    # @param application_context (dict)
    # @param logger (logging.Logger)
    #
    def __init__(self, address, port, peer, application_context, logger):
        self._state = REQUEST_STATE
        self._peer = peer
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
                self._state = CLOSING_STATE

        self._to_send = ''
        self._received = ''
        self._status_line = ''
        self._test = ''
        self._headers = {}
        self._application_context = application_context

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

    ## Function to be called when poller have a POLLIN event.
    # ProxyClientSocket is in the process of receving response from the
    # destination server.
    # @param poll object (poll).
    # @param args (dict) program arguments.
    # @returns (ProxyClientSocket) object to be removed from poll.
    #
    def on_read(self, poll, args):
        while (self._state <= CLOSING_STATE and
                ProxyClientSocket.client_states[self._state]['function'](
                    self,
                    args,
                    poll,
                )):
            if self._state == CLOSING_STATE:
                return self
            self._state = ProxyClientSocket.client_states[self._state]['next']

        return None

    ## Receives the status line from the destination server.
    # @param args (dict) program arguments.
    # @param poll object (poll).
    # @returns (boll) if ready to move to next state.
    #
    def request_state(self, args, poll):
        try:
            self.add_buf()
            line = self.check_if_line()
        except RuntimeError:
            self._state = CLOSING_STATE
            return True

        if line:
            try:
                signature, status_num, status = util.check_response(line)
            except RuntimeError:
                self._peer._to_send = util.return_status(
                    500,
                    'Unsupported http request',
                    '',
                )
                self._state = CLOSING_STATE
                return True
            to_send = (
                '%s %s %s\r\n' % (
                    signature,
                    status_num,
                    status,
                )
            ).encode('utf-8')
            self._peer._to_send = to_send
            self._test = to_send
            self._status_line = to_send
            return True
        self.check_if_maxsize()
        return False

    ## Receives response headers from the destination server.
    # @param args (dict) program arguments.
    # @param poll object (poll).
    # @returns (boll) if ready to move to next state.
    #
    def headers_state(self, args, poll):
        line = ' '
        if constants.CRLF not in self._received:
            self.add_buf()
        while line and self._received[:2] != constants.CRLF:
            line = self.check_if_line()
            if line:
                self._headers = util.update_headers(
                    line,
                    self._headers,
                )
        check_header = self._peer._cache.check_headers(
            self._headers
        )
        if check_header is not False:
            self._peer._cache.create_files(
                self._peer._request_context,
                check_header,
            )
            self._peer._cache.add_cache(
                self._peer._request_context,
                self._status_line,
            )
        if self._received[:2] == '\r\n':  # or line == '':
            self._received = self._received[2:]
            for key in self._headers:
                to_send = (
                    '%s: %s\r\n' % (
                        key,
                        self._headers[key],
                    )
                ).encode('utf-8')
                self._peer._to_send += to_send
                self._test += to_send
                self._peer._cache.add_cache(
                    self._peer._request_context,
                    to_send,
                )
            self._peer._to_send += constants.CRLF
            self._peer._cache.add_cache(
                self._peer._request_context,
                constants.CRLF,
            )
            return True
        self.check_if_maxsize()
        return False

    ## Receives responses content part from the destination server.
    # @param args (dict) program arguments.
    # @param poll object (poll).
    # @returns (boll) if ready to move to next state.
    #
    def content_state(self, args, poll):
        finished = False
        self._headers['Content-Length'] = int(
            self._headers.get('Content-Length', 0)
        )
        is_content = self._headers['Content-Length'] == 0
        # if len(self._peer._to_send) > constants.TO_SEND_MAXSIZE:
        #    return False
        t = ''
        try:
            t = self._socket.recv(constants.BLOCK_SIZE)
        except socket.error as e:
            if e.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                self._logger.error(
                    'ProxyClientSocket %s socket error: %s',
                    self._socket.fileno(),
                    e,
                )
                self._state = CLOSING_STATE
                finished = True

        if not t and is_content:
            finished = True

        self._received += t
        self._peer._to_send += self._received
        self._test += self._received
        self._peer._cache.add_cache(
            self._peer._request_context,
            self._received,
        )
        if self._headers['Content-Length'] != 0:
            self._headers['Content-Length'] -= len(self._received)
        self._received = ''

        if self._headers['Content-Length'] == 0 and not is_content:
            finished = True

        if finished:
            if (
                self._peer._request_context['uri'] in
                self._peer._cache._opened_files
            ):
                self._peer._cache._opened_files[
                    self._peer._request_context['uri']
                ].close()
                del self._peer._cache._opened_files[
                    self._peer._request_context['uri']
                ]

            return True

        return False

    ## Final state. Finished receiving. Ready to close socket.
    # @param args (dict) program arguments.
    # @param poll object (poll).
    # @returns (boll) if ready to move to next state.
    #
    def closing_state(self, args, poll):
        self._peer._closing = True
        self.close_socket()
        return True

    ## dict of client state machine.
    client_states = {
        REQUEST_STATE: {
            "function": request_state,
            "next": HEADERS_STATE
        },
        HEADERS_STATE: {
            "function": headers_state,
            "next": CONTENT_STATE
        },
        CONTENT_STATE: {
            "function": content_state,
            "next": CLOSING_STATE,
        },
        CLOSING_STATE: {
            "function": closing_state,
            "next": CLOSING_STATE,
        }
    }

    ## Function to be called when poller have a POLLOUT event.
    # ProxyClientSocket is in the process of sending request to the destination
    # server.
    # This function sends everything from the to_send buffer.
    # @returns (ProxyClientSocket) object to be removed from poll.
    #
    def on_write(self):
        self._to_send = self.send_all()
        return None

    ## Function to be called when poller have a POLLERR event.
    # Socket has encountered an error, closing socket.
    # @returns (ProxyClientSocket) object to be removed from poll.
    #
    def on_error(self):
        self.close_socket()
        if self._peer:
            self._peer._closing = True
        return self

    ## Function to be called when poller have a POLLHUP event.
    # Socket is ready to be close, closing socket.
    # @returns (ProxyClientSocket) object to be removed from poll.
    #
    def on_hup(self):
        self.close_socket()
        if self._peer:
            self._peer._closing = True
        return self

    ## Returns sockets file discriptor.
    # @returns (str) sockets file discriptor.
    #
    def get_fd(self):
        return self._socket.fileno()

    ## Returns poll events.
    # @returns (int) poll events.
    #
    def get_events(self):
        events = select.POLLERR
        if (
            self._state >= REQUEST_STATE and
            self._state <= CLOSING_STATE
        ):
            events |= select.POLLIN
            if self._peer:
                if len(self._peer._to_send) > constants.TO_SEND_MAXSIZE:
                    events = select.POLLERR

        if self._to_send:
            events |= select.POLLOUT
        return events

    ## Closing socket.
    #
    def close_socket(self):
        self._logger.debug(
            'ProxyClientSocket socket %s is closing' %
            self._socket.fileno()
        )
        self._socket.close()

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
                    'ProxyClientSocket %s socket error: %s',
                    self._socket.fileno(),
                    e,
                )
                raise

        return buf

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
            self._received += t

        except socket.error as e:
            if e.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                self._logger.error(
                    'ProxyClientSocket %s socket error: %s',
                    self._socket.fileno(),
                    e,
                )
                raise RuntimeError('Disconnect')

    ## Checks if theres a line in the received buffer, and returns it.
    # @returns (str) line that was found in received buffer.
    #
    def check_if_line(self):
        buf = self._received
        n = buf.find(constants.CRLF_BIN)
        if n == -1:
            return None
        line = buf[:n].decode('utf-8')
        self._received = buf[n + len(constants.CRLF_BIN):]
        return line

    ## Checks if received buffer length exceeded max request/response length.
    # If true, closing socket and sending error message.
    # @returns (bool) whether buffer exceeded max length.
    #
    def check_if_maxsize(self):
        if len(self._received) > constants.MAX_REQ_SIZE:
            self._peer._to_send = util.return_status(500, 'Internal Error', '')
            self._state = CLOSING_STATE
            self._logger.error(
                'ProxyClientSocket %s received-buffer reached max-size',
                self._socket.fileno(),
            )
            return True
        return False
