from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from agentic_hub.catalog.worker_registry import WorkerRegistry
from agentic_hub.core.openai_conversation_agent import OpenAIConversationAgent
from agentic_hub.core.runtime_model_store import RuntimeModelStore
from agentic_hub.models.telegram_conversation import TelegramConversationMessage, TelegramConversationSession
from agentic_hub.models.telegram_managed_bot import TelegramManagedBot
from agentic_hub.models.worker_instance import WorkerInstance
from agentic_hub.services.telegram.client import TelegramClient
from agentic_hub.services.telegram.service import TelegramPollingService


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TelegramRuntimeManager:
    def __init__(
        self,
        *,
        hub,
        worker_registry: WorkerRegistry,
        service_manager,
        runtime_dir: Path,
        env_path: Path,
        skill_library=None,
    ) -> None:
        self.hub = hub
        self.worker_registry = worker_registry
        self.service_manager = service_manager
        self.env_path = env_path
        self.managed_bot_store = RuntimeModelStore(runtime_dir / "managed_telegram_bots.json", TelegramManagedBot)
        self.session_store = RuntimeModelStore(runtime_dir / "telegram_conversation_sessions.json", TelegramConversationSession)
        self.conversation_agent = OpenAIConversationAgent(worker_registry, skill_library=skill_library)

    def load_managed_bots(self) -> list[TelegramManagedBot]:
        return self.managed_bot_store.load()

    def list_managed_bots(self) -> list[TelegramManagedBot]:
        return self.load_managed_bots()

    def get_managed_bot(self, worker_id: str) -> TelegramManagedBot:
        for record in self.load_managed_bots():
            if record.worker_id == worker_id:
                return record
        raise KeyError(f"Unknown managed bot for worker_id: {worker_id}")

    def attach_managed_bot(self, worker_id: str, bot_token: str) -> TelegramManagedBot:
        worker = self.worker_registry.get_worker(worker_id)
        self._require_interface_mode(worker, "managed")

        existing = self.load_managed_bots()
        if any(record.bot_token == bot_token and record.worker_id != worker_id for record in existing):
            raise ValueError("Telegram bot token already assigned to another worker")

        client = TelegramClient(bot_token)
        bot_info = client.get_me()
        result = bot_info.get("result", {}) if isinstance(bot_info, dict) else {}
        username = result.get("username")
        display_name = result.get("first_name") or worker.name
        if not username:
            raise ValueError("Telegram bot token is valid but missing username")

        record = TelegramManagedBot(
            worker_id=worker_id,
            bot_token=bot_token,
            bot_username=username,
            bot_display_name=display_name,
            enabled=True,
            allowed_user_ids=sorted(self._control_allowed_user_ids()),
            updated_at=utc_now(),
        )
        updated = [item for item in existing if item.worker_id != worker_id]
        updated.append(record)
        self.managed_bot_store.save(updated)
        self._persist_bot_token(worker_id, bot_token)
        self.register_managed_bot(record, start=True)
        return record

    def remove_managed_bot(self, worker_id: str) -> None:
        records = self.load_managed_bots()
        remaining = [record for record in records if record.worker_id != worker_id]
        if len(remaining) == len(records):
            raise KeyError(f"Unknown managed bot for worker_id: {worker_id}")
        service_name = self.service_name_for_worker(worker_id)
        if service_name in self.service_manager._services:
            self.service_manager.stop(service_name)
            self.service_manager.unregister(service_name)
        self.managed_bot_store.save(remaining)
        self._remove_persisted_bot_token(worker_id)

    def register_persisted_managed_bots(self) -> None:
        for record in self.load_managed_bots():
            self.register_managed_bot(record, start=record.enabled)

    def register_managed_bot(self, record: TelegramManagedBot, *, start: bool) -> None:
        service_name = self.service_name_for_worker(record.worker_id)
        service = TelegramPollingService(
            hub=self.hub,
            bot_token=record.bot_token,
            allowed_user_ids=set(record.allowed_user_ids),
            allowed_chat_ids=set(record.allowed_chat_ids),
            mode="managed",
            worker_id=record.worker_id,
            bot_username=record.bot_username,
        )
        self.service_manager.register(
            service_name,
            service,
            metadata={"transport": "telegram", "worker_id": record.worker_id, "mode": "managed"},
        )
        if start:
            self.service_manager.start(service_name)

    def start_managed_bot(self, worker_id: str) -> dict:
        record = self.get_managed_bot(worker_id)
        self._set_managed_bot_enabled(worker_id, True)
        self.register_managed_bot(record, start=False)
        return self.service_manager.start(self.service_name_for_worker(worker_id))

    def stop_managed_bot(self, worker_id: str) -> dict:
        self._set_managed_bot_enabled(worker_id, False)
        return self.service_manager.stop(self.service_name_for_worker(worker_id))

    def inspect_managed_bot(self, worker_id: str) -> dict:
        record = self.get_managed_bot(worker_id)
        service_name = self.service_name_for_worker(worker_id)
        status = self.service_manager.status(service_name) if service_name in self.service_manager._services else None
        return {
            "worker_id": record.worker_id,
            "bot_username": record.bot_username,
            "bot_display_name": record.bot_display_name,
            "enabled": record.enabled,
            "service": status,
        }

    def handle_managed_message(self, worker_id: str, chat_id: int, user_id: int | None, text: str) -> str:
        return self.handle_managed_message_in_thread(
            worker_id=worker_id,
            chat_id=chat_id,
            message_thread_id=None,
            user_id=user_id,
            text=text,
        )

    def handle_managed_message_in_thread(
        self,
        *,
        worker_id: str,
        chat_id: int,
        message_thread_id: int | None,
        user_id: int | None,
        text: str,
    ) -> str:
        worker = self.worker_registry.get_worker(worker_id)
        self._require_interface_mode(worker, "managed")
        session = self._find_session("managed_bot", worker_id, chat_id, message_thread_id)
        if session is None:
            session = TelegramConversationSession(
                session_id=str(uuid4()),
                worker_id=worker_id,
                channel_type="managed_bot",
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                user_id=user_id,
            )
            sessions = self.session_store.load()
            sessions.append(session)
            self.session_store.save(sessions)
        return self._reply_in_session(session, text)

    def service_name_for_worker(self, worker_id: str) -> str:
        return f"telegram_worker_{worker_id}"

    def allow_managed_chat(self, worker_id: str, chat_id: int) -> TelegramManagedBot:
        records = self.load_managed_bots()
        updated_record: TelegramManagedBot | None = None
        for record in records:
            if record.worker_id != worker_id:
                continue
            if chat_id not in record.allowed_chat_ids:
                record.allowed_chat_ids.append(chat_id)
                record.updated_at = utc_now()
            updated_record = record
            break
        if updated_record is None:
            raise KeyError(f"Unknown managed bot for worker_id: {worker_id}")
        self.managed_bot_store.save(records)

        service_name = self.service_name_for_worker(worker_id)
        service_record = self.service_manager._services.get(service_name)
        if service_record is not None:
            service_record.service.allowed_chat_ids = set(updated_record.allowed_chat_ids)
        return updated_record

    def _reply_in_session(self, session: TelegramConversationSession, text: str) -> str:
        worker = self.worker_registry.get_worker(session.worker_id)
        if worker.interface_mode == "internal":
            raise ValueError(f"Worker {worker.worker_id} is internal and cannot be messaged from Telegram")

        reply = self.conversation_agent.generate_reply(
            worker,
            session.messages,
            text,
            channel_type=session.channel_type,
        )
        sessions = self.session_store.load()
        for existing in sessions:
            if existing.session_id != session.session_id:
                continue
            existing.messages.append(TelegramConversationMessage(role="user", content=text))
            existing.messages.append(TelegramConversationMessage(role="assistant", content=reply))
            existing.updated_at = utc_now()
            break
        else:
            session.messages.append(TelegramConversationMessage(role="user", content=text))
            session.messages.append(TelegramConversationMessage(role="assistant", content=reply))
            session.updated_at = utc_now()
            sessions.append(session)
        self.session_store.save(sessions)
        return reply

    def _find_session(
        self,
        channel_type: str,
        worker_id: str,
        chat_id: int,
        message_thread_id: int | None = None,
    ) -> TelegramConversationSession | None:
        for session in self.session_store.load():
            if (
                session.channel_type == channel_type
                and session.worker_id == worker_id
                and session.chat_id == chat_id
                and session.message_thread_id == message_thread_id
                and session.active
            ):
                return session
        return None

    def _save_session(self, target: TelegramConversationSession) -> None:
        sessions = self.session_store.load()
        updated = []
        replaced = False
        for session in sessions:
            if session.session_id == target.session_id:
                updated.append(target)
                replaced = True
            else:
                updated.append(session)
        if not replaced:
            updated.append(target)
        self.session_store.save(updated)

    def _persist_bot_token(self, worker_id: str, token: str) -> None:
        key = f"TELEGRAM_WORKER_BOT_{worker_id.upper()}_TOKEN"
        lines: list[str] = []
        if self.env_path.exists():
            lines = self.env_path.read_text(encoding="utf-8").splitlines()
        updated = []
        replaced = False
        for line in lines:
            if line.startswith(f"{key}="):
                updated.append(f"{key}={token}")
                replaced = True
            else:
                updated.append(line)
        if not replaced:
            updated.append(f"{key}={token}")
        self.env_path.write_text("\n".join(updated).strip() + "\n", encoding="utf-8")

    def _remove_persisted_bot_token(self, worker_id: str) -> None:
        key = f"TELEGRAM_WORKER_BOT_{worker_id.upper()}_TOKEN"
        if not self.env_path.exists():
            return
        lines = self.env_path.read_text(encoding="utf-8").splitlines()
        updated = [line for line in lines if not line.startswith(f"{key}=")]
        if updated:
            self.env_path.write_text("\n".join(updated).strip() + "\n", encoding="utf-8")
        else:
            self.env_path.write_text("", encoding="utf-8")

    def _control_allowed_user_ids(self) -> set[int]:
        control = self.service_manager._services.get("telegram")
        if control is None:
            return set()
        service_status = control.service.status()
        return set(service_status.get("allowed_user_ids", []))

    def _require_interface_mode(self, worker: WorkerInstance, required: str) -> None:
        if worker.interface_mode != required:
            raise ValueError(f"Worker {worker.worker_id} must be `{required}` to use this Telegram flow")

    def _set_managed_bot_enabled(self, worker_id: str, enabled: bool) -> None:
        records = self.load_managed_bots()
        updated = []
        for record in records:
            if record.worker_id == worker_id:
                record.enabled = enabled
                record.updated_at = utc_now()
            updated.append(record)
        self.managed_bot_store.save(updated)
