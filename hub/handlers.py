def startup_task(payload):
    return {"message": "hub started"}


def interval_task(payload):
    return {"message": "interval ran"}