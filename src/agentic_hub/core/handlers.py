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