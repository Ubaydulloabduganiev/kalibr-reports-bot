from app.services.activation import hash_code, normalize_code


def test_activation_code_normalization():
    assert normalize_code(" kb-ab12-cd34 ") == "KB-AB12-CD34"
    assert hash_code("kb-ab12-cd34") == hash_code(" KB-AB12-CD34 ")
