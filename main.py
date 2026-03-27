from dotenv import load_dotenv

from agentic_hub.core.hub import Hub


def main() -> None:
    load_dotenv()
    hub = Hub()
    try:
        hub.run()
    except KeyboardInterrupt:
        hub.request_stop()


if __name__ == "__main__":
    main()
