## @package proxy.cache
# Handles all cache activities
## @file cache.py
# Implementation of @ref proxy.cache
#

import constants
import datetime
import hashlib
import os
import os.path
import time
import traceback
import util


## Cache Handler.
#
# Created when the program boots.
# Handles all cache activities.
#
class Cache():
    ## Constructor.
    # @param logger (logging.Logger)
    def __init__(self, logger):
        # Currently opened files
        self._opened_files = {}
        self._logger = logger

    ## Checks if cache file exists and not expired.
    # @param request_context (dict).
    # @returns (bool) whether file exist or not.
    #
    def check_if_exist(self, request_context):
        if request_context['uri'] in self._opened_files:
            return False
        if (
            os.path.isfile(
                '%s/cache/%s' % (
                    os.getcwd(),
                    self.encode_url(
                        request_context['uri']
                    ),
                )
            )
        ):
            metadata_file = open(
                '%s/%s/metadata/%s' % (
                    os.getcwd(),
                    constants.CACHING_PATH,
                    self.encode_url(request_context['uri']),
                ),
                'rb+',
            )
            parsed_metadata = self.parse_metadata(metadata_file)
            exp_date = parsed_metadata['expiration_date']
            parsed_metadata['hits'] = int(parsed_metadata['hits']) + 1
            self.update_metadata(metadata_file, parsed_metadata)
            metadata_file.close()
            if int(exp_date) >= time.time():
                return True
            else:
                self.delete_cache(request_context['uri'])
        return False

    ## Updates (rewrites) the metadata file
    # @param fd (file).
    # @param data (dict).
    #
    def update_metadata(self, fd, data):
        fd.truncate(0)
        fd.seek(0, 0)
        for key in data.keys():
            fd.write('%s:%s\r\n' % (key, data[key]))

    ## Checks if response should be cached or not.
    # Based on headers from the HTTP response.
    # @param headers (dict) response headers.
    #
    def check_headers(self, headers):
        if 'Cache-Control' in headers:
            cache_header = headers['Cache-Control']
            parsed_header = self.parse_cache_header(cache_header)
            if 'max-age' in parsed_header:
                if int(parsed_header['max-age']) > 0:
                    return int(parsed_header['max-age'])
        return False

    ## Checks whether file should be cached or not.
    # @param request_context (dict).
    # @returns (bool) whether file should be cached or not.
    #
    def check_if_cache(self, request_context):
        if request_context['method'] == 'CONNECT':
            return False
        try:
            try:
                os.mkdir('%s/cache' % os.getcwd())
            except OSError as e:
                pass

            try:
                os.mkdir('%s/cache/metadata' % os.getcwd())
            except OSError as e:
                pass

            if self.check_if_exist(request_context):
                self._opened_files[request_context['uri']] = open(
                    '%s/%s/%s' % (
                        os.getcwd(),
                        constants.CACHING_PATH,
                        self.encode_url(
                            request_context['uri'],
                        )
                    ),
                    'rb',
                )
                return True
            return False

        except Exception as e:
            traceback.print_exc()
            self._logger.error('Error with cache file %s', e)
            return False

    ## Parsing Cache-Control header.
    # @param cache_header (str) cache header.
    # @returns (dict) parsed cache header.
    #
    def parse_cache_header(self, cache_header):
        to_return = {}
        for entry in cache_header.split(','):
            splt = entry.split('=')
            if len(splt) > 1:
                to_return[splt[0]] = splt[1]
            else:
                to_return[entry] = None
        return to_return

    ## Loads response from cache.
    # Reades from relevent cache file and return requested number of bytes.
    # @param request_context (dict).
    # @param to_send_len (int) length of socket-object to_send.
    # @returns part of the cached response (str).
    #
    def load_response(self, request_context, to_send_len):
        try:
            read = ''
            if (
                request_context['uri'] in self._opened_files and
                to_send_len < constants.TO_SEND_MAXSIZE
            ):
                read = self._opened_files[request_context['uri']].read(
                    constants.TO_SEND_MAXSIZE - to_send_len
                )
                if not read:
                    self._opened_files[request_context['uri']].close()
                    del self._opened_files[request_context['uri']]
            return read

        except Exception as e:
            self._logger.error('Error with cache file %s', e)
            traceback.print_exc()

    ## Creates files for new cache storage.
    # @param request_context (dict).
    # @param exp - time to expire in seconds (int).
    #
    def create_files(self, request_context, exp):
        try:
            self._opened_files[request_context['uri']] = open(
                '%s/%s/%s' % (
                    os.getcwd(),
                    constants.CACHING_PATH,
                    self.encode_url(
                        request_context['uri'],
                    ),
                ),
                'wb',
            )
            metadata_file = open(
                '%s/%s/metadata/%s' % (
                    os.getcwd(),
                    constants.CACHING_PATH,
                    self.encode_url(
                        request_context['uri'],
                    ),
                ),
                'wb',
            )
            metadata_file.write(
                'expiration_date:%s\r\n'
                'url:%s\r\n'
                'hits:0\r\n' % (
                    int(time.time()) + exp,
                    request_context['uri'],
                )
            )
            metadata_file.close()

        except Exception as e:
            self._logger.error('Error creating files %s', e)
            traceback.print_exc()

    ## Writes data to opend cache file.
    # @param request_context (dict).
    # @param to_add (str) text to written to file.
    #
    def add_cache(self, request_context, to_add):
        if request_context['uri'] in self._opened_files:
            self._opened_files[request_context['uri']].write(to_add)

    ## Get all cached responses.
    # @returns (dict) dict with all urls cached, their expiration date & hits.
    #
    def get_cached(self):
        try:
            os.mkdir('%s/cache' % os.getcwd())
        except OSError:
            pass

        to_return = {}
        for fn in os.listdir('%s/cache' % os.getcwd()):
            if (
                os.path.isfile('%s/cache/%s' % (os.getcwd(), fn)) and
                not fn.startswith('.')
            ):
                metadata_file = open(
                    '%s/%s/metadata/%s' % (
                        os.getcwd(),
                        constants.CACHING_PATH,
                        fn,
                    ),
                    'rb',
                )
                parsed_metadata = self.parse_metadata(metadata_file)
                exp_date = parsed_metadata['expiration_date']
                uri = parsed_metadata['url']
                hits = parsed_metadata['hits']
                metadata_file.close()
                to_return[uri] = [
                    datetime.datetime.fromtimestamp(
                        float(exp_date),
                    ).strftime('%c'),
                    hits,
                ]
        return to_return

    ## Deletes cache file.
    # @param url (str) a url whose response will be deleted.
    #
    def delete_cache(self, url):
        url = self.encode_url(url)
        os.remove('%s/cache/%s' % (os.getcwd(), url))
        os.remove('%s/cache/metadata/%s' % (os.getcwd(), url))

    ## Delets all cached files.
    #
    def delete_all_cache(self):
        for key in os.listdir('%s/cache' % os.getcwd()):
            if (
                os.path.isfile('%s/cache/%s' % (os.getcwd(), key)) and
                not key.startswith('.')
            ):
                metadata_file = open(
                    '%s/%s/metadata/%s' % (
                        os.getcwd(),
                        constants.CACHING_PATH,
                        key,
                    ),
                    'rb',
                )
                parsed_metadata = self.parse_metadata(metadata_file)
                uri = parsed_metadata['url']
                metadata_file.close()
                fn = self.encode_url(uri)
                os.remove('%s/cache/%s' % (os.getcwd(), fn))
                os.remove('%s/cache/metadata/%s' % (os.getcwd(), fn))

    ## Parse metadata file content.
    # @param fd (file) metadata file to be parsed.
    #
    def parse_metadata(self, fd):
        to_return = {}
        read = fd.read(constants.BLOCK_SIZE)
        line, read = util.read_line(read)
        while line:
            splt = line.split(':', 1)
            to_return[splt[0]] = splt[1]
            line, read = util.read_line(read)
        return to_return

    ## Encode url to sha1 encoding.
    # @param url to be encoded (str).
    #
    def encode_url(self, url):
        sha1 = hashlib.sha1()
        sha1.update(url)
        return sha1.hexdigest()
