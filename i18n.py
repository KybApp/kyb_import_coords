"""Загрузка переводов плагина KYB_import_coords.

Подход: НЕ устанавливаем QTranslator глобально через
QCoreApplication.installTranslator (это ломает UI QGIS 4 / Qt6 —
пропадают все стандартные надписи). Вместо этого храним переводчик
в модульной переменной _active_translator и переводим строки через
собственную функцию tr(context, text).

Приоритет загрузки:
    1. plugin_XX.qm — если есть (быстрее);
    2. plugin_XX.ts — если .qm нет, парсим XML сами;
    3. ничего — работает русский (язык оригинала).
"""

import os
import re

from qgis.core import QgsSettings
from qgis.PyQt.QtCore import QLocale, QTranslator

try:
    from defusedxml import ElementTree as ET

    _DEFUSED = True
except ImportError:
    import xml.etree.ElementTree as ET  # nosec B405

    _DEFUSED = False


_active_translator = None


def _app_locale():
    """Возвращает локаль, выбранную в настройках QGIS."""
    s = QgsSettings()
    val = s.value("locale/userLocale", "", type=str)
    if val:
        return val
    return QLocale.system().name()


class _TsTranslator(QTranslator):
    """Транслятор, читающий .ts (XML) напрямую — без lrelease."""

    def __init__(self):
        super().__init__()
        self._data = {}

    def translate(self, context, source, disambiguation=None, n=-1):
        return self._data.get((context, source), "")

    def isEmpty(self):
        return not self._data

    def load_ts(self, path):
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except OSError:
            return False

        # Защита от XML-бомб и внешних сущностей. defusedxml
        # проверяет сам. Fallback: отклоняем файлы с DOCTYPE/ENTITY
        # вручную (QGIS .ts их не использует).
        if not _DEFUSED and re.search(r"<!DOCTYPE|<!ENTITY", content, re.IGNORECASE):
            return False

        try:
            # Безопасно: content уже проверен выше на DOCTYPE/ENTITY
            # (если defusedxml не установлен). С defusedxml — ET уже
            # безопасная замена. Сканер: проверка вручную, # nosec.
            root = ET.fromstring(content)  # nosec B314
        except ET.ParseError:
            return False

        for ctx_el in root.findall("context"):
            name_el = ctx_el.find("name")
            if name_el is None or not name_el.text:
                continue
            ctx = name_el.text
            for msg in ctx_el.findall("message"):
                src_el = msg.find("source")
                tr_el = msg.find("translation")
                if src_el is None or tr_el is None or not src_el.text:
                    continue
                if tr_el.get("type", "") == "unfinished":
                    continue
                tr_text = tr_el.text or ""
                if not tr_text:
                    continue
                self._data[(ctx, src_el.text)] = tr_text
        return bool(self._data)


def install_translator(plugin_dir):
    """Загружает перевод для текущей локали QGIS.

    НЕ устанавливает глобально через QCoreApplication.installTranslator.
    Сохраняет переводчик в модульной переменной _active_translator.
    Перевод работает только через tr().

    Возвращает загруженный QTranslator или None.
    """
    global _active_translator
    _active_translator = None

    locale = _app_locale()
    lang = locale.split("_")[0] if "_" in locale else locale
    if not lang or lang == "ru":
        return None

    # 1. Пробуем .qm (быстро, нативно)
    qm_path = os.path.join(plugin_dir, "i18n", f"plugin_{lang}.qm")
    if os.path.isfile(qm_path):
        translator = QTranslator()
        if translator.load(qm_path):
            _active_translator = translator
            return translator

    # 2. Откатываемся к .ts (парсим XML сами)
    ts_path = os.path.join(plugin_dir, "i18n", f"plugin_{lang}.ts")
    if os.path.isfile(ts_path):
        translator = _TsTranslator()
        if translator.load_ts(ts_path):
            _active_translator = translator
            return translator

    return None


def unload_translator():
    """Сбрасывает активный переводчик."""
    global _active_translator
    _active_translator = None


def tr(context, text):
    """Переводит строку через активный переводчик.

    Порядок аргументов — как у QCoreApplication.translate:
    сначала контекст, потом текст.

    Если переводчика нет или строки нет в словаре — возвращает
    оригинал (text).
    """
    if _active_translator is not None:
        translated = _active_translator.translate(context, text)
        if translated:
            return translated
    return text
