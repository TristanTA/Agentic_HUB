def startup_task(payload):
    return {"message": "hub started"}


def start_service_task(payload, hub):
    service_name = payload.get("service_name")
    if not service_name:
        raise ValueError("Missing service_name")

    result = hub.service_manager.start(service_name)

    if result.get("ok"):
        return result

    raise RuntimeError(result.get("error") or result.get("message") or "Unknown service start failure")


def interval_task(payload):
    return {"message": "interval ran"}


def send_scheduled_telegram_reminder(payload, hub):
    from agentic_hub.services.telegram.client import TelegramClient

    worker_id = payload.get("worker_id")
    chat_id = payload.get("chat_id")
    text = payload.get("text")
    if worker_id is None or chat_id is None or not text:
        raise ValueError("Scheduled reminder payload requires worker_id, chat_id, and text")

    bot_token = None
    try:
        bot_token = hub.telegram_runtime_manager.get_managed_bot(str(worker_id)).bot_token
    except KeyError:
        service_record = hub.service_manager._services.get("telegram")
        if service_record is not None:
            bot_token = getattr(service_record.service, "bot_token", None)
    if not bot_token:
        raise RuntimeError("No Telegram bot token is available for scheduled reminder delivery")

    client = TelegramClient(bot_token)
    return client.send_message(int(chat_id), str(text), message_thread_id=payload.get("message_thread_id"))
