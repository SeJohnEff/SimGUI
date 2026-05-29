from unittest.mock import MagicMock

from managers.card_manager import CardManager


class TestWorkerStateInit:
    def test_worker_client_is_none(self):
        assert CardManager()._worker_client is None

    def test_session_id_is_none(self):
        assert CardManager()._current_session_id is None

    def test_card_gen_is_none(self):
        assert CardManager()._current_card_gen is None


class TestSetWorkerClient:
    def test_stores_client(self):
        cm = CardManager()
        client = MagicMock()
        cm.set_worker_client(client)
        assert cm._worker_client is client

    def test_replaces_client(self):
        cm = CardManager()
        cm.set_worker_client(MagicMock())
        second = MagicMock()
        cm.set_worker_client(second)
        assert cm._worker_client is second


class TestSetWorkerSession:
    def test_stores_session(self):
        cm = CardManager()
        cm.set_worker_session("abc123", 7)
        assert cm._current_session_id == "abc123"
        assert cm._current_card_gen == 7

    def test_clears_session(self):
        cm = CardManager()
        cm.set_worker_session("abc123", 7)
        cm.set_worker_session(None, None)
        assert cm._current_session_id is None
        assert cm._current_card_gen is None
