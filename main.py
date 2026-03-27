import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

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
