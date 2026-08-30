import os
import unittest
from unittest.mock import patch

from flask import Flask, request

from security_policy import (
    RequestValidationError,
    build_reset_link,
    chat_history_bytes,
    rate_limit_allowed,
    require_json_object,
    required_env,
    required_https_origin,
    string_field,
    trim_chat_history,
    trusted_client_ip,
    trusted_hosts_from_env,
)


class FakeRedis:
    def __init__(self):
        self.counts = {}

    def eval(self, _script, _num_keys, key, _window_seconds):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]


class ConfigurationPolicyTests(unittest.TestCase):
    def test_required_env_fails_closed_for_missing_and_forbidden_values(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "FLASK_SECRET_KEY"):
                required_env("FLASK_SECRET_KEY", min_length=16)

        with patch.dict(
            os.environ, {"FLASK_SECRET_KEY": "default-secret-key"}, clear=True
        ):
            with self.assertRaisesRegex(RuntimeError, "FLASK_SECRET_KEY"):
                required_env(
                    "FLASK_SECRET_KEY",
                    min_length=16,
                    forbidden_values=("default-secret-key",),
                )

    def test_required_https_origin_rejects_non_origins(self):
        with patch.dict(
            os.environ,
            {"FRONTEND_BASE_URL": "https://www.rendazhang.com/"},
            clear=True,
        ):
            self.assertEqual(
                required_https_origin("FRONTEND_BASE_URL"),
                "https://www.rendazhang.com",
            )

        for invalid in (
            "http://www.rendazhang.com",
            "https://user@example.com",
            "https://www.rendazhang.com/reset_password",
            "https://www.rendazhang.com?token=value",
        ):
            with self.subTest(invalid=invalid), patch.dict(
                os.environ, {"FRONTEND_BASE_URL": invalid}, clear=True
            ):
                with self.assertRaisesRegex(RuntimeError, "HTTPS origin"):
                    required_https_origin("FRONTEND_BASE_URL")

    def test_trusted_hosts_use_a_narrow_default_and_validate_overrides(self):
        with patch.dict(os.environ, {}, clear=True):
            hosts = trusted_hosts_from_env()
        self.assertIn("www.rendazhang.com", hosts)
        self.assertIn("127.0.0.1", hosts)
        self.assertNotIn("*", hosts)

        with patch.dict(
            os.environ, {"TRUSTED_HOSTS": "www.rendazhang.com,localhost"}, clear=True
        ):
            self.assertEqual(
                trusted_hosts_from_env(), ["www.rendazhang.com", "localhost"]
            )

        with patch.dict(
            os.environ, {"TRUSTED_HOSTS": "https://example.com"}, clear=True
        ):
            with self.assertRaisesRegex(RuntimeError, "invalid host"):
                trusted_hosts_from_env()


class RequestPolicyTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def test_json_payload_must_be_an_object(self):
        with self.app.test_request_context(
            "/", method="POST", data='["value"]', content_type="application/json"
        ):
            with self.assertRaises(RequestValidationError):
                require_json_object(request)

        with self.app.test_request_context(
            "/", method="POST", data="not-json", content_type="application/json"
        ):
            with self.assertRaises(RequestValidationError):
                require_json_object(request)

    def test_string_fields_reject_wrong_types_and_lengths(self):
        with self.assertRaisesRegex(RequestValidationError, "message must be a string"):
            string_field({"message": 42}, "message", max_length=10)
        with self.assertRaisesRegex(RequestValidationError, "message is too long"):
            string_field({"message": "x" * 11}, "message", max_length=10)
        self.assertEqual(
            string_field(
                {"message": "  hello  "}, "message", max_length=10, strip=True
            ),
            "hello",
        )

    def test_forwarded_identity_is_trusted_only_from_one_loopback_hop(self):
        self.assertEqual(trusted_client_ip("127.0.0.1", "203.0.113.8"), "203.0.113.8")
        self.assertEqual(
            trusted_client_ip("198.51.100.9", "203.0.113.8"), "198.51.100.9"
        )
        self.assertEqual(
            trusted_client_ip("127.0.0.1", "203.0.113.8, 198.51.100.9"),
            "127.0.0.1",
        )
        self.assertEqual(trusted_client_ip("127.0.0.1", "invalid"), "127.0.0.1")

    def test_rate_limit_uses_a_bounded_counter(self):
        redis_client = FakeRedis()
        self.assertTrue(rate_limit_allowed(redis_client, "rl:test", 2, 60))
        self.assertTrue(rate_limit_allowed(redis_client, "rl:test", 2, 60))
        self.assertFalse(rate_limit_allowed(redis_client, "rl:test", 2, 60))

    def test_chat_history_keeps_complete_recent_rounds_and_byte_budget(self):
        messages = [{"role": "system", "content": "system"}]
        for index in range(4):
            messages.extend(
                [
                    {"role": "user", "content": f"question-{index}"},
                    {"role": "assistant", "content": f"answer-{index}"},
                ]
            )

        trimmed = trim_chat_history(messages, max_rounds=2, max_bytes=10_000)
        self.assertEqual(
            [message["content"] for message in trimmed],
            ["system", "question-2", "answer-2", "question-3", "answer-3"],
        )

        byte_trimmed = trim_chat_history(messages, max_rounds=4, max_bytes=150)
        self.assertLessEqual(chat_history_bytes(byte_trimmed), 150)
        self.assertEqual(byte_trimmed[0]["role"], "system")
        self.assertEqual(byte_trimmed[-1]["content"], "answer-3")

    def test_reset_link_uses_a_non_request_fragment(self):
        link = build_reset_link("https://www.rendazhang.com", "token/value")
        self.assertEqual(
            link,
            "https://www.rendazhang.com/reset_password#token=token%2Fvalue",
        )
        self.assertNotIn("?token=", link)


if __name__ == "__main__":
    unittest.main()
