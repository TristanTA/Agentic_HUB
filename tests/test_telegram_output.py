from __future__ import annotations

from hub.outputs.telegram import TelegramOutputAdapter


def test_telegram_output_chunks_large_messages():
    adapter = TelegramOutputAdapter(enabled=True, max_message_length=10)

    chunks = adapter._chunk_text("12345\n67890\nABCDE")

    assert len(chunks) >= 2
    assert all(len(chunk) <= 10 for chunk in chunks)
