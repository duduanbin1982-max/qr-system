import logging


def test_validation_log_never_contains_request_values(client, caplog):
    secret_password = 'P1-plaintext-password-must-not-be-logged'

    with caplog.at_level(logging.ERROR, logger='qr'):
        response = client.post('/api/auth/login', json={'password': secret_password})

    assert response.status_code == 400
    assert secret_password not in caplog.text
    assert 'body(raw)' not in caplog.text
    assert 'SCHEMA_VALIDATE_FAILED: login' in caplog.text
    assert 'validator: required' in caplog.text
    assert 'payload_shape: object(fields=1)' in caplog.text


def test_validation_response_never_echoes_sensitive_invalid_value(client, caplog):
    short_password = 'p@1'

    with caplog.at_level(logging.ERROR, logger='qr'):
        response = client.post(
            '/api/auth/login',
            json={'username': 'validation-security-test', 'password': short_password},
        )

    assert response.status_code == 400
    body = response.get_json()
    assert short_password not in response.get_data(as_text=True)
    assert short_password not in caplog.text
    assert body['error'] == '参数校验失败: password — 长度不能少于 6 个字符'
    assert 'validator: minLength' in caplog.text


def test_validation_log_does_not_emit_non_sensitive_request_values(client, caplog):
    user_supplied_value = 'attacker-controlled-value-must-not-enter-logs'

    with caplog.at_level(logging.ERROR, logger='qr'):
        response = client.post(
            '/api/auth/login',
            json={
                'username': user_supplied_value,
                'password': 'valid-password',
                'unexpected': {'token': 'nested-secret'},
            },
        )

    assert response.status_code == 400
    assert user_supplied_value not in caplog.text
    assert 'nested-secret' not in caplog.text
    assert 'unexpected' not in caplog.text
    assert 'validator: additionalProperties' in caplog.text
    assert 'payload_shape: object(fields=3)' in caplog.text
