import os


#WEBSOCKET_URL = os.environ.get('WEBSOCKET_URL', "ws://127.0.0.1:8095")

# If local node is not running, remote TUSC node could be used
WEBSOCKET_URL = os.environ.get('WEBSOCKET_URL', "wss://tuscapi.gambitweb.com")

# Default connection to Elastic Search.
ELASTICSEARCH = {
    'hosts': os.environ.get('ELASTICSEARCH_URL', 'http://localhost:9200').split(','),
    'user': os.environ.get('ELASTICSEARCH_USER', 'TUSC'),
    'password': os.environ.get('ELASTICSEARCH_PASS', 'CSUT')
}


# Optional ElasticSearch cluster to access other data.
# Currently expect:
#   - 'operations': for bitshares-* indexes where operations are stored
#   - 'objects': for objects-* indexes where Chain data is stored.
#
# Sample:
#
# ELASTICSEARCH_ADDITIONAL {
#   'operations': None, # Use default cluster.
#   'objects': {
#     'hosts': ['https://es.mycompany.com/'],
#     'user': 'myself',
#     'password': 'secret'
#    }
# }
ELASTICSEARCH_ADDITIONAL = {
    # Overwrite cluster to use to retrieve bitshares-* index.
    'operations': None,
    # Overwrite cluster to use to retrieve bitshares-* index.
    'objects': {
        'hosts': ['http://localhost:9200']  # infra
    }

}

# Cache: see https://flask-caching.readthedocs.io/en/latest/#configuring-flask-caching
CACHE = {
    # use 'uwsgi' when running under uWSGI server.
    'CACHE_TYPE': os.environ.get('CACHE_TYPE', 'simple'),
    # 10 min
    'CACHE_DEFAULT_TIMEOUT': int(os.environ.get('CACHE_DEFAULT_TIMEOUT', 600))
}

# Configure profiler: see https://github.com/muatik/flask-profiler
PROFILER = {
    'enabled': os.environ.get('PROFILER_ENABLED', False),
    'username': os.environ.get('PROFILER_USERNAME', None),
    'password': os.environ.get('PROFILER_PASSWORD', None),
}

CORE_ASSET_SYMBOL = 'TUSC'
CORE_ASSET_ID = '1.3.0'

TESTNET = 0  # 0 = not in the testnet, 1 = testnet
CORE_ASSET_SYMBOL_TESTNET = 'TEST'

# Choose which APIs to expose, default to all.
#EXPOSED_APIS = ['explorer', 'es_wrapper', 'udf']
