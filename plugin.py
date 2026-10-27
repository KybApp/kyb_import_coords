# -*- coding: utf-8 -*-
"""
Плагин KYB_import_coords — точка входа QGIS.

Отвечает за:
    • создание QAction — кнопки запуска плагина;
    • размещение кнопки на собственной панели KYB_TOOLS;
    • пункт меню «Плагины → Импорт данных».

Панель KYB_TOOLS — общая для всех инструментов серии KYB.
Если она уже существует (например, другой плагин её создал) —
плагин добавит кнопку в неё, а не создаст дубликат.
"""

import os

# QAction: в Qt5 (QGIS 3.x) живёт в QtWidgets, в Qt6 (QGIS 4.x) — в QtGui.
# Пробуем оба варианта, чтобы работало и там, и там.
try:
    from qgis.PyQt.QtGui import QAction
except ImportError:
    from qgis.PyQt.QtWidgets import QAction

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QToolBar

from .dialog import ImportDialog


# Имя панели инструментов, к которой прикрепляется кнопка.
# Общее для всех инструментов серии KYB — так они собираются
# в одном месте, а не разбросаны по панелям QGIS.
TOOLBAR_NAME = 'KYB_TOOLS'

# Пункт меню «Плагины».
MENU_NAME = '&Импорт данных'

# Подпись кнопки.
ACTION_TEXT = 'Импорт данных'


class ImportCoordsPlugin:
    """Плагин QGIS: создаёт кнопку, держит ссылки на неё и панель."""

    def __init__(self, iface):
        """Сохраняет ссылку на интерфейс QGIS.

        Параметры:
            iface — QgisInterface. Используется для доступа к главному
                    окну, меню и панелям инструментов.
        """
        self.iface = iface
        self.action = None
        self.toolbar = None

    def initGui(self):
        """Вызывается QGIS при загрузке плагина.

        Создаёт QAction, панель KYB_TOOLS (если ещё не создана),
        добавляет кнопку на панель и пункт в меню «Плагины».
        """
        icon_path = os.path.join(os.path.dirname(__file__), 'icon.png')

        self.action = QAction(QIcon(icon_path), ACTION_TEXT,
                              self.iface.mainWindow())
        self.action.setObjectName('KYB_import_coords_action')
        self.action.setToolTip('Импорт и проверка пространственных данных')
        self.action.triggered.connect(self.run)

        # --- Панель KYB_TOOLS ---
        # Ищем среди существующих панелей. Если нет — создаём.
        self.toolbar = self._find_toolbar(TOOLBAR_NAME)
        if self.toolbar is None:
            self.toolbar = QToolBar(TOOLBAR_NAME, self.iface.mainWindow())
            # objectName нужен для сохранения/восстановления раскладки
            # QGIS при перезапуске и для поиска панели из других плагинов.
            self.toolbar.setObjectName(TOOLBAR_NAME)
            self.toolbar.setWindowTitle(TOOLBAR_NAME)
            self.iface.mainWindow().addToolBar(self.toolbar)

        self.toolbar.addAction(self.action)

        # --- Пункт в меню «Плагины» ---
        self.iface.addPluginToMenu(MENU_NAME, self.action)

    def unload(self):
        """Вызывается QGIS при выгрузке плагина.

        Убирает кнопку с панели и пункт из меню. Саму панель
        не удаляет — в ней могут быть инструменты других
        плагинов серии KYB. Если панель осталась пуста — прячем.
        """
        if self.toolbar is not None and self.action is not None:
            self.toolbar.removeAction(self.action)

        self.iface.removePluginMenu(MENU_NAME, self.action)

        # Если после удаления кнопки на панели ничего не осталось —
        # скрываем её, чтобы не мозолила глаза пустой полоской.
        if self.toolbar is not None:
            try:
                if not self.toolbar.actions():
                    self.toolbar.setVisible(False)
            except Exception:
                pass

    def _find_toolbar(self, name):
        """Ищет панель с данным именем среди панелей главного окна.

        Сначала — по objectName (его QGIS сохраняет между сессиями),
        затем — по windowTitle (то, что видит пользователь).

        Параметры:
            name — имя панели, например 'KYB_TOOLS'.

        Возвращает QToolBar или None, если панель не найдена.
        """
        try:
            mw = self.iface.mainWindow()
            for tb in mw.findChildren(QToolBar):
                if tb.objectName() == name or tb.windowTitle() == name:
                    return tb
        except Exception:
            pass
        return None

    def run(self):
        """Открывает диалог импорта.

        exec() в Qt6, exec_() в Qt5 — обёртка на hasattr, чтобы
        работать и в QGIS 3.x, и в 4.x.
        """
        dlg = ImportDialog(self.iface)
        if hasattr(dlg, 'exec_'):
            dlg.exec_()
        else:
            dlg.exec()