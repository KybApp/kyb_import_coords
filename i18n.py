"""Загрузка переводов плагина KYB_import_coords.

Приоритет:
    1. plugin_XX.qm — если есть (быстрее, ~1ms);
    2. plugin_XX.ts — если .qm нет, парсим XML сами (~30ms);
    3. ничего — работает русский (язык оригинала).
"""

import os
import xml.etree.ElementTree as ET

from qgis.core import QgsSettings
from qgis.PyQt.QtCore import QCoreApplication, QLocale, QTranslator


def _app_locale():
    """Возвращает локаль, выбранную в настройках QGIS."""
    s = QgsSettings()
    val = s.value("locale/userLocale", "", type=str)
    if val:
        return val
    return QLocale.system().name()


class _TsTranslator(QTranslator):
    """Транслятор, читающий .ts (XML) напрямую — без lrelease.

    Qt при вызове QCoreApplication.translate(context, source) обходит
    все установленные трансляторы и берёт первый, вернувший непустую
    строку. Наш translate() возвращает "" для отсутствующих пар —
    тогда Qt переходит к следующему или к source.
    """

    def __init__(self):
        super().__init__()
        self._data = {}

    def translate(self, context, source, disambiguation=None, n=-1):
        return self._data.get((context, source), "")

    def isEmpty(self):
        return not self._data

    def load_ts(self, path):
        try:
            tree = ET.parse(path)
        except (ET.ParseError, OSError):
            return False
        root = tree.getroot()
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
    """Устанавливает переводчик для текущей локали QGIS.

    Параметры:
        plugin_dir — путь к папке плагина (где лежит i18n/).

    Возвращает QTranslator или None, если перевода нет.
    """
    locale = _app_locale()
    lang = locale.split("_")[0] if "_" in locale else locale
    if not lang or lang == "ru":
        return None

    # 1. Пробуем .qm (быстро, нативно)
    qm_path = os.path.join(plugin_dir, "i18n", f"plugin_{lang}.qm")
    if os.path.isfile(qm_path):
        translator = QTranslator()
        if translator.load(qm_path):
            QCoreApplication.installTranslator(translator)
            return translator

    # 2. Откатываемся к .ts (парсим XML сами)
    ts_path = os.path.join(plugin_dir, "i18n", f"plugin_{lang}.ts")
    if os.path.isfile(ts_path):
        translator = _TsTranslator()
        if translator.load_ts(ts_path):
            QCoreApplication.installTranslator(translator)
            return translator

    return None


def remove_translator(translator):
    """Снимает переводчик, если он был установлен."""
    if translator is None:
        return
    QCoreApplication.removeTranslator(translator)
