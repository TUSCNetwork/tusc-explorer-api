import pytest

from services.tusc_websocket_client import TUSCWebsocketClient
import config

@pytest.fixture
def tusc_client():
    return TUSCWebsocketClient(config.WEBSOCKET_URL)

def test_ws_request(tusc_client):
    response = tusc_client.request('database', "get_dynamic_global_properties", [])
    assert response['id'] == '2.1.0'
    assert 'head_block_number' in response

def test_automatic_api_id_retrieval(tusc_client):
    tusc_client.request('asset', 'get_asset_holders', ['1.3.0', 0, 100])

def test_get_object(tusc_client):
    object = tusc_client.get_object('1.3.0')
    assert object