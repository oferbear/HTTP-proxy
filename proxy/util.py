# -*- coding: utf-8 -*-

import errno
import socket

from . import constants


# python-3 woodo
try:
    # try python-2 module name
    import urlparse
except ImportError:
    # try python-3 module name
    import urllib.parse
    urlparse = urllib.parse


def spliturl(url):
    return urlparse.urlsplit(url)


def recv_line(
    s,
    buf,
    max_length=constants.MAX_HEADER_LENGTH,
    block_size=constants.BLOCK_SIZE,
):
    try:
        while True:
            # print "BUF "+buf
            if len(buf) > max_length:
                raise RuntimeError(
                    'Exceeded maximum line length %s' % max_length
                )
            n = buf.find(constants.CRLF_BIN)
            if n != -1:
                break
            t = s.recv(block_size)

            if not t:
                raise RuntimeError('Disconnect')
            buf += t
        # print "num"+str(n)
        # print buf[:n].decode('utf-8'), buf[n + len(constants.CRLF_BIN):]
        return buf[:n].decode('utf-8'), buf[n + len(constants.CRLF_BIN):]

    except socket.error as e:
        # print e.errno
        if e.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
            raise


def parse_header(line):
    SEP = ':'
    n = line.find(SEP)
    if n == -1:
        raise RuntimeError('Invalid header received')
    return line[:n].rstrip(), line[n + len(SEP):].lstrip()


def update_headers(line, headers):
    if len(headers) < constants.MAX_NUMBER_OF_HEADERS:
        k, v = parse_header(line)
        headers[k] = v
    else:
        raise RuntimeError('Too many headers')

    return headers


def check_response(res):
    # print res
    res_comps = res.split(' ', 2)
    if res_comps[0] != constants.HTTP_SIGNATURE:
        raise RuntimeError('Not HTTP protocol')
    if len(res_comps) != 3:
        raise RuntimeError('Incomplete HTTP protocol')

    signature, status_num, status = res_comps
    return signature, status_num, status


def check_request(req):
    # print "REQ"
    # print req
    req_comps = req.split(' ', 2)
    # print req_comps
    if req_comps[2] != constants.HTTP_SIGNATURE:
        raise RuntimeError('Not HTTP protocol')
    if len(req_comps) != 3:
        raise RuntimeError('Incomplete HTTP protocol')

    method, uri, signature = req_comps
    # print "METHOD, URI, SIGNATURE"
    # print method, uri, signature
    if method not in ('GET', 'CONNECT'):
        raise RuntimeError(
            "HTTP unsupported method '%s'" % method
        )
    if not uri:
        raise RuntimeError("Invalid URI")
    return method, uri, signature


def read_line(buf):
    n = buf.find(constants.CRLF_BIN)
    if n == -1:
        return '', ''
    line = buf[:n].decode('utf-8')
    return line, buf[n + len(constants.CRLF_BIN):]


def return_status(code, message, extra):
    response = (
        (
            (
                '%s %s %s\r\n'
                'Content-Type: text/plain\r\n'
                '\r\n'
                'Error %s %s\r\n'
            ) % (
                constants.HTTP_SIGNATURE,
                code,
                message,
                code,
                message,
            )
        ).encode('utf-8')
    )
    response += (
        (
            '%s' % extra
        ).encode('utf-8')
    )
    return response


def add_buf(
    self,
    socket,
    max_length=constants.MAX_HEADER_LENGTH,
    block_size=constants.BLOCK_SIZE,
):
    try:
        t = socket.recv(block_size)
        if not t:
            raise RuntimeError('Disconnect')
        return t

    except socket.error as e:
        # print e.errno
        if e.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
            raise


def build_cache_table(cache_files):
    body = constants.START_TABLE
    counter = 1
    for entry in cache_files.keys():
        body += (
            (
                '<tr align="center"> %s </tr>'
            ) % (
                '<td> %s </td>' % counter +
                '<td> %s </td>' % entry +
                '<td> %s </td>' % cache_files[entry][0] +
                '<td> %s </td>' % cache_files[entry][1] +
                '<td> %s </td>' % (
                    delete_form(entry)
                )
            )
        )
        counter += 1
    body += constants.END_TABLE
    return body


def delete_form(url):
    return (
        '<form action="/manage" enctype="multipart/form-data"'
        'method="GET">'
        '<input type="hidden" name="url" value=%s>'
        '<input type="submit" value="delete">'
        '</form>'
    ) % (
        url,
    )


def delete_all_form():
    return (
        '<form action="/manage" enctype="multipart/form-data"'
        'method="GET">'
        '<input type="hidden" name="url" value=all>'
        '<input type="submit" value="delete all">'
        '</form>'
    )


def refrash_form():
    return (
        '<form action="/manage">'
        '<input type="submit" value="refrash">'
        '</form>'
    )

# vim: expandtab tabstop=4 shiftwidth=4
