import os
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ["DATABASE_URL"] = "postgresql+psycopg2://test@127.0.0.1:1/cloudchat_test"
os.environ["FLASK_SECRET_KEY"] = "unit-test-flask-secret-key"
os.environ["DEEPSEEK_API_KEY"] = "unit-test-model-key"
os.environ["FRONTEND_BASE_URL"] = "https://www.rendazhang.com"

from flask.sessions import SecureCookieSessionInterface

import app as app_module
import app_auth
from security_policy import MAX_CHAT_MESSAGE_CHARS, MAX_JSON_BODY_BYTES


class AppSecurityBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.original_session_interface = app_module.app.session_interface
        app_module.app.session_interface = SecureCookieSessionInterface()
        app_module.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.client = app_module.app.test_client()

    def tearDown(self):
        app_module.app.session_interface = self.original_session_interface

    def test_host_allowlist_accepts_loopback_and_rejects_unknown_hosts(self):
        self.assertEqual(
            self.client.get("/test", headers={"Host": "127.0.0.1:5000"}).status_code,
            200,
        )
        self.assertEqual(
            self.client.get("/test", headers={"Host": "untrusted.example"}).status_code,
            400,
        )

    def test_chat_rejects_malformed_wrong_shape_and_wrong_type_json(self):
        cases = (
            ("not-json", "application/json"),
            ('["message"]', "application/json"),
            ('{"message":42}', "application/json"),
            ('{"message":"hello","guideMode":[]}', "application/json"),
        )
        for body, content_type in cases:
            with self.subTest(body=body):
                response = self.client.post(
                    "/deepseek_chat", data=body, content_type=content_type
                )
                self.assertEqual(response.status_code, 400)

    def test_chat_rejects_overlong_and_oversized_messages(self):
        with patch.object(app_module, "rate_limit_allowed", return_value=True):
            response = self.client.post(
                "/deepseek_chat", json={"message": "x" * (MAX_CHAT_MESSAGE_CHARS + 1)}
            )
        self.assertEqual(response.status_code, 400)

        response = self.client.post(
            "/deepseek_chat",
            data='{"message":"' + ("x" * MAX_JSON_BODY_BYTES) + '"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.get_json(), {"error": "Request body is too large"})

    def test_chat_rate_limit_rejects_before_model_invocation(self):
        with (
            patch.object(app_module, "rate_limit_allowed", return_value=False),
            patch.object(app_module, "generate_deepseek_response") as generate,
        ):
            response = self.client.post("/deepseek_chat", json={"message": "hello"})

        self.assertEqual(response.status_code, 429)
        generate.assert_not_called()

    def test_valid_chat_keeps_stream_contract(self):
        with (
            patch.object(app_module, "rate_limit_allowed", return_value=True),
            patch.object(
                app_module,
                "generate_deepseek_response",
                return_value=iter([b'{"text":"hello"}\n']),
            ),
        ):
            response = self.client.post("/deepseek_chat", json={"message": "hello"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'{"text":"hello"}\n')

    def test_chat_guide_uses_normalized_validated_fields(self):
        guide_prompt = SimpleNamespace(prompt="bounded guide prompt")
        with (
            patch.object(app_module, "rate_limit_allowed", return_value=True),
            patch.object(
                app_module, "build_chat_guide_prompt", return_value=guide_prompt
            ) as build_prompt,
            patch.object(
                app_module,
                "generate_deepseek_response",
                return_value=iter([b'{"text":"hello"}\n']),
            ) as generate,
        ):
            response = self.client.post(
                "/deepseek_chat",
                json={
                    "message": "  hello  ",
                    "guideMode": " public_site ",
                    "presetId": " who_is_renda ",
                    "locale": " zh-CN ",
                },
            )

        self.assertEqual(response.status_code, 200)
        build_prompt.assert_called_once_with(
            "hello", preset_id="who_is_renda", locale="zh-CN"
        )
        self.assertEqual(
            generate.call_args.args[0][-1],
            {"role": "user", "content": "bounded guide prompt"},
        )

    def test_auth_routes_reject_non_object_and_wrong_type_payloads(self):
        cases = (
            ("/auth/register", '["value"]'),
            ("/auth/login", '{"identifier":[],"password":"value"}'),
            ("/auth/password/forgot", '{"identifier":42}'),
            ("/auth/password/reset", '{"token":{},"password":"value"}'),
        )
        for path, body in cases:
            with self.subTest(path=path):
                response = self.client.post(
                    path, data=body, content_type="application/json"
                )
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.get_json()["ok"])

    def test_password_forgot_generates_a_fragment_reset_link(self):
        database_session = MagicMock()
        database_session.execute.return_value.scalars.return_value.first.return_value = SimpleNamespace(
            id=7, email="person@example.com"
        )

        @contextmanager
        def fake_get_session():
            yield database_session

        with (
            patch.object(app_auth, "_rate_limit", return_value=True),
            patch.object(app_auth, "get_session", fake_get_session),
            patch.object(app_auth.redis_client, "setex"),
            patch.object(app_auth, "DEBUG_RETURN_RESET_TOKEN", False),
            patch("mailer.send_reset_email") as send_reset_email,
        ):
            response = self.client.post(
                "/auth/password/forgot", json={"identifier": "person@example.com"}
            )

        self.assertEqual(response.status_code, 200)
        reset_link = send_reset_email.call_args.args[1]
        self.assertIn("/reset_password#token=", reset_link)
        self.assertNotIn("?token=", reset_link)

    def test_redis_clients_have_read_and_connect_timeouts(self):
        for redis_client in (
            app_module.app.config["SESSION_REDIS"],
            app_auth.redis_client,
        ):
            options = redis_client.connection_pool.connection_kwargs
            self.assertEqual(options["socket_timeout"], app_module.REDIS_TIMEOUT)
            self.assertEqual(
                options["socket_connect_timeout"], app_module.REDIS_TIMEOUT
            )
            self.assertFalse(options.get("retry_on_timeout", False))

    def test_model_client_has_explicit_timeout_and_retry_budget(self):
        model_client = MagicMock()
        model_client.chat.completions.create.return_value = []
        with patch.object(
            app_module.openai, "OpenAI", return_value=model_client
        ) as client_factory:
            self.assertEqual(
                list(
                    app_module.generate_deepseek_response(
                        [{"role": "user", "content": "hello"}]
                    )
                ),
                [],
            )

        client_factory.assert_called_once_with(
            api_key="unit-test-model-key",
            base_url=app_module.DEEPSEEK_BASE_URL,
            timeout=app_module.DEEPSEEK_TIMEOUT_SECONDS,
            max_retries=1,
        )


if __name__ == "__main__":
    unittest.main()
