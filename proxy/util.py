# -*- coding: utf-8 -*-
## @package proxy.util
# Module for util functions.
#

import constants
import errno
import socket


# python-3 woodo
try:
    # try python-2 module name
    import urlparse
except ImportError:
    # try python-3 module name
    import urllib.parse
    urlparse = urllib.parse


## Parse header line.
# @returns (tuple) header, content
#
def parse_header(line):
    SEP = ':'
    n = line.find(SEP)
    if n == -1:
        raise RuntimeError('Invalid header received')
    return line[:n].rstrip(), line[n + len(SEP):].lstrip()


## Add header to existing headers dict.
# @param headers (dict)
# @return headers (dict)
#
def update_headers(line, headers):
    if len(headers) < constants.MAX_NUMBER_OF_HEADERS:
        k, v = parse_header(line)
        headers[k] = v
    else:
        raise RuntimeError('Too many headers')

    return headers


## Checks if response status line is valid, and parse it.
# @param status line (str)
# @returns http signatue (str)
# @returns status code (str)
# @returns status (str)
#
def check_response(res):
    res_comps = res.split(' ', 2)
    if res_comps[0] != constants.HTTP_SIGNATURE:
        raise RuntimeError('Not HTTP protocol')
    if len(res_comps) != 3:
        raise RuntimeError('Incomplete HTTP protocol')

    signature, status_num, status = res_comps
    return signature, status_num, status


## Checks if request first line is valid, and parse it.
# @param first line (str)
# @returns method (str)
# @returns uri (str)
# @returns http signature (str)
#
def check_request(req):
    req_comps = req.split(' ', 2)
    if req_comps[2] != constants.HTTP_SIGNATURE:
        raise RuntimeError('Not HTTP protocol')
    if len(req_comps) != 3:
        raise RuntimeError('Incomplete HTTP protocol')

    method, uri, signature = req_comps
    if method not in ('GET', 'CONNECT'):
        raise RuntimeError(
            "HTTP unsupported method '%s'" % method
        )
    if not uri:
        raise RuntimeError("Invalid URI")
    return method, uri, signature


## Finds line in text.
# @param text (str)
# @returns line, rest of text (tuple)
#
def read_line(buf):
    n = buf.find(constants.CRLF_BIN)
    if n == -1:
        return '', ''
    line = buf[:n].decode('utf-8')
    return line, buf[n + len(constants.CRLF_BIN):]


## Creates an error HTTP response.
# @param code (int)
# @param message (str)
# @param extra (str)
#
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


## Builds HTML table with cache data.
# @param cache_files (dict)
# @returns table body (str)
#
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


## Creates HTML form for deleting cache entry.
# @param url to be deleted (str)
# @returns form (str)
#
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


## Creates HTML form for deleting all cache entries.
# @returns form (str)
#
def delete_all_form():
    return (
        '<form action="/manage" enctype="multipart/form-data"'
        'method="GET">'
        '<input type="hidden" name="url" value=all>'
        '<input type="submit" value="delete all">'
        '</form>'
    )


## Creates HTML form for refrash button.
# @returns form (str)
#
def refrash_form():
    return (
        '<form action="/manage">'
        '<input type="submit" value="refrash">'
        '</form>'
    )
