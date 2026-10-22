import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "client"))
sys.modules.pop("config", None)

from client.auth import AuthSession
sys.modules.pop("config", None)


class ClientAuthTests(unittest.TestCase):
    @patch("client.auth.requests.post")
    def test_login_uses_environment_credentials(self, post: Mock) -> None:
        post.return_value = Mock(status_code=200, json=lambda: {"access_token": "token"})
        with patch.dict(
            os.environ,
            {"DFSHA_USERNAME": "alice", "DFSHA_PASSWORD": "secret"},
            clear=False,
        ):
            AuthSession().login()

        self.assertEqual(
            post.call_args.kwargs["json"],
            {"username": "alice", "password": "secret"},
        )

    @patch("client.auth.session_file")
    @patch("client.auth.requests.post")
    def test_login_persists_token_without_password(
        self, post: Mock, session_path: Mock
    ) -> None:
        post.return_value = Mock(status_code=200, json=lambda: {"access_token": "token"})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            session_path.return_value = str(path)
            AuthSession().login("alice", "secret")
            saved = path.read_text(encoding="utf-8")

        self.assertIn("token", saved)
        self.assertNotIn("secret", saved)

    @patch("client.auth.getpass.getpass", return_value="secret")
    @patch("client.auth.input", return_value="alice")
    def test_credentials_confirm_password(self, input_mock: Mock, getpass_mock: Mock) -> None:
        self.assertEqual(
            AuthSession.credentials(confirm=True),
            ("alice", "secret"),
        )

    @patch("client.auth.getpass.getpass", return_value="hidden")
    @patch("client.auth.input", return_value="alice")
    @patch("client.auth.requests.post")
    def test_login_prompts_when_credentials_are_not_configured(
        self,
        post: Mock,
        input_mock: Mock,
        getpass_mock: Mock,
    ) -> None:
        post.return_value = Mock(status_code=200, json=lambda: {"access_token": "token"})
        with patch.dict(
            os.environ,
            {"DFSHA_USERNAME": "", "DFSHA_PASSWORD": ""},
            clear=False,
        ):
            AuthSession().login()

        input_mock.assert_called_once()
        getpass_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
