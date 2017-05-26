import constants
import errno
import fcntl
import os
import pollable
import select
import socket
import util

(
    REQUEST_STATE,
    HEADERS_STATE,
    CONTENT_STATE,
    CLOSING_STATE,
) = range(4)


class Client(pollable.Pollable):
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
            # print "PORT " + str(port)
            self._socket.connect((address, port))
            # print "CLIENT CONNECTED"
        except socket.error as e:
            # print "ERROR CONNECTING " + str(e)
            if e.errno != errno.EINPROGRESS:
                self._state = CLOSING_STATE
                self._peer._closing

        self._to_send = ''
        self._received = ''
        self._status_line = ''
        self._headers = {
            # 'Content-Length': '0'
        }
        self._application_context = application_context
        # print "CLIENT CREATED"

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

    def on_read(self, poll, args):
        while (self._state <= CLOSING_STATE and
                Client.client_states[self._state]['function'](
                    self,
                    args,
                    poll,
                )):
            if self._state == CLOSING_STATE:
                # print "ARE YOU RETURNING YOURSELF OR NOT?"
                return self
            self._state = Client.client_states[self._state]['next']

        return None

    def request_state(self, args, poll):
        try:
            self.add_buf()
            line = self.check_if_line()
        except RuntimeError:
            self._state = CLOSING_STATE
            self._peer._closing = True
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
                self._peer._closing = True
                return True
            to_send = (
                '%s %s %s\r\n' % (
                    signature,
                    status_num,
                    status,
                )
            ).encode('utf-8')
            self._peer._to_send = to_send
            # self._peer._cache.add_cache(self._peer._request_context, to_send)
            self._status_line = to_send
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
                self._headers = util.update_headers(
                    line,
                    self._headers,
                )
        # print 'HEADERS %s' % self._headers
        check_header = self._peer._cache.check_headers(
            self._headers
        )
        # print 'CHECK HEADER %s' % check_header
        if check_header is not False:
            # print 'REQUEST CONTEXT %s' % self._peer._request_context
            self._peer._cache.create_files(
                self._peer._request_context,
                check_header,
            )
            self._peer._cache.add_cache(
                self._peer._request_context,
                self._status_line,
            )
        if self._received == '\r\n' or line == '':
            for key in self._headers:
                to_send = (
                    '%s: %s\r\n' % (
                        key,
                        self._headers[key],
                    )
                ).encode('utf-8')
                self._peer._to_send += to_send
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

    def content_state(self, args, poll):
        # if self._headers['Content-Length'] is not '0':
        finished = False
        # print self._headers
        if 'Content-Length' in self._headers:
            leng = int(self._headers['Content-Length'])
            # print 'LENGTH (CLIENT HEADERS) %s' % leng
            self._headers['Content-Length'] = leng
        # else:
        #    self._headers['Content-Length'] = None

        if len(self._peer._to_send) > constants.TO_SEND_MAXSIZE:
            # print 'PEER TO SEND: %s' % self._peer._to_send
            return False
        # if len(self._received) < leng:
        t = ''
        try:
            # print 'yo are you here???'
            t = self._socket.recv(constants.BLOCK_SIZE)
            # print 'finished receive'
        except socket.error as e:
            # print e.errno
            if e.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                self._logger.error(
                    'Client %s socket error: %s',
                    self._socket.fileno(),
                    e,
                )
                self._state = CLOSING_STATE

        # print 'RECEIVED: %s' % t
        if not t:
            finished = True
            # self._headers['Content-Length'] == 0
            # raise RuntimeError('Disconnect')
        self._received += t
        # print 'BLOCK RECEIVED %s' % t
        self._peer._to_send += self._received
        # print 'REQUEST CONTEXT %s' % self._peer._request_context
        self._peer._cache.add_cache(
            self._peer._request_context,
            self._received,
        )
        if 'Content-Length' in self._headers:
            self._headers['Content-Length'] = leng - len(self._received)
        self._received = ''

        # if self._headers['Content-Length'] == 0:
        if 'Content-Length' in self._headers:
            if self._headers['Content-Length'] == 0:
                finished = True
        if finished:
            if (
                self._peer._request_context['uri'] in
                self._peer._cache._opened_files
            ):
                self._peer._cache._opened_files[
                    self._peer._request_context['uri']
                ].close()
            return True

        return False

        # self._peer._cache.add_cache(self._received)
        # self._peer._cache._file.close()
        # return True

    def closing_state(self, args, poll):
        self._peer._closing = True
        self.close_socket()
        # print 'SOCKET CLOSED'
        return True

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

    def on_write(self):
        # print 'CLIENT SENDING %s' % self._to_send
        self._to_send = self.send_all()
        # if not self._to_send and self._state == CLOSING_STATE:
        #    self._state = constants.CLOSING
        #    self.close_socket()
        #    return self
        return None

    def on_error(self):
        self.close_socket()
        if self._peer:
            self._peer._closing = True
        return self

    def on_hup(self):
        self.close_socket()
        if self._peer:
            self._peer._closing = True
        return self

    def get_fd(self):
        return self._socket.fileno()

    def get_events(self):
        # print '%s CLIENT STATE %s' % (self._socket.fileno(), self._state)
        events = select.POLLERR
        if (
            self._state >= REQUEST_STATE and
            self._state <= CLOSING_STATE
        ):
            events |= select.POLLIN
        if self._to_send:  # or self._state == CLOSING_STATE:
            events |= select.POLLOUT
            # print 'CLIENT %s: SOMETHING TO SEND' % self._socket.fileno()
        return events

    def close_socket(self):
        # print str(self._socket.fileno()) + " CLIENT is closing"
        self._logger.debug(
            'Client socket %s is closing' %
            self._socket.fileno()
        )
        self._socket.close()

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
                    'Client %s socket error: %s',
                    self._socket.fileno(),
                    e,
                )
                raise

        return buf

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
            # print e.errno
            if e.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                self._logger.error(
                    'Client %s socket error: %s',
                    self._socket.fileno(),
                    e,
                )
                raise RuntimeError('Disconnect')

    def check_if_line(self):
        # checks if theres a full line in what the socket received, if there
        # is returns it, if not adds buf to the 'received'
        buf = self._received
        n = buf.find(constants.CRLF_BIN)
        if n == -1:
            # self.add_buf()
            return None
        line = buf[:n].decode('utf-8')
        self._received = buf[n + len(constants.CRLF_BIN):]
        return line

    def check_if_maxsize(self):
        if len(self._received) > constants.MAX_REQ_SIZE:
            self._to_send = util.return_status(500, 'Internal Error', '')
            self._state = CLOSING_STATE
            self._logger.error(
                'Client %s received-buffer reached max-size',
                self._socket.fileno(),
            )
            return True
        return False
