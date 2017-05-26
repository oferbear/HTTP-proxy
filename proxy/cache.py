import constants
import datetime
import hashlib
import os
import os.path
import time
import traceback
import util


class Cache():
    def __init__(self, logger):
        self._opened_files = {}
        self._logger = logger

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
            # print exp_date
            parsed_metadata['hits'] = int(parsed_metadata['hits']) + 1
            self.update_metadata(metadata_file, parsed_metadata)
            metadata_file.close()
            # print 'EXP DATE %s TIME NOW %s' % (exp_date, time.time())
            if int(exp_date) >= time.time():
                return True
            else:
                self.delete_cache(request_context['uri'])
        return False

    def update_metadata(self, fd, data):
        fd.truncate(0)
        fd.seek(0, 0)
        # print 'METADATA %s' % data
        for key in data.keys():
            fd.write('%s:%s\r\n' % (key, data[key]))

    def check_headers(self, headers):
        if 'Cache-Control' in headers:
            # print 'CACHE HEADERS %s' % headers
            cache_header = headers['Cache-Control']
            # print 'CACHE HEADER %s' % cache_header
            parsed_header = self.parse_cache_header(cache_header)
            if 'max-age' in parsed_header:
                if int(parsed_header['max-age']) > 0:
                    return int(parsed_header['max-age'])
        return False

    def check_if_cache(self, request_context):
        try:
            try:
                os.mkdir('%s/cache' % os.getcwd())
            except OSError as e:
                # print 'cache directory already existes'
                pass

            try:
                os.mkdir('%s/cache/metadata' % os.getcwd())
            except OSError as e:
                # print 'exp directory already existes'
                pass

            # check_header = self.check_headers(request_context)
            # if check_header is True:
            if self.check_if_exist(request_context):
                # print 'FILE IS THERE'
                # if self.check_date():
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
            # self.create_files(request_context, check_header)
            # print 'CACHE DOESNT EXIST'
            return False

        except Exception as e:
            traceback.print_exc()
            # print 'ERROR WITH CACHE FILE %s' % e
            self._logger.error('Error with cache file %s', e)
            return False

    def parse_cache_header(self, cache_header):
        to_return = {}
        for entry in cache_header.split(','):
            splt = entry.split('=')
            if len(splt) > 1:
                to_return[splt[0]] = splt[1]
            else:
                to_return[entry] = None
        return to_return

    def load_response(self, request_context, to_send_len):
        try:
            read = ''
            if (
                request_context['uri'] in self._opened_files and
                to_send_len < constants.TO_SEND_MAXSIZE
            ):
                # print 'ARE YOU HERE?????'
                read = self._opened_files[request_context['uri']].read(
                    constants.TO_SEND_MAXSIZE - to_send_len
                )
                if not read:
                    # self._cache = False  # we finished using the cache file
                    # self._http_obj._closing = True
                    # print 'CACHE %s IS CLOSINGGG' % request_context['uri']
                    self._opened_files[request_context['uri']].close()
                    del self._opened_files[request_context['uri']]
                # self._http_obj._to_send += read
            # print request_context['uri']
            # print 'READ %s' % (read)
            return read

        except Exception as e:
            # print 'ERROR READING CACHE FILE %s' % e
            self._logger.error('Error with cache file %s', e)
            traceback.print_exc()

    def create_files(self, request_context, exp):
        try:
            # print '%s %s/%s/%s' % (
            #    'CACHE FILENAME',
            #    os.getcwd(),
            #    constants.CACHING_PATH,
            #    self.encode_url(
            #        request_context['uri'],
            #    ),
            # )
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
            # self._cached[request_context['uri']][1] = int(time.time())+exp
            # print '%s %s/%s/exp/%s' % (
            #    'EXP FILE NAME',
            #    os.getcwd(),
            #    constants.CACHING_PATH,
            #    self.encode_url(
            #        request_context['uri'],
            #    )
            # )
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
            # print 'EXP TIME %s' % self._cached[request_context['uri']][1]
            metadata_file.write(
                'expiration_date:%s\r\n'
                'url:%s\r\n'
                'hits:0\r\n' % (
                    int(time.time()) + exp,
                    request_context['uri'],
                )
            )
            metadata_file.close()
            # print 'FILES CREATED'

        except Exception as e:
            # print 'ERROR CREATING FILES %s' % e
            self._logger.error('Error creating files %s', e)
            traceback.print_exc()

    def add_cache(self, request_context, to_add):
        # print 'OPENED FILES %s' % self._opened_files
        if request_context['uri'] in self._opened_files:
            # print self._file
            # print 'TO ADD CACHE: %s' % to_add
            # print 'WRITING TO FILE: %s' % (request_context['uri'])
            self._opened_files[request_context['uri']].write(to_add)

    def get_cached(self):
        try:
            os.mkdir('%s/cache' % os.getcwd())
        except OSError:
            # print 'directory already existes'
            pass

        to_return = {}
        for fn in os.listdir('%s/cache' % os.getcwd()):
            # print fn
            if (
                os.path.isfile('%s/cache/%s' % (os.getcwd(), fn)) and
                not fn.startswith('.')
            ):
                # print 'yo' + str(fn)
                metadata_file = open(
                    '%s/%s/metadata/%s' % (
                        os.getcwd(),
                        constants.CACHING_PATH,
                        fn,
                    ),
                    'rb',
                )
                parsed_metadata = self.parse_metadata(metadata_file)
                # print 'METADATA %s' % parsed_metadata
                exp_date = parsed_metadata['expiration_date']
                uri = parsed_metadata['url']
                hits = parsed_metadata['hits']
                # print exp_date
                metadata_file.close()
                to_return[uri] = [
                    datetime.datetime.fromtimestamp(
                        float(exp_date),
                    ).strftime('%c'),
                    hits,
                ]
        return to_return

    def delete_cache(self, url):
        # del self._cached[url]
        url = self.encode_url(url)
        os.remove('%s/cache/%s' % (os.getcwd(), url))
        os.remove('%s/cache/metadata/%s' % (os.getcwd(), url))

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
        # print 'THIS SHOULD BE EMPTY %s' % self._cached

    def parse_metadata(self, fd):
        to_return = {}
        read = fd.read(constants.BLOCK_SIZE)
        line, read = util.read_line(read)
        while line:
            splt = line.split(':', 1)
            to_return[splt[0]] = splt[1]
            line, read = util.read_line(read)
        return to_return

    def encode_url(self, url):
        sha1 = hashlib.sha1()
        sha1.update(url)
        return sha1.hexdigest()
