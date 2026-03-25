from hub.hub import Hub


def main():
    hub = Hub()
    try:
        hub.run()
    except KeyboardInterrupt:
        hub.request_stop()
        hub.shutdown()


if __name__ == "__main__":
    main()