# -*- coding: utf-8 -*-
## @package proxy.constants
# Constants used within the program.
## @file constants.py
# Implementation of @ref proxy.constants
#


## Block size for reading from files or sockets.
BLOCK_SIZE = 1024
## New line sign in HTTP protocol.
CRLF = '\r\n'
## CRLF encoded to utf-8.
CRLF_BIN = CRLF.encode('utf-8')
## Default proxy port for web servers.
DEFAULT_PROXY_PORT = 8080
## Default server port for web servers.
DEFAULT_SERVER_PORT = 9090
## HTTP signature.
HTTP_SIGNATURE = 'HTTP/1.1'
## Max header length.
MAX_HEADER_LENGTH = 4096
## Max number of headers.
MAX_NUMBER_OF_HEADERS = 100
## Mime mapping for HTTP protocol.
MIME_MAPPING = {
    'html': 'text/html',
    'png': 'image/png',
    'txt': 'text/plain',
}
## To-send buffer max length.
TO_SEND_MAXSIZE = 4096
## Max request length.
MAX_REQ_SIZE = 1000
## Path for cache to be stored.
CACHING_PATH = 'cache'
## Beggining of HTML table.
START_TABLE = (
    '<style>'
    'table, th, td {'
    'border: 1px solid black;'
    '}'
    '</style>'
    '<body>'

    '<table style="width:500px">'
    '<tr>'
    '<th>Num</th>'
    '<th>Url Cached</th>'
    '<th>Expiration Date</th>'
    '<th>Cache Hits'
    '<th>Delete</th>'
    '</tr>'
)
## End of HTML table.
END_TABLE = (
    '</table>'
    '</body>'
)
