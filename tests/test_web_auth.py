from house_monitor.web_auth import hash_password, verify_password


def test_password_hash_roundtrip():
    encoded = hash_password("StrongPass!234", iterations=1000)
    assert encoded.startswith("pbkdf2_sha256$1000$")
    assert verify_password("StrongPass!234", encoded) is True
    assert verify_password("wrong", encoded) is False


def test_password_hash_is_salted():
    first = hash_password("StrongPass!234", iterations=1000)
    second = hash_password("StrongPass!234", iterations=1000)
    assert first != second
    assert verify_password("StrongPass!234", first)
    assert verify_password("StrongPass!234", second)