# -*- coding: utf-8 -*-

BLOCK_SIZE = 1024
CRLF = '\r\n'
CRLF_BIN = CRLF.encode('utf-8')
DEFAULT_HTTP_PORT = 80
HTTP_SIGNATURE = 'HTTP/1.1'
MAX_HEADER_LENGTH = 4096
MAX_NUMBER_OF_HEADERS = 100
LISTEN = 'listen'
ACTIVE = 'active'
CLOSING = 'closing'
MIME_MAPPING = {
    'html': 'text/html',
    'png': 'image/png',
    'txt': 'text/plain',
}
TO_SEND_MAXSIZE = 4096
MAX_REQ_SIZE = 1000
CACHING_PATH = 'cache'
CACHE_EXPIR_DAYS = 3
SECONDS_IN_DAY = 86400
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
END_TABLE = (
    '</table>'
    '</body>'
)

# vim: expandtab tabstop=4 shiftwidth=4
