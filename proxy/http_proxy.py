## @package proxy.http_proxy
# Module for ProxySocket, ProxyListen objects.
## @file http_proxy.py
# Implementation of @ref proxy.http_proxy
#

import proxy_client
import constants
import errno
import fcntl
import os
import pollable
import direct_socket
import select
import socket
import time
import util

## States for parsing HTTP request
(
    REQUEST_STATE,
    HEADERS_STATE,
    CONTENT_STATE,
    CLOSING_STATE,
) = range(4)


## ProxySocket for sending and receiving HTTP requests and responses.
#
# Created from ProxyListen class.
# Receives requests from the browser client server and parse his request. Then
# moves the requests to the ProxyClientSocket object.
#
class ProxySocket(pollable.Pollable):
    ## Constructor.
    # @param socket (socket)
    # @param state (int)
    # @param headers (dict)
    # @param cache_handler (Cache)
    # @param application_context (dict)
    # @param logger (logging.Logger)
    #
    def __init__(
        self,
        socket,
        state,
        headers,
        cache_handler,
        application_context,
        logger,
    ):
        self._socket = socket
        self._received = ''
        self._to_send = ''
        self._state = state
        self._peer = ''
        self._cache = cache_handler
        self._caching = False
        self._closing = False
        self._logger = logger
        self._request_context = {
            'method': '',
            'uri': '',
            'headers': headers,
            'content': '',
            'application_context': application_context,
        }

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
    def request_context(self):
        return self._request_context

    @request_context.setter
    def request_context(self, request_context):
        self.request_context = request_context

    ## Checks if received buffer length exceeded max request/response length.
    # If true, closing socket and sending error message.
    # @returns (bool) whether buffer exceeded max length.
    #
    def check_if_maxsize(self):
        if len(self._received) > constants.MAX_REQ_SIZE:
            self._to_send = util.return_status(500, 'Internal Error', '')
            self._state = CLOSING_STATE
            self._logger.error(
                'ProxySocket %s received-buffer reached max-size',
                self._socket.fileno(),
            )
            return True
        return False

    ## Receives the status line from the source server (client).
    # @param args (dict) program arguments.
    # @param poll object (poll).
    # @returns (boll) if ready to move to next state.
    #
    def request_state(self, args, poll):
        self.add_buf()
        line = self.check_if_line()
        if line:
            try:
                method, uri, signature = util.check_request(line)
            except RuntimeError:
                self._to_send = util.return_status(
                    500,
                    'Unsupported http request',
                    '',
                )
                self._logger.error(
                    'ProxySocket %s Unsupported http request, closing socket',
                    self._socket.fileno(),
                )
                self._state = CLOSING_STATE
                self._closing = True
                return True

            self._logger.info(
                'ProxySocket %s: %s request, %s, %s',
                self._socket.fileno(),
                method,
                uri,
                signature,
            )
            if method == 'CONNECT':
                address, port = uri.split(':', 1)
                upstream = direct_socket.DirectSocketUp(
                    self._socket,
                    address,
                    int(port),
                    poll,
                    self,
                    self._request_context['application_context'],
                    self._logger,
                )
                self._logger.debug(
                    'DirectSocketUp %s object created',
                    upstream._socket.fileno(),
                )
                poll._pollables.remove(self)
                self._state = CLOSING_STATE
                self._closing = True
                return True

            if '//' not in uri:
                self._to_send = util.return_status(400, 'Bad request', '')
                self._state = CLOSING_STATE
                self._logger.error(
                    'ProxySocket %s Bad request %s',
                    self._socket.fileno(),
                    uri,
                )
                return True
            self._request_context['method'] = method
            self._request_context['uri'] = uri
            address, uri = uri.split('//', 1)[1].split('/', 1)
            address = '%s:' % (address)
            address, port = address.split(':', 1)
            port = port.replace(':', '')
            if not port:
                port = 80
            else:
                port = int(port)
            self._caching = self._cache.check_if_cache(self._request_context)
            if self._caching:
                self._logger.info(
                    'ProxySocket %s: Found in cache %s',
                    self._socket.fileno(),
                    uri,
                )
                self._state = CLOSING_STATE
                response = self._cache.load_response(
                    self._request_context,
                    len(self._to_send),
                )
                if not response:
                    self._closing = True
                self._to_send += response
                return True

            self._peer = proxy_client.ProxyClientSocket(
                address,
                port,
                self,
                self._request_context['application_context'],
                self._logger,
            )
            poll.register(self._peer)
            self._logger.debug(
                'ProxyClientSocket object %s created' %
                self._peer._socket.fileno()
            )
            self._peer._to_send = '%s /%s %s\r\n' % (
                method,
                uri,
                constants.HTTP_SIGNATURE,
            )
            return True
        self.check_if_maxsize()
        return False

    ## Receives request headers from the source server.
    # @param args (dict) program arguments.
    # @param poll object (poll).
    # @returns (boll) if ready to move to next state.
    #
    def headers_state(self, args, poll):
        line = ' '
        if constants.CRLF not in self._received:
            self.add_buf()
        while line:
            line = self.check_if_line()

            if line:
                self._request_context['headers'] = util.update_headers(
                    line,
                    self._request_context['headers'],
                )

        if self._received == constants.CRLF or line == '':
            for key in self._request_context['headers']:
                self._peer._to_send += '%s: %s%s' % (
                    key,
                    self._request_context['headers'][key],
                    constants.CRLF,
                )
            self._peer._to_send += constants.CRLF
            return True
        self.check_if_maxsize()
        return False

    ## Receives requests content part from the source server.
    # @param args (dict) program arguments.
    # @param poll object (poll).
    # @returns (boll) if ready to move to next state.
    #
    def content_state(self, args, poll):
        if self.request_context['headers']['Content-Length'] is not '0':
            leng = int(self._request_context['headers']['Content-Length'])
            self._request_context['headers']['Content-Length'] = leng
            try:
                t = self._socket.recv(constants.BLOCK_SIZE)
                if not t:
                    raise RuntimeError('Disconnect')
                self._received += t
                if self._request_context['headers']['Content-Length'] == 0:
                    self._peer._to_send += self._request_context['content']
                    return True

            except socket.error as e:
                if e.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                    self._logger.error(
                        'ProxySocket %s socket error: %s',
                        self._socket.fileno(),
                        e,
                    )
                    raise

            return False
        return True

    ## Final state. Finished receiving. Ready to close socket.
    # @returns (boll) if ready to move to next state.
    #
    def closing_state(self):
        if not self._to_send:
            self.close_socket()
        return True

    ## dict of ProxySocket state machine.
    states = {
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
            "next": CLOSING_STATE
        },
        CLOSING_STATE: {
            "function": closing_state,
            "next": CLOSING_STATE,
        }
    }

    ## Function to be called when poller have a POLLIN event.
    # ProxySocket is in the process of receving request from the source server.
    # @param poll object (poll).
    # @param args (dict) program arguments.
    # @returns (ProxySocket) object to be removed from poll.
    #
    def on_read(self, poll, args):
        while (self._state <= CONTENT_STATE and
                ProxySocket.states[self._state]['function'](self, args, poll)):
            self._state = ProxySocket.states[self._state]['next']
        return None

    ## Function to be called when poller have a POLLOUT event.
    # ProxySocket is in the process of sending response to the source server.
    # This function sends everything from the to_send buffer.
    # @returns (ProxySocket) object to be removed from poll.
    #
    def on_write(self):
        self._to_send = self.send_all()
        if (
            self._caching and
            not self._closing and
            len(self._to_send) < constants.TO_SEND_MAXSIZE
        ):
            response = self._cache.load_response(
                self._request_context,
                len(self._to_send),
            )
            if not response:
                self._closing = True
            self._to_send += response

        if not self._to_send and self._closing:
            self.close_socket()
            if self._peer:
                self._peer._state = proxy_client.CLOSING_STATE
            return self
        return None

    ## Function to be called when poller have a POLLERR event.
    # Socket has encountered an error, closing socket.
    # @returns (ProxySocket) object to be removed from poll.
    #
    def on_error(self):
        self.close_socket()
        if self._peer:
            self._peer._state = proxy_client.CLOSING_STATE
        return self

    ## Function to be called when poller have a POLLHUP event.
    # Socket is ready to be close, closing socket.
    # @returns (ProxySocket) object to be removed from poll.
    #
    def on_hup(self):
        self.close_socket()
        if self._peer:
            self._peer._state = proxy_client.CLOSING_STATE
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
            self._state <= CONTENT_STATE
        ):
            events |= select.POLLIN

        if (
            self._to_send or self._closing
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
                self._state = CLOSING_STATE
                self._closing = True
            self._received += t

        except socket.error as e:
            if e.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                self._logger.error(
                    'ProxySocket %s socket error: %s',
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
                self._request_context[
                    'application_context'
                ]['statistics']['throughput'][0] += bytes_sent
                buf = buf[bytes_sent:]

        except socket.error as e:
            if e.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                self._logger.error(
                    'ProxySocket %s socket error: %s',
                    self._socket.fileno(),
                    e,
                )
                raise

        return buf

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

    ## Closing socket.
    #
    def close_socket(self):
        self._logger.debug(
            'ProxySocket socket %s is closing' %
            self._socket.fileno()
        )
        self._socket.close()


## ProxyListen object to accept new connections.
#
# Created by the __main__ function.
# Creates ProxySocket object.
#
class ProxyListen(pollable.Pollable):
    ## Constructor.
    # @param bind_address (str)
    # @param bind_port (int)
    # @param cache_handler (Cache)
    # @param application_context (dict)
    # @param logger (logging.Logger)
    #
    def __init__(
        self,
        bind_address,
        bind_port,
        cache_handler,
        application_context,
        logger,
    ):
        self._logger = logger
        self._application_context = application_context
        self._cache = cache_handler
        self._socket = socket.socket(
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
        )
        fcntl.fcntl(
            self._socket.fileno(),
            fcntl.F_SETFL, fcntl.fcntl(self._socket.fileno(), fcntl.F_GETFL) |
            os.O_NONBLOCK,
        )
        connected = False
        while not connected:
            try:
                self._socket.bind((bind_address, bind_port))
                self._socket.listen(10)
                print 'Port %s connected' % bind_port
                connected = True
            except socket.error as e:
                if e.args[0] != 48:
                    raise
                print 'Port %s already in use, trying again in 5 sec' % (
                    bind_port,
                )
                time.sleep(5)

    ## Function to be called when poller have a POLLIN event.
    # ProxyListen is accepting new connection and creates ProxySocket object
    # @param poll object (poll).
    # @param args (dict) program arguments.
    # @returns (ProxyListen) object to be removed from poll.
    #
    def on_read(self, poll, args):
        s1, add = self._socket.accept()
        fcntl.fcntl(
            s1.fileno(),
            fcntl.F_SETFL,
            fcntl.fcntl(s1.fileno(), fcntl.F_GETFL) | os.O_NONBLOCK,
        )
        http_obj = ProxySocket(
            s1,
            REQUEST_STATE,
            {
                'Content-Length': '0',
            },
            self._cache,
            self._application_context,
            self._logger,
        )
        self._logger.info(
            'proxy request (ProxySocket object created - %s)' % (
                http_obj._socket.fileno()
            )
        )
        poll.register(http_obj)
        return None

    ## Function to be called when poller have a POLLOUT event.
    # @returns (ProxyListen) object to be removed from poll.
    #
    def on_write(self):
        return None

    ## Function to be called when poller have a POLLERR event.
    # @returns (ProxyListen) object to be removed from poll.
    #
    def on_error(self):
        return self

    ## Returns poll events.
    # @returns (int) poll events.
    #
    def get_events(self):
        return select.POLLIN | select.POLLERR

    ## Returns sockets file discriptor.
    # @returns (str) sockets file discriptor.
    #
    def get_fd(self):
        return self._socket.fileno()

    ## Closing socket.
    #
    def close_socket(self):
        self._logger.debug(
            'ProxyListen socket %s is closing' %
            self._socket.fileno()
        )
        self._socket.close()
