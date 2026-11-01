"""
Плагин KYB_import_coords — точка входа QGIS.
"""

import os

from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import QCoreApplication

try:
    from qgis.PyQt.QtGui import QAction
except ImportError:
    from qgis.PyQt.QtWidgets import QAction

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QToolBar

from .dialog import ImportDialog
from .i18n import install_translator, remove_translator

TOOLBAR_NAME = "KYB_TOOLS"


def _log_ignored_exception(e, context=""):
    msg = f"Проигнорирована ошибка {context}: {type(e).__name__} - {e}"
    QgsMessageLog.logMessage(msg, "KYB_import_coords", Qgis.MessageLevel.Warning)


def _tr(text):
    return QCoreApplication.translate("plugin", text)


class ImportCoordsPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.toolbar = None
        self._translator = None
        self._menu_name = None

    def initGui(self):
        # --- Переводы ---
        self._translator = install_translator(os.path.dirname(__file__))

        icon_path = os.path.join(os.path.dirname(__file__), "icon.png")

        action_text = _tr("Импорт данных")
        self.action = QAction(QIcon(icon_path), action_text, self.iface.mainWindow())
        self.action.setObjectName("KYB_import_coords_action")
        self.action.setToolTip(_tr("Импорт и проверка пространственных данных"))
        self.action.triggered.connect(self.run)

        self.toolbar = self._find_toolbar(TOOLBAR_NAME)
        if self.toolbar is None:
            self.toolbar = QToolBar(TOOLBAR_NAME, self.iface.mainWindow())
            self.toolbar.setObjectName(TOOLBAR_NAME)
            self.toolbar.setWindowTitle(TOOLBAR_NAME)
            self.iface.mainWindow().addToolBar(self.toolbar)

        self.toolbar.addAction(self.action)

        # Сохраняем переведённое имя меню — оно нужно для unload
        self._menu_name = _tr("&Импорт данных")
        self.iface.addPluginToMenu(self._menu_name, self.action)

    def unload(self):
        if self.toolbar is not None and self.action is not None:
            self.toolbar.removeAction(self.action)

        if self._menu_name:
            self.iface.removePluginMenu(self._menu_name, self.action)

        if self.toolbar is not None:
            try:
                if not self.toolbar.actions():
                    self.toolbar.setVisible(False)
            except Exception as e:  # noqa: BLE001
                _log_ignored_exception(e, "при скрытии пустой панели KYB_TOOLS")

        remove_translator(self._translator)
        self._translator = None

    def _find_toolbar(self, name):
        try:
            mw = self.iface.mainWindow()
            for tb in mw.findChildren(QToolBar):
                if tb.objectName() == name or tb.windowTitle() == name:
                    return tb
        except Exception as e:  # noqa: BLE001
            _log_ignored_exception(e, f"при поиске панели '{name}'")
        return None

    def run(self):
        dlg = ImportDialog(self.iface)
        dlg.exec()
