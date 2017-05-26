import constants
import errno
import fcntl
import os
import pollable
import select
import socket
import time
import traceback
import urlparse
import util

(
    REQUEST_STATE,
    HEADERS_STATE,
    CONTENT_STATE,
    RESPONSE_STATUS_STATE,
    RESPONSE_HEADER_STATE,
    RESPONSE_CONTENT_STATE,
    CLOSING_STATE,
) = range(7)


class Manage(pollable.Pollable):
    def __init__(
        self,
        socket,
        headers,
        cache_handler,
        application_context,
        logger
    ):
        self._socket = socket
        self._state = 0
        self._received = ''
        self._to_send = ''
        self._manage = ''
        self._cache_handler = cache_handler
        self._logger = logger
        self._request_context = {
            'method': '',
            'uri': '',
            'parameters': '',
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
                'Manage %s received-buffer reached max-size',
                self._socket.fileno(),
            )
            return True
        return False

    def request_state(self, args, poll):
        self.add_buf()
        line = self.check_if_line()
        if line:
            method, uri, signature = util.check_request(line)
            file_name = os.path.normpath(
                '%s%s' % (
                    args.base,
                    os.path.normpath(uri),
                )
            )
            self._request_context['method'] = method
            urlparsed = urlparse.urlparse(uri)
            self._request_context['uri'] = urlparsed.path
            self._request_context['parameters'] = urlparse.parse_qs(
                urlparsed.query
            )
            self._request_context['file_name'] = file_name
            if self._request_context['uri'] == '/manage':
                if len(self._request_context['parameters']) > 0:
                    if self._request_context['parameters']['url'][0] == 'all':
                        self._cache_handler.delete_all_cache()
                    else:
                        self._cache_handler.delete_cache(
                            self._request_context['parameters']['url'][0]
                        )
                self._manage = ManageInerface(
                    self._cache_handler,
                    self._request_context['application_context'],
                    self._logger,
                )
            elif self._request_context['uri'] != '/style.css':
                self._logger.info(
                    'Manage %s: %s request, %s, %s',
                    self._socket.fileno(),
                    method,
                    uri,
                    signature,
                )
            return True
        self.check_if_maxsize()
        return False

    def headers_state(self, args, poll):
        line = ' '
        while line:
            line = self.check_if_line()
            if line:
                self._request_context['headers'] = util.update_headers(
                    line,
                    self._request_context['headers'],
                )
        if self._received == constants.CRLF or line == '':
            return True
        self.check_if_maxsize()
        return False

    def content_state(self, args, poll):
        # print self._request_context['headers']
        # print 'LENGTH %s' % (
        #    type(str(self._request_context['headers']['Content-Length']))
        # )
        if int(self._request_context['headers']['Content-Length']) != 0:
            # if '0' is not '0':
            # print 'yo???'
            leng = int(self._request_context['headers']['Content-Length'])
            self._request_context['headers']['Content-Length'] = leng
            try:
                t = self._socket.recv(constants.BLOCK_SIZE)
                if not t:
                    raise RuntimeError('Disconnect')
                self._received += t
                if self._request_context['headers']['Content-Length'] == 0:
                    return True

            except socket.error as e:
                # print e.errno
                if e.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                    self._logger.error(
                        'Manage %s socket error: %s',
                        self._socket.fileno(),
                        e,
                    )
                    raise

            return False
        # self._socket.shutdown(socket.SHUT_RD)
        return True

    def response_status_state(self):
        self._to_send = (
            '%s 200 OK\r\n' % (constants.HTTP_SIGNATURE)
        ).encode('utf-8')
        return True

    def response_header_state(self):
        try:
            if self._manage:
                self._to_send += self._manage.get_headers()
            else:
                file_obj = open(self._request_context['file_name'], 'rb')
                self._request_context['file_obj'] = file_obj
                self._to_send += (
                    (
                        'Content-Length: %s\r\n'
                        'Content-Type: %s\r\n'
                        '\r\n'
                    ) % (
                        os.fstat(file_obj.fileno()).st_size,
                        constants.MIME_MAPPING.get(
                            os.path.splitext(
                                self._request_context['file_name']
                            )[1].lstrip('.'),
                            'application/octet-stream',
                        )
                    )
                ).encode('utf-8')
            return True

        except IOError as e:
            # traceback.print_exc()
            self._logger.error(
                'Manage %s socket error: %s',
                self._socket.fileno(),
                e,
            )
            self._state = CLOSING_STATE
            if e.errno == errno.ENOENT:
                self._to_send = util.return_status(404, 'File Not Found', e)
            else:
                self._to_send = util.return_status(500, 'Internal Error', e)

        except Exception as e:
            # print "ERROR " + str(e)
            # traceback.print_exc()
            self._logger.error(
                'Manage %s socket error: %s',
                self._socket.fileno(),
                e,
            )
            self._state = CLOSING_STATE
            self._to_send = util.return_status(500, 'Internal Error', e)

    def response_content_state(self):
        try:
            if self._manage:
                self._to_send += self._manage._body
                return True
            else:
                file_obj = self._request_context['file_obj']
                while len(self._to_send) < constants.TO_SEND_MAXSIZE:
                    buf = file_obj.read(constants.BLOCK_SIZE)
                    if not buf:
                        file_obj.close()
                        return True
                    self._to_send += buf
            return False

        except IOError as e:
            # traceback.print_exc()
            self._logger.error(
                'Manage %s socket error: %s',
                self._socket.fileno(),
                e,
            )
            self._state = CLOSING_STATE
            if e.errno == errno.ENOENT:
                self._to_send = util.return_status(404, 'File Not Found', e)
            else:
                self._to_send = util.return_status(500, 'Internal Error', e)

        except Exception as e:
            # print "ERROR " + str(e)
            # traceback.print_exc()
            self._logger.error(
                'Manage %s socket error: %s',
                self._socket.fileno(),
                e,
            )
            self._state = CLOSING_STATE
            self._to_send = util.return_status(500, 'Internal Error', e)

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
            "next": RESPONSE_STATUS_STATE
        },
        RESPONSE_STATUS_STATE: {
            "function": response_status_state,
            "next": RESPONSE_HEADER_STATE,
        },
        RESPONSE_HEADER_STATE: {
            "function": response_header_state,
            "next": RESPONSE_CONTENT_STATE,
        },
        RESPONSE_CONTENT_STATE: {
            "function": response_content_state,
            "next": CLOSING_STATE,
        },
        CLOSING_STATE: {
            "function": closing_state,
            "next": CLOSING_STATE,
        }
    }

    def on_read(self, poll, args):
        # print "MANAGE STATE " + str(self._state)
        while (self._state <= CONTENT_STATE and
                Manage.states[self._state]['function'](self, args, poll)):
            self._state = Manage.states[self._state]['next']
        return None

    def on_write(self):
        while (self._state < CLOSING_STATE and
                Manage.states[self._state]['function'](self)):
            # print 'COMPLETED %s' % self._state
            self._state = Manage.states[self._state]['next']
        # print "HERE?"
        # print self._to_send
        self._to_send = self.send_all()
        if not self._to_send and self._state == CLOSING_STATE:
            # print 'hey??'
            self._state = constants.CLOSING
            self.close_socket()
            return self
        return None

    def send_all(self):
        try:
            buf = self._to_send
            while buf:
                buf = buf[self._socket.send(buf):]

        except socket.error as e:
            if e.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                self._logger.error(
                    'Manage %s socket error: %s',
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
                    'Manage %s socket error: %s',
                    self._socket.fileno(),
                    e,
                )
                raise

    def check_if_line(self):
        # checks if theres a full line in what the socket received, if there
        # is returns it, if not adds buf to the 'received'
        buf = self._received
        n = buf.find(constants.CRLF_BIN)
        if n == -1:
            self.add_buf()
            return None
        line = buf[:n].decode('utf-8')
        self._received = buf[n + len(constants.CRLF_BIN):]
        return line

    def on_error(self):
        raise RuntimeError
        return None

    def get_fd(self):
        return self._socket.fileno()

    def get_events(self):
        # print '%s MANAGE STATE %s' % (self._socket.fileno(), self._state)
        events = select.POLLERR
        if (
            self._state >= REQUEST_STATE and
            self._state <= CONTENT_STATE
        ):
            events |= select.POLLIN

        if (
            self._state >= RESPONSE_STATUS_STATE and
            self._state <= CLOSING_STATE
        ):
            events |= select.POLLOUT
        # print 'MANAGE EVENTS %s %s' % (events, self._to_send)
        return events

    def close_socket(self):
        # print '%s MANAGELISTEN is closing' % str(self._socket.fileno())
        self._logger.debug(
            'Manage socket %s is closing' %
            self._socket.fileno()
        )
        # self._socket.shutdown(socket.SHUT_WR)
        self._socket.close()


class ManageListen(pollable.Pollable):
    def __init__(
        self,
        bind_address,
        bind_port,
        cache_handler,
        application_context,
        logger,
    ):
        self._cache_handler = cache_handler
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
                print 'Port', bind_port, 'already in use, trying again in 5sec'
                time.sleep(5)

    def on_read(self, poll, args):
        s1, add = self._socket.accept()
        fcntl.fcntl(
            s1.fileno(),
            fcntl.F_SETFL,
            fcntl.fcntl(s1.fileno(), fcntl.F_GETFL) |
            os.O_NONBLOCK
        )
        manage_obj = Manage(
            s1,
            {
                'Content-Length': '0',
            },
            self._cache_handler,
            self._application_context,
            self._logger,
        )
        # self._logger.info(
        #    'Local server request (Manage object created - %s)' % (
        #        manage_obj._socket.fileno()
        #    )
        # )
        # print "MANAGE OBJ %s%s: " % (manage_obj._socket.fileno(), manage_obj)
        poll.register(manage_obj)
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
        # print '%s MANAGELISTEN is closing' % str(self._socket.fileno())
        self._logger.debug(
            'ManageListen socket %s is closing' %
            self._socket.fileno()
        )
        # try:
        #    try:
        #        # socket, ssl.SSLSocket
        #        return self._socket.shutdown(socket.SHUT_RDWR)
        #    except TypeError:
        #        # SSL.Connection
        #        return self._socket.shutdown()
        # except socket.error, e:
        #    # we don't care if the socket is already closed;
        #    # this will often be the case in an http server context
        #    if e.errno != errno.ENOTCONN:
        #        raise
        self._socket.close()


(
    CACHE_FILES,
    THROUGHPUT,
    END
) = range(3)


class ManageInerface():
    def __init__(self, cache_handler, application_context, logger):
        self._state = CACHE_FILES
        self._body = ''
        self._length = 0
        self._cache_handler = cache_handler
        self._application_context = application_context
        self._logger = logger
        self.create_interface()

    def get_headers(self):
        return ('Content-Length: %s\r\n'
                'Content-Type: text/html\r\n\r\n') % (len(self._body))

    def cache_state(self):
        self._body += '<h2>Cache Stored</h2>'
        cache_files = self._cache_handler.get_cached()  # {
        #     'http://www.mechon-mamre.org/i/t/t09b18.htm': '20 April 2017'
        # }  # cache.get_cached()  # {name:date}
        self._body += util.build_cache_table(cache_files)

        return True

    def throughput_state(self):
        self._body += '<h2>Throughput Statistics</h2>'
        time_started = self._application_context['statistics']['throughput'][1]
        self._body += '<td> throughput rate for the last %s seconds:\r\n' % (
            int(round(time.time() - time_started))
        )
        if time_started + 10 > time.time():
            bytesent = self._application_context['statistics']['throughput'][0]
            self._body += '<td> %s bytes/second </td>' % (
                bytesent / (time.time() - time_started)
            )
        else:
            self._application_context[
                'statistics'
            ]['throughput'][1] = time.time()
            self._application_context['statistics']['throughput'][0] = 0
            self._body += '<td> %s bytes/second </td>' % (0.0)

        return True

    states = {
        CACHE_FILES: {
            "function": cache_state,
            "next": THROUGHPUT
        },
        THROUGHPUT: {
            "function": throughput_state,
            "next": END
        },

    }

    def create_interface(self):
        self._body = (
            # '<!DOCTYPE html>'
            '<html>'
            '<head>'
            '<title>Management</title>'
            '<link rel="stylesheet" type="text/css" href="style.css">'
            '</head>'
            '<meta http-equiv="refresh" content="1;URL=/manage" >'
            '<h1>Management Interface</h1>'
            '%s\t\t%s' % (
                util.refrash_form(),
                util.delete_all_form(),
            )
        )
        while (self._state <= THROUGHPUT and
                ManageInerface.states[self._state]['function'](self)):
            self._state = Manage.states[self._state]['next']
            self._body += '</html>'
