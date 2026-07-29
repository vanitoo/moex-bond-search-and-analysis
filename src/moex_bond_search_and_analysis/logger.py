import logging
import sys


def _configure_stdout_utf8() -> None:
    """Переключает текстовый stdout на UTF-8, если поток это поддерживает."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


class Logger:
    def __init__(self, name: str, format: str, store: bool = True):
        self.log = self.__get_logger(name, format)
        self.messages = [] if store else None

    def __get_logger(self, name: str, format: str) -> logging.Logger:
        _configure_stdout_utf8()
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(format)
        handler.setFormatter(formatter)

        log = logging.getLogger(name)
        log.setLevel(logging.INFO)
        log.propagate = False
        log.handlers.clear()
        log.addHandler(handler)
        return log

    def info(self, message: str):
        if self.messages is not None:
            if message.startswith("\n"):
                self.messages.append("")
            self.messages.append(message)
            if message.endswith("\n"):
                self.messages.append("")

        self.log.info(message)


# main_log = Logger(name="main", format="%(asctime)s - %(levelname)s - %(message)s", store=True)
like_print_log = Logger(name="main", format="%(message)s", store=True)
# empty_log = Logger(name="empty", format="", store=False)
