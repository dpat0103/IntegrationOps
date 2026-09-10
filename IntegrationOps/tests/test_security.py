import pytest
from app.core.security import UnsafeEndpointError, validate_endpoint_url, encode_headers, decode_headers, generate_fernet_key


def test_blocks_private_and_metadata_targets():
    for url in ['http://127.0.0.1:8000','http://10.0.0.4','http://169.254.169.254/latest/meta-data','http://localhost:9000']:
        with pytest.raises(UnsafeEndpointError):
            validate_endpoint_url(url, allow_private=False)


def test_allows_public_target_and_explicit_dev_private_target():
    validate_endpoint_url('https://example.com/health', allow_private=False)
    validate_endpoint_url('http://127.0.0.1:8000/simulator/status', allow_private=True)


def test_headers_encrypt_round_trip():
    key = generate_fernet_key()
    encoded = encode_headers({'Authorization':'Bearer secret'}, key)
    assert encoded.startswith('fernet:')
    assert 'secret' not in encoded
    assert decode_headers(encoded, key) == {'Authorization':'Bearer secret'}
