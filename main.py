from dotenv import load_dotenv

from hub.hub import Hub


def main():
    hub = Hub()
    try:
        hub.run()
    except KeyboardInterrupt:
        hub.request_stop()

if __name__ == "__main__":
    load_dotenv()
    main()