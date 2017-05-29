## @package proxy.http_server
# Module for HttpServer, ServerListen, ManageInerface objects.
#

import constants
import errno
import fcntl
import os
import pollable
import select
import socket
import time
import urlparse
import util

## States for parsing HTTP request and sending response.
(
    REQUEST_STATE,
    HEADERS_STATE,
    CONTENT_STATE,
    RESPONSE_STATUS_STATE,
    RESPONSE_HEADER_STATE,
    RESPONSE_CONTENT_STATE,
    CLOSING_STATE,
) = range(7)


## HttpServer object for receiving HTTP requests from source server and
# responding to it.
#
# Created from ServerListen object.
#
class HttpServer(pollable.Pollable):
    ## Constructor.
    # @param socket (socket)
    # @param headers (dict)
    # @param cache_handler (Cache)
    # @param application_context (dict)
    # @param logger (logging.Logger)
    #
    def __init__(
        self,
        socket,
        headers,
        cache_handler,
        application_context,
        logger,
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

    ## Checks if received buffer length exceeded max request/response length.
    # If true, closing socket and sending error message.
    # @returns (bool) whether buffer exceeded max length.
    #
    def check_if_maxsize(self):
        if len(self._received) > constants.MAX_REQ_SIZE:
            self._to_send = util.return_status(500, 'Internal Error', '')
            self._state = CLOSING_STATE
            self._logger.error(
                'HttpServer %s received-buffer reached max-size',
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
                    'HttpServer %s: %s request, %s, %s',
                    self._socket.fileno(),
                    method,
                    uri,
                    signature,
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

    ## Receives requests content part from the source server.
    # @param args (dict) program arguments.
    # @param poll object (poll).
    # @returns (boll) if ready to move to next state.
    #
    def content_state(self, args, poll):
        if int(self._request_context['headers']['Content-Length']) != 0:
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
                if e.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                    self._logger.error(
                        'HttpServer %s socket error: %s',
                        self._socket.fileno(),
                        e,
                    )
                    raise

            return False
        return True

    ## Builds responses status line.
    # @returns (boll) if ready to move to next state.
    #
    def response_status_state(self):
        self._to_send = (
            '%s 200 OK\r\n' % (constants.HTTP_SIGNATURE)
        ).encode('utf-8')
        return True

    ## Builds response headers part.
    # @returns (boll) if ready to move to next state.
    #
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
            self._logger.error(
                'HttpServer %s socket error: %s',
                self._socket.fileno(),
                e,
            )
            self._state = CLOSING_STATE
            if e.errno == errno.ENOENT:
                self._to_send = util.return_status(404, 'File Not Found', e)
            else:
                self._to_send = util.return_status(500, 'Internal Error', e)

        except Exception as e:
            self._logger.error(
                'HttpServer %s socket error: %s',
                self._socket.fileno(),
                e,
            )
            self._state = CLOSING_STATE
            self._to_send = util.return_status(500, 'Internal Error', e)

    ## Builds response content part.
    # @returns (boll) if ready to move to next state.
    #
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
            self._logger.error(
                'HttpServer %s socket error: %s',
                self._socket.fileno(),
                e,
            )
            self._state = CLOSING_STATE
            if e.errno == errno.ENOENT:
                self._to_send = util.return_status(404, 'File Not Found', e)
            else:
                self._to_send = util.return_status(500, 'Internal Error', e)

        except Exception as e:
            self._logger.error(
                'HttpServer %s socket error: %s',
                self._socket.fileno(),
                e,
            )
            self._state = CLOSING_STATE
            self._to_send = util.return_status(500, 'Internal Error', e)

    ## Final state. Finished receiving. Ready to close socket.
    # @returns (boll) if ready to move to next state.
    #
    def closing_state(self):
        if not self._to_send:
            self.close_socket()
        return True

    ## dict of HttpServer state machine.
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

    ## Function to be called when poller have a POLLIN event.
    # HttpServer is in the process of receving request from the source server.
    # @param poll object (poll).
    # @param args (dict) program arguments.
    # @returns (ProxySocket) object to be removed from poll.
    #
    def on_read(self, poll, args):
        while (self._state <= CONTENT_STATE and
                HttpServer.states[self._state]['function'](self, args, poll)):
            self._state = HttpServer.states[self._state]['next']
        return None

    ## Function to be called when poller have a POLLOUT event.
    # ProxySocket is in the process of sending response to the source server.
    # @returns (ProxySocket) object to be removed from poll.
    #
    def on_write(self):
        while (self._state < CLOSING_STATE and
                HttpServer.states[self._state]['function'](self)):
            self._state = HttpServer.states[self._state]['next']
        self._to_send = self.send_all()
        if not self._to_send and self._state == CLOSING_STATE:
            self.close_socket()
            return self
        return None

    ## Sends everything possible from to_send buffer.
    # @returns (str) string from buffer that couldn't be sent.
    #
    def send_all(self):
        try:
            buf = self._to_send
            while buf:
                buf = buf[self._socket.send(buf):]

        except socket.error as e:
            if e.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                self._logger.error(
                    'HttpServer %s socket error: %s',
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
                    'HttpServer %s socket error: %s',
                    self._socket.fileno(),
                    e,
                )
                raise

    ## Checks if theres a line in the received buffer, and returns it.
    # @returns (str) line that was found in received buffer.
    #
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

    ## Function to be called when poller have a POLLERR event.
    # Socket has encountered an error, closing socket.
    # @returns (ProxySocket) object to be removed from poll.
    #
    def on_error(self):
        raise RuntimeError
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
        return events

    ## Closing socket.
    #
    def close_socket(self):
        self._logger.debug(
            'HttpServer socket %s is closing' %
            self._socket.fileno()
        )
        self._socket.close()


## ServerListen object to accept new connections.
#
# Created by the __main__ function.
# Creates HttpServer object.
#
class ServerListen(pollable.Pollable):
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

    ## Function to be called when poller have a POLLIN event.
    # ServerListen is accepting new connection and creates HttpServer object
    # @param poll object (poll).
    # @param args (dict) program arguments.
    # @returns (ServerListen) object to be removed from poll.
    #
    def on_read(self, poll, args):
        s1, add = self._socket.accept()
        fcntl.fcntl(
            s1.fileno(),
            fcntl.F_SETFL,
            fcntl.fcntl(s1.fileno(), fcntl.F_GETFL) |
            os.O_NONBLOCK
        )
        server_obj = HttpServer(
            s1,
            {
                'Content-Length': '0',
            },
            self._cache_handler,
            self._application_context,
            self._logger,
        )
        poll.register(server_obj)
        return None

    ## Function to be called when poller have a POLLOUT event.
    # @returns (ServerListen) object to be removed from poll.
    #
    def on_write(self):
        return None

    ## Function to be called when poller have a POLLERR event.
    # @returns (ServerListen) object to be removed from poll.
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
            'ServerListen socket %s is closing' %
            self._socket.fileno()
        )

        self._socket.close()


## States for creating management interface.
(
    CACHE_FILES,
    THROUGHPUT,
    END
) = range(3)


## Class for creating the management interface.
#
# Created by the HttpServer object, when the uri '/manage' is requested.
#
class ManageInerface():
    ## Constructor.
    # @param cache_handler (Cache)
    # @param application_context (dict)
    # @param logger (logging.Logger)
    #
    def __init__(self, cache_handler, application_context, logger):
        self._state = CACHE_FILES
        self._body = ''
        self._length = 0
        self._cache_handler = cache_handler
        self._application_context = application_context
        self._logger = logger
        self.create_interface()

    ## Returns headers for management page.
    # @returns headers (str)
    #
    def get_headers(self):
        return ('Content-Length: %s\r\n'
                'Content-Type: text/html\r\n\r\n') % (len(self._body))

    ## Builds the cached table in the management page.
    # @returns (boll) if ready to move to next state.
    #
    def cache_state(self):
        self._body += '<h3>Cache Stored</h3>'
        cache_files = self._cache_handler.get_cached()
        # cache.get_cached()  # {name:[date, hits]}
        self._body += util.build_cache_table(cache_files)

        return True

    ## Builds the throughput part of the management page.
    # @returns (boll) if ready to move to next state.
    #
    def throughput_state(self):
        self._body += '<h3>Throughput Statistics</h3>'
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

    ## State machine for bulding the management page.
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

    ## Creates the interface in the management page.
    #
    def create_interface(self):
        self._body = (
            '<html>'
            '<head>'
            '<title>Management</title>'
            '<link rel="stylesheet" type="text/css" href="style.css">'
            '</head>'
            '<meta http-equiv="refresh" content="1;URL=/manage" >'
            '<h1>HTTP Proxy by Ofer Bear</h1>'
            '<h2>Management Interface</h2>'
            '%s\t\t%s' % (
                util.refrash_form(),
                util.delete_all_form(),
            )
        )
        while (self._state <= THROUGHPUT and
                ManageInerface.states[self._state]['function'](self)):
            self._state = HttpServer.states[self._state]['next']
            self._body += '</html>'
