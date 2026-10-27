"""SnowRunner Exporter - точка входа: python main.py"""

import logging
import sys

from paths import DATA_DIR


def _report(text: str) -> None:
    """Консоли в собранном .exe нет, поэтому ошибку показываем окном."""
    if sys.stderr:
        print(text, file=sys.stderr)
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "SnowRunner Exporter", 0x10)
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    log_file = DATA_DIR / "exporter.log"
    try:
        handlers = [logging.FileHandler(log_file, mode="w", encoding="utf-8")]
    except OSError:
        handlers = [logging.NullHandler()]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )
    try:
        import app_identity
        app_identity.ensure_icon()
        app_identity.set_process_app_id()      # до создания окна: своя кнопка в панели задач и свой значок
        import gui
    except ImportError as exc:
        _report(f"Не хватает библиотек / Missing libraries: {exc}\nУстановите / Install: pip install -r requirements.txt")
        return 1
    gui.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
