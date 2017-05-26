import client
import constants
import errno
import fcntl
import os
import pollable
import proxy
import select
import socket
import time
import util

(
    REQUEST_STATE,
    HEADERS_STATE,
    CONTENT_STATE,
    CLOSING_STATE,
) = range(4)


class HttpSocket(pollable.Pollable):
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
            'file_name': '',
            'file_obj': '',
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

    def check_if_maxsize(self):
        if len(self._received) > constants.MAX_REQ_SIZE:
            self._to_send = util.return_status(500, 'Internal Error', '')
            self._state = CLOSING_STATE
            self._logger.error(
                'HttpSocket %s received-buffer reached max-size',
                self._socket.fileno(),
            )
            return True
        return False

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
                    'HttpSocket %s Unsupported http request, closing socket',
                    self._socket.fileno(),
                )
                self._state = CLOSING_STATE
                self._closing = True
                return True

            self._logger.info(
                'HttpSocket %s: %s request, %s, %s',
                self._socket.fileno(),
                method,
                uri,
                signature,
            )
            if method == 'CONNECT':
                address, port = uri.split(':', 1)
                upstream = proxy.UpStream(
                    self._socket,
                    address,
                    int(port),
                    poll,
                    self,
                    self._request_context['application_context'],
                    self._logger,
                )
                self._logger.debug(
                    'UpStream %s object created',
                    upstream._socket.fileno(),
                )
                # upstream._peer._to_send = self._received
                # downstream = proxy.DownStream(address, port, self._socket)
                # poll.register(upstream)
                # poll.register(downstream)
                poll._pollables.remove(self)
                # self.close_socket()
                self._state = CLOSING_STATE
                self._closing = True
                return True

            if '//' not in uri:
                raise RuntimeError('bad request')
            file_name = os.path.normpath(
                '%s%s' % (
                    args.base,
                    os.path.normpath(uri),
                )
            )
            self._request_context['method'] = method
            self._request_context['uri'] = uri
            self._request_context['file_name'] = file_name
            # self._cache = cache.Cache()
            # print 'CACHED %s %s' % (self._caching, self._cache._cached)
            address, uri = uri.split('//', 1)[1].split('/', 1)
            address = '%s:' % (address)
            # print address
            address, port = address.split(':', 1)
            port = port.replace(':', '')
            if not port:
                port = 80
            else:
                port = int(port)
            self._caching = self._cache.check_if_cache(self._request_context)
            if self._caching:
                # print 'CACHING yooo'
                self._logger.info(
                    'HttpSocket %s: Found in cache %s',
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

            self._peer = client.Client(
                address,
                port,
                self,
                self._request_context['application_context'],
                self._logger,
            )
            poll.register(self._peer)
            self._logger.debug(
                'Client object %s created' % self._peer._socket.fileno()
            )
            self._peer._to_send = '%s /%s %s\r\n' % (
                method,
                uri,
                constants.HTTP_SIGNATURE,
            )
            return True
        self.check_if_maxsize()
        return False

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
            # print 'LINE: %s' % line
        # print 'SELF.RECEIVED: %s' % self._received
        if self._received == constants.CRLF or line == '':
            for key in self._request_context['headers']:
                self._peer._to_send += '%s: %s%s' % (
                    key,
                    self._request_context['headers'][key],
                    constants.CRLF,
                )
            self._peer._to_send += constants.CRLF
            # print 'PEERS TOSEND %s' % self._peer._to_send
            return True
        self.check_if_maxsize()
        return False

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
                # print e.errno
                if e.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                    self._logger.error(
                        'HttpSocket %s socket error: %s',
                        self._socket.fileno(),
                        e,
                    )
                    raise

            return False
        return True

    def closing_state(self):
        if not self._to_send:
            self.close_socket()
        return True

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

    def on_read(self, poll, args):
        while (self._state <= CONTENT_STATE and
                HttpSocket.states[self._state]['function'](self, args, poll)):
            self._state = HttpSocket.states[self._state]['next']
        return None

    def on_write(self):
        # print 'TOSEND: %s' % self._to_send
        # print 'HTTP SOCKET ON WRITE'
        self._to_send = self.send_all()
        # print 'SELF.CACHING %s' % self._caching
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

        # print 'TEST TEST %s %s' % (self._to_send, self._closing)
        if not self._to_send and self._closing:
            # print 'hey??'
            self.close_socket()
            # print 'PEERS STATE %s' % self._peer._state
            if self._peer:
                self._peer._state = client.CLOSING_STATE
            return self
        return None

    def on_error(self):
        # raise RuntimeError
        self.close_socket()
        if self._peer:
            self._peer._state = client.CLOSING_STATE
        return self

    def on_hup(self):
        self.close_socket()
        if self._peer:
            self._peer._state = client.CLOSING_STATE
        return self

    def get_fd(self):
        return self._socket.fileno()

    def get_events(self):
        # print '%s HTTPSOCKET STATE %s TO SEND %s' % (
        #    self._socket.fileno(),
        #    self._state,
        #    self._to_send,
        # )
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
        # print 'HTTPSOCKET EVENTS %s' % events
        return events

    def add_buf(
        self,
        max_length=constants.MAX_HEADER_LENGTH,
        block_size=constants.BLOCK_SIZE,
    ):
        try:
            t = self._socket.recv(block_size)
            if not t:
                # raise RuntimeError('Disconnect')
                self._state = CLOSING_STATE
                self._closing = True
            self._received += t

        except socket.error as e:
            # print e.errno
            if e.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                self._logger.error(
                    'HttpSocket %s socket error: %s',
                    self._socket.fileno(),
                    e,
                )
                raise

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
                    'HttpSocket %s socket error: %s',
                    self._socket.fileno(),
                    e,
                )
                raise

        return buf

    def check_if_line(self):
        # checks if theres a full line in what the socket received, if there
        # is returns it, if not adds buf to the 'received'
        buf = self._received
        # print 'BUF: %s' % buf
        n = buf.find(constants.CRLF_BIN)
        if n == -1:
            # self.add_buf()
            return None
        line = buf[:n].decode('utf-8')
        self._received = buf[n + len(constants.CRLF_BIN):]
        return line

    def close_socket(self):
        # print '%s HTTPSOCKET is closing' % str(self._socket.fileno())
        self._logger.debug(
            'HttpSocket socket %s is closing' %
            self._socket.fileno()
        )
        self._socket.close()


class HttpListen(pollable.Pollable):
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

    def on_read(self, poll, args):
        s1, add = self._socket.accept()
        fcntl.fcntl(
            s1.fileno(),
            fcntl.F_SETFL,
            fcntl.fcntl(s1.fileno(), fcntl.F_GETFL) | os.O_NONBLOCK,
        )
        http_obj = HttpSocket(
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
            'proxy request (HttpSocket object created - %s)' % (
                http_obj._socket.fileno()
            )
        )
        poll.register(http_obj)
        return None

    def on_write(self):
        return None

    def on_error(self):
        raise RuntimeError
        return None

    def get_events(self):
        return select.POLLIN | select.POLLERR

    def get_fd(self):
        return self._socket.fileno()

    def close_socket(self):
        # print '%s HTTPLISTEN is closing' % str(self._socket.fileno())
        self._logger.debug(
            'HttpListen socket %s is closing' %
            self._socket.fileno()
        )
        self._socket.close()
