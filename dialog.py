# KYB_import_coords — плагин импорта пространственных данных для QGIS.
# Copyright (C) 2026 Шершавин Д.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

# -*- coding: utf-8 -*-
"""
Диалог импорта координат в QGIS.

Главное окно плагина: загрузка данных из файла/буфера, автоопределение
формата координат и разделителя, предпросмотр в таблице и на карте,
сборка векторных слоёв и сохранение в GeoPackage.

Совместимость: QGIS 3.28+ и 4.x. Qt5 и Qt6 отличаются путями
к некоторым константам — все такие места собраны в блоке
совместимости ниже.
"""

import csv
import math
import os
import re
from collections import Counter

from qgis.PyQt.QtCore import QRectF, Qt
from qgis.PyQt.QtGui import QBrush, QColor, QFont, QPainter, QPen

# ---------- Qt: виджеты и утилиты ----------
from qgis.PyQt.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# QVariant есть в PyQt5 (QGIS 3.x), но удалён в PyQt6 (QGIS 4.x).
# В PyQt6 эквивалент — QMetaType.Type.*.
try:
    from qgis.PyQt.QtCore import QVariant

    T_STRING = QVariant.String
    T_DOUBLE = QVariant.Double
    T_INT = QVariant.Int
except (ImportError, AttributeError):
    from qgis.PyQt.QtCore import QMetaType

    T_STRING = QMetaType.Type.QString
    T_DOUBLE = QMetaType.Type.Double
    T_INT = QMetaType.Type.Int

# ---------- QGIS: работа со слоями, геометрией, стилями ----------
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsFillSymbol,
    QgsGeometry,
    QgsMarkerSymbol,
    QgsMessageLog,
    QgsPalLayerSettings,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsSettings,
    QgsTextFormat,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
    QgsWkbTypes,
)
from qgis.gui import QgsMapCanvas, QgsProjectionSelectionWidget, QgsRubberBand

# ---------- Qt-константы (scoped enums, PyQt5 5.15+ / PyQt6) ----------
_QPAINTER_ANTIALIASING = QPainter.RenderHint.Antialiasing
_QT_HORIZONTAL = Qt.Orientation.Horizontal
_QT_VERTICAL = Qt.Orientation.Vertical
_QT_CUSTOM_CONTEXT_MENU = Qt.ContextMenuPolicy.CustomContextMenu
_QT_ALIGN_LEFT_BOTTOM = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom
_QT_ALIGN_LEFT_TOP = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
_QT_COLOR_ALPHA = QColorDialog.ColorDialogOption.ShowAlphaChannel

_QT_BTN_OK = QDialogButtonBox.StandardButton.Ok
_QT_BTN_CANCEL = QDialogButtonBox.StandardButton.Cancel
_QT_BTN_ROLE_RESET = QDialogButtonBox.ButtonRole.ResetRole
_QT_ITEM_EDITABLE = Qt.ItemFlag.ItemIsEditable

# ---------- QGIS-константы (scoped enums, QGIS 3.28+ / 4.x) ----------
_QgsWkbTypesType_Point = QgsWkbTypes.Type.Point
_QgsWkbTypesType_LineString = QgsWkbTypes.Type.LineString
_QgsWkbTypesType_Polygon = QgsWkbTypes.Type.Polygon
_QgsWkbTypesType_MultiPolygon = QgsWkbTypes.Type.MultiPolygon

_QgsWkbTypesGeom_Point = QgsWkbTypes.GeometryType.PointGeometry
_QgsWkbTypesGeom_Line = QgsWkbTypes.GeometryType.LineGeometry
_QgsWkbTypesGeom_Polygon = QgsWkbTypes.GeometryType.PolygonGeometry

_QMessageBox_Yes = QMessageBox.StandardButton.Yes
_QMessageBox_No = QMessageBox.StandardButton.No

_QgsVectorFileWriter_Action = (
    QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
)
_QgsVectorFileWriter_Error = QgsVectorFileWriter.WriterError.NoError

_QColor_HexArgb = QColor.NameFormat.HexArgb

# ============================================================
# КОНСТАНТЫ
# ============================================================

DELIMS = {
    "авто": None,
    "таб": "\t",
    "запятая": ",",
    "точка с запятой": ";",
    "пробел": " ",
}

ENCODINGS = ["UTF-8", "CP1251", "UTF-16"]
GEOMS = ["Точка", "Линия", "Полигон", "Многоконтурный полигон"]
ORDERS = ["Широта, Долгота", "Долгота, Широта"]
AXES = ["Север, Восток", "Восток, Север"]
POLY_STYLES = ["Контур", "Заливка", "Контур + заливка"]

GEOM_URI = {
    "Точка": "Point",
    "Линия": "LineString",
    "Полигон": "Polygon",
    "Многоконтурный полигон": "MultiPolygon",
}
GEOM_WKB = {
    "Точка": _QgsWkbTypesType_Point,
    "Линия": _QgsWkbTypesType_LineString,
    "Полигон": _QgsWkbTypesType_Polygon,
    "Многоконтурный полигон": _QgsWkbTypesType_MultiPolygon,
}

HMS_RE = re.compile(
    r'^(-?\d+(?:[.,]\d+)?)°(\d+(?:[.,]\d+)?)[\'′](\d+(?:[.,]\d+)?)["″]$'
)

FMT_DECIMAL = "decimal"
FMT_HMS_ONE = "hms_one"
FMT_HMS_THREE = "hms_three"

FMT_LABELS = {
    FMT_DECIMAL: "Десятичные",
    FMT_HMS_ONE: "ГМС в одной колонке",
    FMT_HMS_THREE: "ГМС в трёх колонках",
}

HMS_EXAMPLE = "55°43'28.05\"  или  55\t43\t28.05"

# В Qt5 (QGIS 3.x) — QComboBox.AdjustToContents.
# В Qt6 (QGIS 4.x) — QComboBox.SizeAdjustPolicy.AdjustToContents.
# Пробуем новый путь, при неудаче — старый.
COL_COMBO_POLICY = QComboBox.SizeAdjustPolicy.AdjustToContents
COL_COMBO_MIN_CHARS = 12

NUM_MIN = 2
NUM_RATIO_MIN = 0.4

# Сколько вершин показывать от каждого объекта.
# Остальные сворачиваются в строку «... ещё N скрыто ...».
MAX_VERTICES_PER_OBJECT = 80

SETTINGS_PREFIX = "KYB_import_coords/"

# Стиль красной рамки для полей с ошибкой. Держим в одном месте,
# чтобы визуально все проблемные поля выглядели одинаково.
ERROR_STYLE_QLE = "QLineEdit { border: 2px solid #cc0000; background: #fff5f5; }"
ERROR_STYLE_FRAME = (
    "QFrame#crs_frame { border: 2px solid #cc0000; border-radius: 3px; }"
)


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================


def _num(s):
    """Приводит строку к float.

    Принимает запятую как десятичный разделитель.
    Возвращает None, если значение не является числом.

    Пример:
        _num("55,72") -> 55.72
        _num("abc")   -> None
    """
    if s is None:
        return None
    s = str(s).strip().replace(",", ".")
    if not s:
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _is_num_or_hms(c):
    """Проверяет, похоже ли значение на число или на ГМС."""
    c = str(c).strip()
    if not c:
        return False
    if _num(c) is not None:
        return True
    v, _ = parse_hms_one(c)
    return v is not None


def _hms_to_dec(d, mi, s):
    """Переводит градусы-минуты-секунды в десятичные градусы.

    Параметры:
        d  — целые градусы (отрицательные для W/S)
        mi — минуты (0..59.999)
        s  — секунды (0..59.999)

    Возвращает (значение, None) или (None, 'сообщение об ошибке').
    """
    if mi >= 60:
        return None, f"минуты = {mi} (должны быть < 60)"
    if s >= 60:
        return None, f"секунды = {s} (должны быть < 60)"
    sign = -1 if d < 0 else 1
    return sign * (abs(d) + mi / 60.0 + s / 3600.0), None


def parse_hms_one(text):
    """Разбирает ГМС в формате одной ячейки.

    Пример корректного значения: 55°43'28.05" или 55°43'28,05"
    Пробелы внутри ГМС не допускаются.
    """
    text = (text or "").strip()
    m = HMS_RE.match(text)
    if not m:
        return None, f"не похоже на ГМС. Пример: {HMS_EXAMPLE}"
    d = _num(m.group(1))
    mi = _num(m.group(2))
    s = _num(m.group(3))
    if d is None or mi is None or s is None:
        return None, "не число внутри ГМС"
    return _hms_to_dec(d, mi, s)


def _apply_polygon_style(
    layer, style_name, outline_color=None, outline_width=None, fill_color=None
):
    """Задаёт стиль полигона: контур, заливка или оба.

    Параметры:
        layer          — QgsVectorLayer с полигональной геометрией.
        style_name     — одна из строк POLY_STYLES.
        outline_color  — QColor обводки (или None — чёрный).
        outline_width  — толщина обводки в pt (или None — 0.5).
        fill_color     — QColor заливки (или None — серый 128).

    Значения по умолчанию рассчитаны на обычный вид в проекте,
    где стиль превью (ярко-красный) не нужен.
    """
    oc = outline_color or QColor(0, 0, 0, 255)
    ow = outline_width if outline_width is not None else 0.5
    fc = fill_color or QColor(150, 150, 150, 128)

    if style_name == "Контур":
        props = {
            "style": "no",
            "outline_style": "solid",
            "outline_color": oc.name(_QColor_HexArgb),
            "outline_width": str(ow),
        }
    elif style_name == "Заливка":
        props = {
            "style": "solid",
            "color": fc.name(_QColor_HexArgb),
            "outline_style": "no",
        }
    else:
        props = {
            "style": "solid",
            "color": fc.name(_QColor_HexArgb),
            "outline_style": "solid",
            "outline_color": oc.name(_QColor_HexArgb),
            "outline_width": str(ow),
        }

    symbol = QgsFillSymbol.createSimple(props)
    layer.renderer().setSymbol(symbol)
    layer.triggerRepaint()


def _enable_number_labels(layer, color="0,0,0,255", size=9):
    """Включает подписи по атрибуту 'num' на слое.

    Параметры:
        layer — QgsVectorLayer с полем 'num'
        color — цвет текста 'R,G,B,A'
        size  — размер шрифта в пунктах

    Обязательно вызываем setLabelsEnabled(True) после setLabeling —
    иначе в некоторых сборках QGIS подписи не отображаются.
    """
    settings = QgsPalLayerSettings()
    settings.fieldName = "num"
    settings.isExpression = False
    try:
        settings.enabled = True
    except Exception as e:  # noqa: BLE001 — слот не должен ронять плагин
        _log_ignored_exception(e, "некритичная ошибка")

    fmt = QgsTextFormat()
    fmt.setSize(size)
    try:
        fmt.setColor(QColor(color))
    except Exception as e:  # noqa: BLE001 — слот не должен ронять плагин
        _log_ignored_exception(e, "некритичная ошибка")
    settings.setFormat(fmt)

    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)
    layer.triggerRepaint()


def _extend(rect, bb):
    """Расширяет прямоугольник rect до охвата bb.

    Отдельная функция, потому что combineExtentWith мутирует объект,
    а в цикле по геометриям удобнее работать без мутации.
    """
    r = QgsRectangle(rect)
    r.combineExtentWith(bb)
    return r


def _geom_area_m2(geom, units):
    """Считает площадь геометрии в квадратных метрах.

    Параметры:
        geom  — QgsGeometry (полигон или мультиполигон)
        units — 'degrees' или 'meters'

    Логика:
        - для метровых СК — geom.area() уже в м²;
        - для градусных — переводим по Web Mercator: площадь
          в градусах² умножаем на (R·π/180)² и на cos(φ) центроида,
          компенсируя искажение проекции. Это приближение верно
          для небольших объектов (км-масштаб).

    Возвращает float в м² (0.0 при ошибке).
    """
    try:
        if units == "degrees":
            R = 6378137.0
            deg2m = R * math.pi / 180.0
            c = geom.centroid().asPoint()
            cos_lat = math.cos(math.radians(c.y()))
            return geom.area() * (deg2m**2) * cos_lat
        return geom.area()
    except (ValueError, TypeError, AttributeError, RuntimeError):
        return 0.0


def _geom_length_m(geom, units):
    """Считает длину/периметр геометрии в метрах.

    Параметры:
        geom  — QgsGeometry
        units — 'degrees' или 'meters'

    Логика:
        - для метровых СК — geom.length() уже в м;
        - для градусных — идём по сегментам, каждый переводим
          через R·cos(φ)·π/180 для долготы и R·π/180 для широты,
          складываем по теореме Пифагора.

    Возвращает float в м (0.0 при ошибке).
    """
    try:
        if units != "degrees":
            return geom.length()

        R = 6378137.0
        deg2m = R * math.pi / 180.0

        if geom.isMultipart():
            total = 0.0
            for part in geom.asGeometryCollection():
                total += _geom_length_m(part, units)
            return total

        pts = list(geom.vertices())
        total = 0.0
        for i in range(len(pts) - 1):
            p1, p2 = pts[i], pts[i + 1]
            lat_c = math.radians((p1.y() + p2.y()) / 2.0)
            dx = (p2.x() - p1.x()) * deg2m * math.cos(lat_c)
            dy = (p2.y() - p1.y()) * deg2m
            total += math.hypot(dx, dy)
        return total
    except (ValueError, TypeError, AttributeError, RuntimeError):
        return 0.0


def _log_ignored_exception(e, context=""):
    """Логирует ошибку, которую мы решили проигнорировать."""
    msg = f"Проигнорирована ошибка {context}: {type(e).__name__} - {e}"
    QgsMessageLog.logMessage(msg, "KYB_import_coords", Qgis.MessageLevel.Warning)


class ColorButton(QPushButton):
    """Кнопка для выбора цвета.

    Показывает текущий цвет квадратиком. По клику открывает
    QColorDialog с поддержкой альфа-канала. Хранит QColor и умеет
    отдавать его наружу.
    """

    def __init__(self, color, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self.setFixedSize(64, 24)
        self._update_style()
        self.clicked.connect(self._choose)

    def color(self):
        """Возвращает текущий QColor."""
        return QColor(self._color)

    def set_color(self, color):
        """Устанавливает QColor и обновляет вид кнопки."""
        self._color = QColor(color)
        self._update_style()

    def _update_style(self):
        r = self._color.red()
        g = self._color.green()
        b = self._color.blue()
        a = self._color.alpha()
        self.setStyleSheet(
            f"QPushButton {{ background-color: rgba({r},{g},{b},{a}); "
            f"border: 1px solid #888888; border-radius: 3px; }}"
        )
        self.setText("")

    def _choose(self):
        """Открывает QColorDialog и возвращает выбранный цвет.

        Важно: диалогу задаём родителя на уровне окна (self.window()),
        а не самой кнопки. Иначе ColorButton-стиль
        ('QPushButton { background-color: ... }') наследуется
        диалогом и красит все его кнопки в цвет кнопки-родителя.

        Дополнительно обнуляем stylesheet у самого диалога —
        на случай, если верхний QSS окна задаёт что-то для кнопок.
        """
        parent = self.window()
        dlg = QColorDialog(self._color, parent)
        dlg.setWindowTitle("Выбор цвета")
        dlg.setOption(_QT_COLOR_ALPHA, True)
        dlg.setStyleSheet("")  # снимаем унаследованный стиль

        if dlg.exec():
            self._color = dlg.currentColor()
            self._update_style()


class DisplaySettingsDialog(QDialog):
    """Диалог настроек отображения объектов на превью-карте.

    Пользователь настраивает цвета и размеры для:
        • точек (превью + spatial);
        • линий;
        • полигонов — контур, толщина, заливка;
        • подписей — цвет и размер текста номеров и площадей.

    Настройки сохраняются в QgsSettings с префиксом
    KYB_import_coords/display/ и восстанавливаются при следующем
    запуске. Диалог модальный — при закрытии изменения уже
    применены к превью-карте.

    Стиль полигона («Контур» / «Заливка» / «Контур + заливка»)
    задаётся отдельным комбобоксом и здесь не переопределяется —
    здесь только цвета и толщины.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки отображения")
        self.setMinimumWidth(440)
        self._build_ui()
        self._load_from_settings()

    def _build_ui(self):
        root = QVBoxLayout(self)

        # --- Точки ---
        gb_pt = QGroupBox("Точки")
        g_pt = QGridLayout(gb_pt)
        self.pt_color = ColorButton(QColor(230, 0, 0, 220))
        self.pt_size = QSpinBox()
        self.pt_size.setRange(1, 50)
        self.pt_size.setSuffix(" px")
        g_pt.addWidget(QLabel("Цвет:"), 0, 0)
        g_pt.addWidget(self.pt_color, 0, 1)
        g_pt.addWidget(QLabel("Размер:"), 1, 0)
        g_pt.addWidget(self.pt_size, 1, 1)
        root.addWidget(gb_pt)

        # --- Линии ---
        gb_ln = QGroupBox("Линии")
        g_ln = QGridLayout(gb_ln)
        self.ln_color = ColorButton(QColor(20, 160, 60, 255))
        self.ln_width = QSpinBox()
        self.ln_width.setRange(1, 20)
        self.ln_width.setSuffix(" px")
        g_ln.addWidget(QLabel("Цвет:"), 0, 0)
        g_ln.addWidget(self.ln_color, 0, 1)
        g_ln.addWidget(QLabel("Толщина:"), 1, 0)
        g_ln.addWidget(self.ln_width, 1, 1)
        root.addWidget(gb_ln)

        # --- Полигоны ---
        gb_pg = QGroupBox("Полигоны")
        g_pg = QGridLayout(gb_pg)
        self.pg_out_color = ColorButton(QColor(230, 0, 0, 220))
        self.pg_out_width = QSpinBox()
        self.pg_out_width.setRange(0, 20)
        self.pg_out_width.setSuffix(" px")
        self.pg_fill_color = ColorButton(QColor(230, 0, 0, 50))
        g_pg.addWidget(QLabel("Цвет контура:"), 0, 0)
        g_pg.addWidget(self.pg_out_color, 0, 1)
        g_pg.addWidget(QLabel("Толщина контура:"), 1, 0)
        g_pg.addWidget(self.pg_out_width, 1, 1)
        g_pg.addWidget(QLabel("Цвет заливки:"), 2, 0)
        g_pg.addWidget(self.pg_fill_color, 2, 1)
        root.addWidget(gb_pg)

        # --- Подписи ---
        gb_lb = QGroupBox("Подписи")
        g_lb = QGridLayout(gb_lb)
        self.lb_num_color = ColorButton(QColor(180, 0, 0, 255))
        self.lb_num_size = QSpinBox()
        self.lb_num_size.setRange(4, 30)
        self.lb_num_size.setSuffix(" pt")
        self.lb_area_color = ColorButton(QColor(0, 60, 160, 255))
        self.lb_area_size = QSpinBox()
        self.lb_area_size.setRange(4, 30)
        self.lb_area_size.setSuffix(" pt")
        g_lb.addWidget(QLabel("Цвет номеров:"), 0, 0)
        g_lb.addWidget(self.lb_num_color, 0, 1)
        g_lb.addWidget(QLabel("Размер номеров:"), 1, 0)
        g_lb.addWidget(self.lb_num_size, 1, 1)
        g_lb.addWidget(QLabel("Цвет площадей:"), 2, 0)
        g_lb.addWidget(self.lb_area_color, 2, 1)
        g_lb.addWidget(QLabel("Размер площадей:"), 3, 0)
        g_lb.addWidget(self.lb_area_size, 3, 1)
        root.addWidget(gb_lb)

        # --- Кнопки ---
        bb = QDialogButtonBox(_QT_BTN_OK | _QT_BTN_CANCEL)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        btn_reset = bb.addButton("Сбросить", _QT_BTN_ROLE_RESET)
        btn_reset.clicked.connect(self._reset_defaults)
        root.addWidget(bb)

    def _load_from_settings(self):
        """Читает настройки отображения из QgsSettings.

        Читает только цвета и размеры. Настройки формата координат
        и точности вынесены в отдельный диалог PrecisionSettingsDialog.
        """
        s = QgsSettings()
        pre = SETTINGS_PREFIX + "display/"

        def get_color(key, default):
            v = s.value(pre + key, "", type=str)
            if not v:
                return QColor(default)
            parts = v.split(",")
            if len(parts) != 4:
                return QColor(default)
            try:
                return QColor(
                    int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
                )
            except (ValueError, IndexError, TypeError):
                return QColor(default)

        # Дефолты: точки синие, линии зелёные, полигон — красный
        # контур с розовой полупрозрачной заливкой.
        self.pt_color.set_color(get_color("point_color", "#005adeff"))
        self.pt_size.setValue(s.value(pre + "point_size", 6, type=int))
        self.ln_color.set_color(get_color("line_color", "#14a03cff"))
        self.ln_width.setValue(s.value(pre + "line_width", 2, type=int))
        self.pg_out_color.set_color(get_color("poly_outline_color", "#e60000dc"))
        self.pg_out_width.setValue(s.value(pre + "poly_outline_width", 2, type=int))
        self.pg_fill_color.set_color(get_color("poly_fill_color", "#e6000032"))
        self.lb_num_color.set_color(get_color("num_label_color", "#b40000ff"))
        self.lb_num_size.setValue(s.value(pre + "num_label_size", 10, type=int))
        self.lb_area_color.set_color(get_color("area_label_color", "#003ca0ff"))
        self.lb_area_size.setValue(s.value(pre + "area_label_size", 10, type=int))

    def _reset_defaults(self):
        """Возвращает все значения к дефолтным.

        Дефолты соответствуют исходному виду превью до того,
        как пользователь что-либо менял: синие точки, зелёные
        линии, красный контур и розовая заливка полигонов.
        """
        self.pt_color.set_color(QColor(0, 90, 230, 255))
        self.pt_size.setValue(6)
        self.ln_color.set_color(QColor(20, 160, 60, 255))
        self.ln_width.setValue(2)
        self.pg_out_color.set_color(QColor(230, 0, 0, 220))
        self.pg_out_width.setValue(2)
        self.pg_fill_color.set_color(QColor(230, 0, 0, 50))
        self.lb_num_color.set_color(QColor(180, 0, 0, 255))
        self.lb_num_size.setValue(10)
        self.lb_area_color.set_color(QColor(0, 60, 160, 255))
        self.lb_area_size.setValue(10)

    @staticmethod
    def _color_to_str(c):
        return f"{c.red()},{c.green()},{c.blue()},{c.alpha()}"

    def accept(self):
        """Сохраняет настройки в QgsSettings и закрывает диалог."""
        s = QgsSettings()
        pre = SETTINGS_PREFIX + "display/"
        try:
            s.setValue(
                pre + "area_label_color", self._color_to_str(self.lb_area_color.color())
            )
            s.setValue(pre + "area_label_size", self.lb_area_size.value())
            s.setValue(pre + "line_color", self._color_to_str(self.ln_color.color()))
            s.setValue(pre + "line_width", self.ln_width.value())
            s.setValue(
                pre + "poly_outline_color",
                self._color_to_str(self.pg_out_color.color()),
            )
            s.setValue(pre + "poly_outline_width", self.pg_out_width.value())
            s.setValue(
                pre + "poly_fill_color", self._color_to_str(self.pg_fill_color.color())
            )
            s.setValue(
                pre + "num_label_color", self._color_to_str(self.lb_num_color.color())
            )
            s.setValue(pre + "num_label_size", self.lb_num_size.value())
            s.setValue(
                pre + "area_label_color", self._color_to_str(self.lb_area_color.color())
            )
            s.setValue(pre + "area_label_size", self.lb_area_size.value())
        except Exception as e:  # noqa: BLE001 — слот не должен ронять плагин
            _log_ignored_exception(e, "некритичная ошибка")
        super().accept()


# ============================================================
# ДИАЛОГ
# ============================================================
class PrecisionSettingsDialog(QDialog):
    """Диалог настроек формата и точности отображения координат.

    Отдельный от настроек цветов. Пользователь настраивает:
        • формат градусов — десятичные или ГГММСС;
        • точность десятичных градусов;
        • точность секунд в ГГММСС;
        • точность метров.

    Сохраняется в QgsSettings под префиксом KYB_import_coords/display/.
    Изменения применяются сразу после нажатия «OK».
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Формат и точность координат")
        self.setMinimumWidth(400)
        self._build_ui()
        self._load_from_settings()

    def _build_ui(self):
        root = QVBoxLayout(self)

        gb_fmt = QGroupBox("Формат координат")
        g_fmt = QGridLayout(gb_fmt)

        g_fmt.addWidget(QLabel("Широта/Долгота:"), 0, 0)
        self.coord_format = QComboBox()
        self.coord_format.addItems(["Десятичные", "ГГММСС"])
        self.coord_format.currentIndexChanged.connect(self._update_precision_enabled)
        g_fmt.addWidget(self.coord_format, 0, 1)

        g_fmt.addWidget(QLabel("Знаков после запятой (градусы):"), 1, 0)
        self.deg_precision = QSpinBox()
        self.deg_precision.setRange(1, 15)
        g_fmt.addWidget(self.deg_precision, 1, 1)

        g_fmt.addWidget(QLabel("Знаков после запятой (секунды):"), 2, 0)
        self.dms_seconds_precision = QSpinBox()
        self.dms_seconds_precision.setRange(1, 6)
        g_fmt.addWidget(self.dms_seconds_precision, 2, 1)

        g_fmt.addWidget(QLabel("Знаков после запятой (метры):"), 3, 0)
        self.meters_precision = QSpinBox()
        self.meters_precision.setRange(0, 6)
        g_fmt.addWidget(self.meters_precision, 3, 1)

        self.fmt_hint = QLabel(
            "Для прямоугольных координат (метры) формат ГГММСС не применяется."
        )
        self.fmt_hint.setObjectName("hint_label")
        self.fmt_hint.setWordWrap(True)
        g_fmt.addWidget(self.fmt_hint, 4, 0, 1, 2)

        root.addWidget(gb_fmt)

        bb = QDialogButtonBox(_QT_BTN_OK | _QT_BTN_CANCEL)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        btn_reset = bb.addButton("Сбросить", _QT_BTN_ROLE_RESET)
        btn_reset.clicked.connect(self._reset_defaults)
        root.addWidget(bb)

    def _update_precision_enabled(self):
        is_dms = self.coord_format.currentText() == "ГГММСС"
        self.dms_seconds_precision.setEnabled(is_dms)
        self.deg_precision.setEnabled(not is_dms)

    def _load_from_settings(self):
        s = QgsSettings()
        pre = SETTINGS_PREFIX + "display/"

        fmt = s.value(pre + "coord_format", "decimal", type=str)
        idx = self.coord_format.findText("ГГММСС" if fmt == "dms" else "Десятичные")
        if idx >= 0:
            self.coord_format.setCurrentIndex(idx)

        self.deg_precision.setValue(s.value(pre + "deg_precision", 8, type=int))
        self.dms_seconds_precision.setValue(
            s.value(pre + "dms_seconds_precision", 3, type=int)
        )
        self.meters_precision.setValue(s.value(pre + "meters_precision", 3, type=int))
        self._update_precision_enabled()

    def _reset_defaults(self):
        self.coord_format.setCurrentIndex(0)
        self.deg_precision.setValue(8)
        self.dms_seconds_precision.setValue(3)
        self.meters_precision.setValue(3)
        self._update_precision_enabled()

    def accept(self):
        s = QgsSettings()
        pre = SETTINGS_PREFIX + "display/"
        try:
            fmt = "dms" if self.coord_format.currentText() == "ГГММСС" else "decimal"
            s.setValue(pre + "coord_format", fmt)
            s.setValue(pre + "deg_precision", self.deg_precision.value())
            s.setValue(
                pre + "dms_seconds_precision", self.dms_seconds_precision.value()
            )
            s.setValue(pre + "meters_precision", self.meters_precision.value())
        except Exception as e:  # noqa: BLE001 — слот не должен ронять плагин
            _log_ignored_exception(e, "некритичная ошибка")
        super().accept()


class ScaleBarWidget(QWidget):
    """Простая масштабная линейка в стиле QGIS.

    Рисует полоску с 2 сегментами (тёмный + светлый) и подписями
    «0», «середина», «конец единица». Значения берёт у канвы при
    каждом пересчёте — метод update_scale().

    Ограничение: только метры и километры. Градусные канвы
    подписываются в метрах приблизительно (для географических СК
    это будет неточно, но приемлемо для ориентировки).
    """

    def __init__(self, canvas, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self._text = "0"
        self._mid = ""
        self._end = ""
        self.setFixedHeight(42)
        self.setMinimumWidth(160)
        self._temp_layer = None

    def update_scale(self):
        """Пересчитывает подписи по текущему масштабу канвы.

        Два режима:
        - проекционные СК (метры) — используем canvas.scale()
          и переводим в метры на пиксель через DPI;
        - географические СК (градусы) — считаем по Web Mercator,
        как в веб-картах: метры на градус долготы на широте φ
        равны R * cos(φ) * π/180, где R = 6378137.

        Подбор «круглой» длины и разбиение на два сегмента — общее
        для обоих режимов.
        """
        import math

        m_per_px = 0.0

        # Если у канвы ещё нет экстента (только что открыли плагин,
        # нет данных) — линейку не показываем вообще.
        try:
            ext = self.canvas.extent()
            if ext.isEmpty() or ext.width() == 0 or ext.height() == 0:
                self._text = self._mid = self._end = ""
                self.update()
                return
        except (AttributeError, RuntimeError):
            self._text = self._mid = self._end = ""
            self.update()
            return

        # --- Определяем тип СК канвы ---
        try:
            crs = self.canvas.mapSettings().destinationCrs()
        except (AttributeError, RuntimeError):
            crs = None

        is_geographic = crs is not None and crs.isGeographic()

        if is_geographic:
            # Web Mercator: пересчёт градусов в метры на широте центра.
            try:
                extent = self.canvas.extent()
                lat_c = extent.center().y()
                deg_per_px = self.canvas.mapUnitsPerPixel()

                # R — радиус Земли в Web Mercator (EPSG:3857).
                R = 6378137.0
                m_per_deg = R * math.cos(math.radians(lat_c)) * math.pi / 180.0
                m_per_px = deg_per_px * m_per_deg
            except (ValueError, TypeError, AttributeError, RuntimeError):
                m_per_px = 0.0
        else:
            # Проекционные СК — канва возвращает знаменатель масштаба.
            try:
                scale = self.canvas.scale()
            except (ValueError, TypeError, AttributeError, RuntimeError):
                scale = 0
            if scale and scale > 0:
                # 1 px ≈ scale / 3779 м (при 96 dpi).
                m_per_px = scale / 3779.0

        if not m_per_px or m_per_px <= 0:
            self._text = self._mid = self._end = ""
            self.update()
            return

        # Защита от мусорных значений при неинициализированной канве:
        # если на пиксель приходится больше 10 км — это явно ошибка,
        # а не реальный масштаб. Линейку не показываем.
        if m_per_px > 10000:
            self._text = self._mid = self._end = ""
            self.update()
            return

        # Ширина доступной полоски.
        width_px = max(self.width() - 12, 60)
        total_m = m_per_px * width_px

        # Округляем до «круглого» числа: 1, 2, 5 × 10^n.
        nice = _nice_round(total_m)
        self._total_m = nice

        if nice >= 1000:
            # nice — в метрах, а _fmt_km ждёт километры.
            # Делим на 1000 до вызова.
            km = nice / 1000.0
            self._text = "0"
            self._mid = _fmt_km(km / 2.0)
            self._end = _fmt_km(km) + " км"
        else:
            self._text = "0"
            self._mid = _fmt_m(nice / 2.0)
            self._end = _fmt_m(nice) + " м"

        self.update()

    def paintEvent(self, event):
        """Рисует полоску и подписи."""
        if not self._end:
            return

        p = QPainter(self)
        p.setRenderHint(_QPAINTER_ANTIALIASING)

        w = self.width()
        h = self.height()
        # Все размеры уменьшены вдвое — линейка компактнее.
        bar_y = h - 10
        bar_h = 3
        bar_x = 6
        # Справа оставляем запас под самую длинную подпись
        # («10 000 км»). 60 px хватает с избытком.
        bar_w = w - 66
        half_w = bar_w / 2.0

        # Полоски: левая — тёмная, правая — светлая.
        p.setPen(QPen(QColor(60, 60, 60), 1))
        p.setBrush(QBrush(QColor(60, 60, 60)))
        p.drawRect(QRectF(bar_x, bar_y, half_w, bar_h))

        p.setBrush(QBrush(QColor(255, 255, 255)))
        p.drawRect(QRectF(bar_x + half_w, bar_y, half_w, bar_h))

        # Вертикальные засечки по краям и в середине.
        p.setPen(QPen(QColor(60, 60, 60), 1))
        p.drawLine(int(bar_x), int(bar_y - 2), int(bar_x), int(bar_y + bar_h + 2))
        p.drawLine(
            int(bar_x + half_w),
            int(bar_y - 2),
            int(bar_x + half_w),
            int(bar_y + bar_h + 2),
        )
        p.drawLine(
            int(bar_x + bar_w),
            int(bar_y - 2),
            int(bar_x + bar_w),
            int(bar_y + bar_h + 2),
        )

        # Подписи.
        p.setPen(QPen(QColor(40, 40, 40), 1))
        font = QFont()
        font.setPointSize(8)
        p.setFont(font)

        fm = p.fontMetrics()
        text_y = bar_y - 8

        p.drawText(
            int(bar_x - fm.horizontalAdvance(self._text) / 2), int(text_y), self._text
        )
        p.drawText(
            int(bar_x + half_w - fm.horizontalAdvance(self._mid) / 2),
            int(text_y),
            self._mid,
        )
        p.drawText(
            int(bar_x + bar_w - fm.horizontalAdvance(self._end) / 2),
            int(text_y),
            self._end,
        )


def _nice_round(v):
    """Округляет число до «круглого»: 1, 2, 5 × 10^n."""
    if v <= 0:
        return 1
    import math

    exp = math.floor(math.log10(v))
    base = v / (10**exp)
    if base < 1.5:
        nice = 1
    elif base < 3.5:
        nice = 2
    elif base < 7.5:
        nice = 5
    else:
        nice = 10
    return nice * (10**exp)


def _fmt_m(v):
    """Форматирует метры с пробелами между разрядами.

    Пример:
        _fmt_m(500)     -> '500'
        _fmt_m(1500)    -> '1 500'
        _fmt_m(10000)   -> '10 000'
    """
    n = round(v)
    s = str(n)
    # Вставляем пробел каждые 3 цифры справа налево.
    parts = []
    while len(s) > 3:
        parts.insert(0, s[-3:])
        s = s[:-3]
    parts.insert(0, s)
    return " ".join(parts)


def _fmt_km(v):
    """Форматирует километры: 2, 2.5, 10, 100.

    Дробное значение оставляем с одной цифрой после запятой —
    для линейки больше не нужно.
    """
    if v == int(v):
        return _fmt_m(int(v))  # тот же формат с пробелами
    return f"{v:.1f}".replace(".", ",")


class ImportDialog(QDialog):
    """Главное окно плагина."""

    def __init__(self, iface):
        """Инициализация окна.

        Параметры:
            iface — QgisInterface. Нужен для доступа к главному окну
                    и строке состояния QGIS.
        """
        super().__init__(iface.mainWindow())
        self.iface = iface
        self.setWindowTitle("Импорт данных")
        self.resize(1240, 820)
        self.setAcceptDrops(True)

        # Состояние данных.
        self.blocks = []
        self.data_blocks = []
        self.rows = []
        self.headers = []
        self.detected_format = FMT_DECIMAL
        self._source_text = ""
        self._temp_layer = None
        self._saved_vnum_col = ""
        # Список временных слоёв превью (номера, площади). Живут
        # только пока открыто окно.
        self._preview_layers = []
        # Накопитель общей площади для индикатора в углу карты.
        self._total_area_m2 = 0.0

        # Пространственный вход (Shapefile / GeoJSON / KML).
        # Когда открыт такой файл, spatial_data заполняется списком:
        #   [{'name': 'Точки', 'wkb': _QgsWkbTypesType_Point,
        #     'layer': QgsVectorLayer, 'features': [...]}, ...]
        # Пустой список = работаем с текстовым входом.
        self.spatial_data = []
        self._is_spatial_input = False

        # Карта соответствия строк таблицы предпросмотра и данных.
        # Элемент — либо None (серая строка-разделитель между блоками),
        # либо (индекс_блока, индекс_строки) в self.data_blocks.
        self._preview_map = []

        # Была ли попытка импорта без имени слоя. Нужно, чтобы плашка
        # имени не светилась с самого начала, а появлялась только когда
        # пользователь нажал «Импортировать» с пустым полем.
        self._name_warn_shown = False

        # Общая стилизация окна: карточки QGroupBox и жёлтые плашки.
        # Настройки отображения — цвета и размеры. Загружаются
        # из QgsSettings, могут быть изменены через диалог «⚙».
        # Используются и на превью-карте, и при импорте слоя.
        self.display_settings = {}
        self._load_display_settings()

        # Общая стилизация окна: карточки QGroupBox и жёлтые плашки.
        self.setStyleSheet(self._global_qss())

        self._build_ui()
        self._init_map_canvas()
        # Обновлять линейку при любом изменении экстента карты.
        self.map_canvas.extentsChanged.connect(self._update_scale_label)
        self._load_settings()
        self._update_options_visibility()
        self._update_axis_labels()
        self._connect_column_signals()

    def _load_display_settings(self):
        """Читает настройки отображения из QgsSettings.

        Заполняет self.display_settings словарём QColor и int.
        Вызывается один раз при старте окна.
        """
        s = QgsSettings()
        pre = SETTINGS_PREFIX + "display/"

        def col(key, default):
            v = s.value(pre + key, "", type=str)
            if not v:
                return QColor(default)
            parts = v.split(",")
            if len(parts) != 4:
                return QColor(default)
            try:
                return QColor(
                    int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
                )
            except (ValueError, IndexError, TypeError):
                return QColor(default)

        # Дефолты — исходный вид превью: синие точки, зелёные линии,

        # красный контур полигона, розовая заливка.
        self.display_settings = {
            "point_color": col("point_color", "#005adeff"),
            "point_size": s.value(pre + "point_size", 6, type=int),
            "line_color": col("line_color", "#14a03cff"),
            "line_width": s.value(pre + "line_width", 2, type=int),
            "poly_outline_color": col("poly_outline_color", "#e60000dc"),
            "poly_outline_width": s.value(pre + "poly_outline_width", 2, type=int),
            "poly_fill_color": col("poly_fill_color", "#e6000032"),
            "num_label_color": col("num_label_color", "#b40000ff"),
            "num_label_size": s.value(pre + "num_label_size", 10, type=int),
            "area_label_color": col("area_label_color", "#003ca0ff"),
            "area_label_size": s.value(pre + "area_label_size", 10, type=int),
            # Формат координат и точность.
            "coord_format": s.value(pre + "coord_format", "decimal", type=str),
            "deg_precision": s.value(pre + "deg_precision", 8, type=int),
            "dms_seconds_precision": s.value(
                pre + "dms_seconds_precision", 3, type=int
            ),
            "meters_precision": s.value(pre + "meters_precision", 3, type=int),
        }

    def _open_display_dialog(self):
        """Открывает диалог настроек отображения.

        После закрытия перечитывает настройки, применяет новые
        цвета к превью-карте и перестраивает таблицу — чтобы
        формат координат (десятичный / ГГММСС) и точность
        отобразились сразу.
        """
        dlg = DisplaySettingsDialog(self)
        result = dlg.exec()
        if result:
            self._load_display_settings()
            self._init_map_canvas_colors()
            # Перестраиваем таблицу — формат координат мог поменяться.
            if self._is_spatial_input:
                self._fill_spatial_preview_table()
            elif self.rows:
                self._fill_preview()
            self._update_map_preview()

    def _open_precision_dialog(self):
        """Открывает диалог настроек формата и точности координат.

        После закрытия перечитывает настройки и перестраивает таблицу,
        чтобы новый формат (десятичный / ГГММСС) сразу отобразился.
        """
        dlg = PrecisionSettingsDialog(self)
        result = dlg.exec()
        if result:
            self._load_display_settings()
            if self._is_spatial_input:
                self._fill_spatial_preview_table()
            elif self.rows:
                self._fill_preview()

    def _init_map_canvas_colors(self):
        """Применяет текущие настройки к резиновым лентам превью.

        Отдельный метод — потому что вызывается и при старте,
        и после смены настроек.
        """
        ds = self.display_settings
        try:
            self.rb_point.setColor(ds["point_color"])
            self.rb_point.setWidth(ds["point_size"] // 3)  # шаг ~3 px
            self.rb_line.setColor(ds["line_color"])
            self.rb_line.setWidth(ds["line_width"])
            self.rb_vertex.setColor(QColor(0, 90, 230, 255))
            self.rb_vertex.setWidth(5)
            self.rb_vertex.setIconSize(6)
            self._apply_poly_preview_style()
        except Exception as e:  # noqa: BLE001 — слот не должен ронять плагин
            _log_ignored_exception(e, "некритичная ошибка")

    def _global_qss(self):
        """Возвращает таблицу стилей для окна.

        Стилизует:
            - QGroupBox — карточки с заголовками;
            - QLabel#warning_label — жёлтые inline-плашки.

        Всё остальное — на усмотрение темы QGIS.
        """
        return """
        QGroupBox {
            border: 1px solid #cfcfcf;
            border-radius: 6px;
            margin-top: 12px;
            padding: 6px 6px 6px 6px;
            font-weight: bold;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 12px;
            padding: 0 4px;
            color: #444444;
        }
        QLabel#warning_label {
            background-color: #fff3cd;
            border: 1px solid #ffeeba;
            border-radius: 4px;
            color: #856404;
            padding: 8px;
        }
        QLabel#hint_label {
            color: #666666;
            font-weight: normal;
        }
        """

    # --------------------------------------------------------
    # Drag & Drop
    # --------------------------------------------------------
    def dragEnterEvent(self, event):
        """Принимаем только перетаскивание файлов."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        """Берём первый URL из сброшенного файла и грузим его."""
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path:
                self._load_file(path)
        event.acceptProposedAction()

    # --------------------------------------------------------
    # Построение интерфейса
    # --------------------------------------------------------
    def _build_ui(self):
        """Собирает все виджеты окна."""
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ---------- Горизонтальный сплиттер: слева левая панель, справа превью ----------
        main_split = QSplitter(_QT_HORIZONTAL)

        # === Левая колонка (в QScrollArea) ===
        # === Правая колонка — карточки (без QScrollArea) ===
        # QScrollArea не сжимает содержимое ниже sizeHint — из-за этого
        # кнопки уходили за границу. Обычный QWidget сжимается вместе
        # с панелью, и всё влезает.
        left_scroll = QWidget()
        left_layout = QVBoxLayout(left_scroll)
        left_layout.setContentsMargins(0, 0, 6, 0)
        left_layout.setSpacing(10)

        left_layout.addWidget(self._block_source())
        left_layout.addWidget(self._block_structure())
        left_layout.addWidget(self._block_geometry())
        left_layout.addWidget(self._block_result())
        left_layout.addStretch(1)

        # === Правая колонка: вертикальный сплиттер таблица + карта ===
        right_split = QSplitter(_QT_VERTICAL)

        # Предпросмотр данных
        preview_block = QWidget()
        pb_layout = QVBoxLayout(preview_block)
        pb_layout.setContentsMargins(0, 0, 0, 0)
        pb_layout.addWidget(QLabel("Просмотр данных:"))
        self.preview = QTableWidget()
        self.preview.setContextMenuPolicy(_QT_CUSTOM_CONTEXT_MENU)
        self.preview.customContextMenuRequested.connect(self._on_preview_context_menu)
        # Ловим правку ячеек — иначе ввод в новую строку не попадал
        # в self.data_blocks и карта не перерисовывалась.
        self.preview.itemChanged.connect(self._on_preview_item_changed)
        pb_layout.addWidget(self.preview, 1)

        # Карта + масштабная линейка в левом нижнем углу.
        map_block = QWidget()
        mb_layout = QVBoxLayout(map_block)
        mb_layout.setContentsMargins(0, 0, 0, 0)
        mb_layout.addWidget(QLabel("Карта:"))

        canvas_holder = QWidget()
        grid = QGridLayout(canvas_holder)
        grid.setContentsMargins(0, 0, 0, 0)

        self.map_canvas = QgsMapCanvas()
        self.map_canvas.setMinimumSize(300, 200)
        grid.addWidget(self.map_canvas, 0, 0)

        self.scale_bar = ScaleBarWidget(self.map_canvas)
        grid.addWidget(self.scale_bar, 0, 0, _QT_ALIGN_LEFT_BOTTOM)

        # Индикатор общей площади — в левом верхнем углу карты.
        self.total_area_label = QLabel("")
        self.total_area_label.setStyleSheet(
            "background: rgba(255, 255, 255, 220); "
            "border: 1px solid #cccccc; border-radius: 3px; "
            "padding: 4px 8px; font-weight: bold; color: #222222;"
        )
        self.total_area_label.setVisible(False)
        grid.addWidget(self.total_area_label, 0, 0, _QT_ALIGN_LEFT_TOP)

        mb_layout.addWidget(canvas_holder, 1)

        right_split.addWidget(preview_block)
        right_split.addWidget(map_block)
        right_split.setStretchFactor(0, 3)
        right_split.setStretchFactor(1, 2)
        right_split.setSizes([400, 300])

        # Порядок: слева предпросмотр (таблица + карта), справа карточки.
        main_split.addWidget(right_split)  # превью — слева
        main_split.addWidget(left_scroll)  # карточки — справа
        # Растягивается только превью. Карточки держат свою ширину
        # и при сжатии окна не ужимаются первыми.
        main_split.setStretchFactor(0, 1)
        main_split.setStretchFactor(1, 0)
        right_split.setMinimumWidth(300)
        left_scroll.setMinimumWidth(520)
        main_split.setSizes([560, 720])

        root.addWidget(main_split, 1)

        # ---------- Нижние кнопки ----------
        row_btn = QHBoxLayout()
        self.btn_clear = QPushButton("Очистить данные")
        self.btn_clear.clicked.connect(self.on_clear)
        row_btn.addWidget(self.btn_clear)
        row_btn.addStretch(1)

        btn_ok = QPushButton("Импортировать")
        btn_ok.clicked.connect(self.on_import)
        row_btn.addWidget(btn_ok)

        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)
        row_btn.addWidget(btn_cancel)
        root.addLayout(row_btn)

    # --------------------------------------------------------
    # Блок «Источник данных»
    # --------------------------------------------------------
    def _block_source(self):
        """Файл, кнопка «Из буфера», выбор СК и плашка-предупреждение."""
        box = QGroupBox("Источник данных")
        lay = QVBoxLayout(box)

        # Файл: поле тянется по ширине, кнопки фиксированы.
        row_file = QHBoxLayout()
        row_file.addWidget(QLabel("Файл:"))
        self.file_edit = QLineEdit()
        self.file_edit.setAcceptDrops(False)
        self.file_edit.setPlaceholderText("Перетащите файл или нажмите «...»")
        self.file_edit.setMinimumWidth(80)
        row_file.addWidget(self.file_edit, 1)
        btn_browse = QPushButton("...")
        btn_browse.setFixedWidth(32)
        btn_browse.clicked.connect(self.on_browse)
        row_file.addWidget(btn_browse)
        btn_clip = QPushButton("Из буфера")
        btn_clip.setMinimumWidth(90)
        btn_clip.clicked.connect(self.on_clipboard)
        row_file.addWidget(btn_clip)
        lay.addLayout(row_file)

        # Исходная СК во фрейме для подсветки, растягивается по ширине.
        row_crs = QHBoxLayout()
        row_crs.addWidget(QLabel("Исходная СК:"))
        self.crs_frame = QFrame()
        self.crs_frame.setObjectName("crs_frame")
        f_layout = QHBoxLayout(self.crs_frame)
        f_layout.setContentsMargins(0, 0, 0, 0)
        self.crs_widget = QgsProjectionSelectionWidget()
        self.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
        self.crs_widget.setMinimumWidth(80)
        self.crs_widget.crsChanged.connect(self._on_crs_changed)
        f_layout.addWidget(self.crs_widget)
        row_crs.addWidget(self.crs_frame, 1)
        lay.addLayout(row_crs)

        # Inline-плашка про СК. Скрыта по умолчанию.
        self.crs_warning = QLabel("")
        self.crs_warning.setObjectName("warning_label")
        self.crs_warning.setWordWrap(True)
        self.crs_warning.setVisible(False)
        lay.addWidget(self.crs_warning)

        return box

    # --------------------------------------------------------
    # Блок «Структура»
    # --------------------------------------------------------
    def _block_structure(self):
        """Формат, заголовки, строки, кодировка, разделитель, порядок, координаты.

        Порядок блоков:
            1. Формат + Заголовки + Нач./Кон. строка.
            2. Кодировка + Разделитель + Порядок.
            3. Координаты (Коорд.1 / Коорд.2) — последними, потому что
               пользователь сначала видит параметры разбора, а потом
               уже привязку колонок.
        """
        box = QGroupBox("Структура")
        lay = QVBoxLayout(box)

        # --- 1. Формат + Заголовки + Нач./Кон. строка — одной строкой ---
        row_fmt = QHBoxLayout()
        self.format_label = QLabel("Формат: —")
        row_fmt.addWidget(self.format_label)

        row_fmt.addSpacing(15)
        self.headers_label = QLabel("Заголовки: —")
        self.headers_label.setObjectName("hint_label")
        row_fmt.addWidget(self.headers_label)

        row_fmt.addSpacing(10)
        self.start_label = QLabel("Нач. строка:")
        row_fmt.addWidget(self.start_label)
        self.start_line = QSpinBox()
        self.start_line.setMinimum(1)
        self.start_line.setValue(1)
        self.start_line.setMaximumWidth(70)
        self.start_line.valueChanged.connect(self._rebuild_from_raw)
        row_fmt.addWidget(self.start_line)

        row_fmt.addSpacing(10)
        self.end_label = QLabel("Кон. строка:")
        row_fmt.addWidget(self.end_label)
        self.end_line = QSpinBox()
        self.end_line.setMinimum(0)
        self.end_line.setValue(0)
        self.end_line.setMaximumWidth(70)
        self.end_line.valueChanged.connect(self._rebuild_from_raw)
        row_fmt.addWidget(self.end_line)
        self.end_hint_label = QLabel("(0 = до конца)")
        row_fmt.addWidget(self.end_hint_label)
        row_fmt.addStretch(1)

        # Кнопка-шестерёнка: настройки формата и точности координат.
        self.btn_precision = QPushButton("⚙")
        self.btn_precision.setFixedWidth(32)
        self.btn_precision.setToolTip("Формат и точность координат")
        self.btn_precision.clicked.connect(self._open_precision_dialog)
        row_fmt.addWidget(self.btn_precision)
        lay.addLayout(row_fmt)

        # --- 2. Кодировка + Разделитель + Порядок ---
        row_kd = QHBoxLayout()
        self.enc_label = QLabel("Кодировка:")
        row_kd.addWidget(self.enc_label)
        self.enc = QComboBox()
        self.enc.addItems(ENCODINGS)
        row_kd.addWidget(self.enc)

        row_kd.addSpacing(15)
        self.delim_label = QLabel("Разделитель:")
        row_kd.addWidget(self.delim_label)
        self.delim = QComboBox()
        self.delim.addItems(list(DELIMS.keys()))
        self.delim.currentIndexChanged.connect(self._reload_from_source)
        row_kd.addWidget(self.delim)

        row_kd.addSpacing(15)
        self.order_label = QLabel("Порядок:")
        row_kd.addWidget(self.order_label)
        self.order_combo = QComboBox()
        self.order_combo.addItems(ORDERS)
        self.order_combo.currentIndexChanged.connect(self._on_axes_changed)
        row_kd.addWidget(self.order_combo)

        # Оси — тот же смысл, что Порядок, но для метров.
        # Стоит рядом, чтобы переключатель не «прыгал» при смене СК.
        row_kd.addSpacing(15)
        self.axes_label = QLabel("Оси:")
        row_kd.addWidget(self.axes_label)
        self.axes_combo = QComboBox()
        self.axes_combo.addItems(AXES)
        self.axes_combo.currentIndexChanged.connect(self._on_axes_changed)
        row_kd.addWidget(self.axes_combo)

        row_kd.addStretch(1)
        lay.addLayout(row_kd)

        # --- 3. Координаты ---
        self.coord_stack = QStackedWidget()
        self.coord_stack.addWidget(self._page_decimal())
        self.coord_stack.addWidget(self._page_hms_one())
        self.coord_stack.addWidget(self._page_hms_three())
        lay.addWidget(self.coord_stack)

        # --- 3. Нумерация вершин ---
        row_vnum = QHBoxLayout()
        self.vnum_mode_label = QLabel("Нумерация вершин:")
        row_vnum.addWidget(self.vnum_mode_label)

        self.vnum_mode_combo = QComboBox()
        self.vnum_mode_combo.addItems(
            ["Авто (по объектам)", "Авто (сквозная)", "Из колонки"]
        )
        self.vnum_mode_combo.currentIndexChanged.connect(self._on_vnum_mode_changed)
        row_vnum.addWidget(self.vnum_mode_combo)

        self.vnum_col_label = QLabel("Колонка:")
        self.vnum_col_label.setVisible(False)
        row_vnum.addWidget(self.vnum_col_label)

        self.vnum_col_combo = QComboBox()
        self.vnum_col_combo.addItem("—")
        self.vnum_col_combo.setVisible(False)
        row_vnum.addWidget(self.vnum_col_combo)

        row_vnum.addStretch(1)
        lay.addLayout(row_vnum)

        self.vnum_warning = QLabel("")
        self.vnum_warning.setObjectName("warning_label")
        self.vnum_warning.setWordWrap(True)
        self.vnum_warning.setVisible(False)
        lay.addWidget(self.vnum_warning)

        return box

    # --------------------------------------------------------
    # Блок «Геометрия»
    # --------------------------------------------------------
    def _block_geometry(self):
        """Тип геометрии, стиль полигона, чекбоксы вершин и нумерации."""
        box = QGroupBox("Геометрия")
        lay = QVBoxLayout(box)

        row = QHBoxLayout()
        row.addWidget(QLabel("Геометрия:"))
        self.geom_combo = QComboBox()
        self.geom_combo.addItems(GEOMS)
        self.geom_combo.currentIndexChanged.connect(self._on_geom_changed)
        row.addWidget(self.geom_combo)

        row.addSpacing(15)
        self.poly_style_label = QLabel("Стиль:")
        row.addWidget(self.poly_style_label)
        self.poly_style = QComboBox()
        self.poly_style.addItems(POLY_STYLES)
        self.poly_style.currentIndexChanged.connect(self._on_preview_option_changed)
        row.addWidget(self.poly_style)

        # Распорка занимает всё свободное место,
        # прижимая шестерёнку к правому краю.
        row.addStretch(1)

        # Кнопка-шестерёнка — открывает диалог настроек отображения.
        self.btn_display = QPushButton("⚙")
        self.btn_display.setFixedWidth(32)
        self.btn_display.setToolTip("Настройки отображения")
        self.btn_display.clicked.connect(self._open_display_dialog)
        row.addWidget(self.btn_display)

        lay.addLayout(row)

        row2 = QHBoxLayout()
        self.cb_vertices = QCheckBox("Точки по углам")
        self.cb_vertices.stateChanged.connect(self._on_preview_option_changed)
        row2.addWidget(self.cb_vertices)

        row2.addSpacing(15)
        self.cb_numbering = QCheckBox("Нумерация точек и углов")
        self.cb_numbering.stateChanged.connect(self._on_preview_option_changed)
        row2.addWidget(self.cb_numbering)
        row2.addStretch(1)
        lay.addLayout(row2)

        return box

    # --------------------------------------------------------
    # Блок «Результат»
    # --------------------------------------------------------
    def _block_result(self):
        """Имя слоя и опция сохранения в GeoPackage + плашка про имя."""
        box = QGroupBox("Результат")
        lay = QVBoxLayout(box)

        row_name = QHBoxLayout()
        row_name.addWidget(QLabel("Имя слоя:"))
        self.layer_name_edit = QLineEdit()
        self.layer_name_edit.setPlaceholderText("Например: точки_съёмки")
        self.layer_name_edit.textChanged.connect(self._on_layer_name_changed)
        row_name.addWidget(self.layer_name_edit, 1)
        lay.addLayout(row_name)

        # Inline-плашка про имя. Скрыта по умолчанию.
        self.name_warning = QLabel("Введите имя слоя — без него импорт невозможен.")
        self.name_warning.setObjectName("warning_label")
        self.name_warning.setWordWrap(True)
        self.name_warning.setVisible(False)
        lay.addWidget(self.name_warning)

        row_save = QHBoxLayout()
        self.cb_save_file = QCheckBox("Сохранить в файл (GeoPackage):")
        row_save.addWidget(self.cb_save_file)
        row_save.addStretch(1)
        lay.addLayout(row_save)

        row_path = QHBoxLayout()
        self.save_path_edit = QLineEdit()
        self.save_path_edit.setPlaceholderText("Путь к .gpkg")
        self.save_path_edit.setMinimumWidth(80)
        row_path.addWidget(self.save_path_edit, 1)
        btn_save_browse = QPushButton("...")
        btn_save_browse.setFixedWidth(32)
        btn_save_browse.clicked.connect(self.on_browse_save)
        row_path.addWidget(btn_save_browse)
        lay.addLayout(row_path)

        return box

    def _connect_column_signals(self):
        """Подписывает выпадашки колонок на пересборку превью."""
        combos = [
            self.x_combo,
            self.y_combo,
            self.c1_combo,
            self.c2_combo,
            self.c1d,
            self.c1m,
            self.c1s,
            self.c2d,
            self.c2m,
            self.c2s,
            self.vnum_col_combo,
        ]
        for c in combos:
            c.currentIndexChanged.connect(self._on_column_changed)

    # --------------------------------------------------------
    # Обработчики интерфейса
    # --------------------------------------------------------
    def _on_column_changed(self):
        """Смена колонки → обновить таблицу и карту."""
        if not self.rows:
            return
        self._fill_preview()
        self._update_map_preview()

    def _on_vnum_mode_changed(self):
        """Показывает/прячет выбор колонки и обновляет таблицу."""
        mode = self.vnum_mode_combo.currentText()
        is_col = mode == "Из колонки"
        self.vnum_col_label.setVisible(is_col)
        self.vnum_col_combo.setVisible(is_col)
        self.vnum_warning.setVisible(False)
        if self.rows:
            self._fill_preview()
            self._update_map_preview()

    def _validate_vnum(self):
        """Проверяет выбранный режим нумерации вершин.

        Возвращает True, если всё в порядке, и False — если режим
        «Из колонки» выбран, но колонка не указана или содержит пустые
        значения. В этом случае показывает жёлтую плашку.
        """
        if self.vnum_mode_combo.currentText() != "Из колонки":
            self.vnum_warning.setVisible(False)
            return True

        col_idx = self._col_index(self.vnum_col_combo)
        if col_idx < 0:
            self.vnum_warning.setText(
                "Выбран режим «Из колонки», но колонка не указана."
            )
            self.vnum_warning.setVisible(True)
            return False

        empty_found = False
        for block in self.data_blocks:
            for row in block:
                val = self._cell(row, col_idx).strip()
                if not val:
                    empty_found = True
                    break
            if empty_found:
                break

        if empty_found:
            self.vnum_warning.setText(
                "В выбранной колонке есть пустые значения. "
                "Выберите другую колонку или режим."
            )
            self.vnum_warning.setVisible(True)
            return False

        self.vnum_warning.setVisible(False)
        return True

    def _get_vertex_number(self, row, local_vnum, global_vnum):
        """Возвращает строковый номер вершины по текущему режиму."""
        mode = self.vnum_mode_combo.currentText()
        if mode == "Авто (по объектам)":
            return str(local_vnum)
        elif mode == "Авто (сквозная)":
            return str(global_vnum)
        else:
            col_idx = self._col_index(self.vnum_col_combo)
            if col_idx >= 0:
                return self._cell(row, col_idx).strip()
            return ""

    def _on_preview_option_changed(self):
        """Переключение стиля/чекбоксов обновляет превью-карту."""
        self._update_map_preview()

    def _on_axes_changed(self):
        """Смена порядка осей → обновить подписи и перерисовать всё."""
        self._update_axis_labels()
        if not self.rows:
            return
        self._fill_preview()
        self._update_map_preview()

    def _on_geom_changed(self):
        """Смена типа геометрии → обновить видимость опций и превью."""
        self._update_options_visibility()
        self._update_map_preview()

    def _on_crs_changed(self):
        """Смена СК: убрать ошибку, обновить предупреждение, перерисовать."""
        self._clear_crs_error()
        try:
            self.map_canvas.setDestinationCrs(self.crs_widget.crs())
        except Exception as e:  # noqa: BLE001 — слот не должен ронять плагин
            _log_ignored_exception(e, "некритичная ошибка")
        self._update_crs_warning()
        self._update_map_preview()

    def _on_layer_name_changed(self):
        """Ввод в поле имени: убрать красную подсветку и жёлтую плашку."""
        self.layer_name_edit.setStyleSheet("")
        if self.layer_name_edit.text().strip():
            self.name_warning.setVisible(False)
            self._name_warn_shown = False

    def _clear_layer_name_error(self):
        """Снимает красную подсветку с поля имени слоя."""
        self.layer_name_edit.setStyleSheet("")

    def _clear_crs_error(self):
        """Снимает красную подсветку с блока выбора СК."""
        self.crs_frame.setStyleSheet("")

    # --------------------------------------------------------
    # Плашки-предупреждения (inline)
    # --------------------------------------------------------
    def _update_crs_warning(self):
        """Обновляет inline-плашку про СК.

        Плашка показывается, если данные и выбранная СК не согласованы
        по единицам: градусы против метровой СК или наоборот.
        Невалидную СК тут не подсвечиваем — её ловим при импорте.
        """
        if not self.rows:
            self.crs_warning.setVisible(False)
            return

        crs = self.crs_widget.crs()
        if not crs.isValid():
            self.crs_warning.setVisible(False)
            return

        units = self._current_units()
        mismatch = False
        if (
            units == "degrees"
            and not crs.isGeographic()
            or units == "meters"
            and crs.isGeographic()
        ):
            mismatch = True

        if mismatch:
            self.crs_warning.setText(
                "⚠ Внимание: данные и выбранная СК не согласованы по единицам.\n"
                "Возможно, выбрана неверная исходная СК. Проверьте выбор."
            )
            self.crs_warning.setVisible(True)
        else:
            self.crs_warning.setVisible(False)

    def _show_name_warning(self):
        """Показывает плашку про пустое имя слоя."""
        self.name_warning.setVisible(True)
        self._name_warn_shown = True

    # --------------------------------------------------------
    # Управление видимостью опций
    # --------------------------------------------------------
    def _update_options_visibility(self):
        """Прячет опции, не применимые к текущему входу.

        Для пространственного файла скрываем всё, что относится
        к разбору текста: разделитель, кодировку, строки, порядок,
        оси, координаты, тип геометрии. Оставляем только то, что
        имеет смысл: стиль полигона, точки по углам, нумерацию.
        """
        is_spatial = self._is_spatial_input

        # --- Прячем текстовые опции ---
        try:
            for w in (
                self.format_label,
                self.headers_label,
                self.start_label,
                self.start_line,
                self.end_label,
                self.end_line,
                self.end_hint_label,
                self.enc_label,
                self.enc,
                self.delim_label,
                self.delim,
                self.order_label,
                self.order_combo,
                self.axes_label,
                self.axes_combo,
                self.coord_stack,
                self.vnum_mode_label,
                self.vnum_mode_combo,
                self.vnum_col_label,
                self.vnum_col_combo,
                self.vnum_warning,
                self.btn_precision,
            ):
                if w is not None:
                    w.setVisible(not is_spatial)
        except Exception as e:  # noqa: BLE001 — слот не должен ронять плагин
            _log_ignored_exception(e, "некритичная ошибка")

        if not is_spatial:
            self._on_vnum_mode_changed()

        # --- Геометрия ---
        if is_spatial:
            # Тип геометрии определяется файлом, менять не даём.
            self.geom_combo.setEnabled(False)
        else:
            self.geom_combo.setEnabled(True)

        # --- Стиль и чекбоксы ---
        if is_spatial:
            has_poly = any(
                p["wkb"] == _QgsWkbTypesType_Polygon
                or p["wkb"] == _QgsWkbTypesType_MultiPolygon
                for p in self.spatial_data
            )
            self.poly_style_label.setVisible(has_poly)
            self.poly_style.setVisible(has_poly)
            self.cb_vertices.setVisible(True)
            self.cb_numbering.setVisible(True)
        else:
            geom = self.geom_combo.currentText()
            is_point = geom == "Точка"
            show_poly = geom in ("Полигон", "Многоконтурный полигон")
            self.poly_style_label.setVisible(show_poly)
            self.poly_style.setVisible(show_poly)
            self.cb_vertices.setVisible(not is_point)
            self.cb_numbering.setVisible(True)
            self._update_axis_visibility()

    def _update_axis_visibility(self):
        """Показывает только нужный переключатель порядка координат.

        Для градусов и ГМС — широта/долгота. Для метров — север/восток.
        """
        units = self._current_units()
        is_hms = self.detected_format in (FMT_HMS_ONE, FMT_HMS_THREE)

        show_order = is_hms or (units == "degrees")
        show_axes = (units == "meters") and (self.detected_format == FMT_DECIMAL)

        self.order_label.setVisible(show_order)
        self.order_combo.setVisible(show_order)
        self.axes_label.setVisible(show_axes)
        self.axes_combo.setVisible(show_axes)

    def _axis_labels(self):
        """Возвращает две подписи координат в порядке колонок."""
        units = self._current_units()
        if units == "degrees":
            if self.order_combo.currentText().startswith("Широта"):
                return ["Широта", "Долгота"]
            else:
                return ["Долгота", "Широта"]
        else:
            if self.axes_combo.currentText().startswith("Восток"):
                return ["Восток", "Север"]
            else:
                return ["Север", "Восток"]

    def _update_axis_labels(self):
        """Обновляет подписи всех полей координат.

        Для метров — «Север:» / «Восток:» или наоборот.
        Для градусов и ГМС — «Широта:» / «Долгота:» или наоборот.

        Обновляются сразу три страницы QStackedWidget — чтобы при
        переключении формата подписи были согласованы.
        """
        labels = self._axis_labels()
        # Десятичные (метры или градусы).
        self.x_label.setText(labels[0] + ":")
        self.y_label.setText(labels[1] + ":")
        # ГМС в одной колонке.
        self.c1_label.setText(labels[0] + ":")
        self.c2_label.setText(labels[1] + ":")
        # ГМС в трёх колонках.
        self.c1h_label.setText(labels[0] + ":")
        self.c2h_label.setText(labels[1] + ":")

    def _fmt_value(self, v):
        """Форматирует координату для показа в таблице.

        Зависит от единиц и настроек отображения:
            • градусы + «Десятичные» — deg_precision знаков;
            • градусы + «ГГММСС» — градусы°минуты'секунды.ссс";
            • метры — meters_precision знаков.

        Округление — только визуальное. В слой уходит полное
        значение исходной координаты.
        """
        ds = self.display_settings
        units = self._current_units()

        if units == "degrees":
            fmt = ds.get("coord_format", "decimal")
            if fmt == "dms":
                sec_prec = ds.get("dms_seconds_precision", 3)
                return self._to_dms(v, sec_prec)
            prec = ds.get("deg_precision", 8)
            return f"{v:.{prec}f}"

        prec = ds.get("meters_precision", 3)
        return f"{v:.{prec}f}"

    def _to_dms(self, v, sec_prec=3):
        """Переводит десятичные градусы в формат ГГ°ММ'СС.ссс".

        Параметры:
            v         — значение в градусах (может быть отрицательным).
            sec_prec  — число знаков после запятой у секунд.

        Возвращает строку. Пример при sec_prec=3:
            55.72445833  → 55°43'28.050"
            -0.5         → -0°30'00.000"

        Форматирование:
            • градусы — как есть (без ведущего нуля);
            • минуты — всегда 2 знака (02d);
            • секунды — всегда 2 знака до запятой + sec_prec после.
              Пример: 5.0 секунд → «05.000», а не «5.000».

        Особое внимание — округлению: если секунды после округления
        превращаются в 60.000, они переносятся в минуты; если минуты
        становятся 60 — в градусы. Иначе получилось бы «45°12'60.000"».
        """
        sign = "-" if v < 0 else ""
        v = abs(v)

        deg = int(v)
        rem = (v - deg) * 60.0
        minutes = int(rem)
        seconds = (rem - minutes) * 60.0

        # Округляем секунды с учётом переносов вверх.
        seconds = round(seconds, sec_prec)
        if seconds >= 60.0:
            seconds -= 60.0
            minutes += 1
        if minutes >= 60:
            minutes -= 60
            deg += 1

        # Форматируем секунды с ведущим нулём.
        # Общая ширина: 2 знака до запятой + 1 точка + sec_prec после.
        width = 3 + sec_prec
        sec_str = f"{seconds:0{width}.{sec_prec}f}"

        return f"{sign}{deg}°{minutes:02d}'{sec_str}\""

    # --------------------------------------------------------
    # Страницы QStackedWidget — по одной на формат координат
    # --------------------------------------------------------
    def _page_decimal(self):
        """Страница для десятичных координат: два поля — X и Y."""
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        self.x_combo, self.x_label = self._add_col_combo(h, "Север:")
        self.y_combo, self.y_label = self._add_col_combo(h, "Восток:")
        h.addStretch(1)
        return w

    def _page_hms_one(self):
        """Страница для ГМС в одной колонке: два поля.

        Подписи — Широта/Долгота, обновляются по выбранному порядку.
        Ссылки на подписи сохраняются как self.c1_label / self.c2_label —
        чтобы _update_axis_labels мог их менять.
        """
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        self.c1_combo, self.c1_label = self._add_col_combo(h, "Широта:")
        self.c2_combo, self.c2_label = self._add_col_combo(h, "Долгота:")
        h.addStretch(1)
        return w

    def _page_hms_three(self):
        """Страница для ГМС в трёх колонках: 6 полей (гр, мин, сек ×2).

        Надписи «Коорд.1:» / «Коорд.2:» сохранены как
        self.c1h_label / self.c2h_label — их тоже переключает
        _update_axis_labels на Широта/Долгота по выбранному порядку.
        """
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        self.c1h_label = QLabel("Широта:")
        h.addWidget(self.c1h_label)
        self.c1d, _ = self._add_col_combo(h, "")
        h.addWidget(QLabel("°"))
        self.c1m, _ = self._add_col_combo(h, "")
        h.addWidget(QLabel("'"))
        self.c1s, _ = self._add_col_combo(h, "")
        h.addWidget(QLabel('"'))

        h.addSpacing(15)

        self.c2h_label = QLabel("Долгота:")
        h.addWidget(self.c2h_label)
        self.c2d, _ = self._add_col_combo(h, "")
        h.addWidget(QLabel("°"))
        self.c2m, _ = self._add_col_combo(h, "")
        h.addWidget(QLabel("'"))
        self.c2s, _ = self._add_col_combo(h, "")
        h.addWidget(QLabel('"'))

        h.addStretch(1)
        return w

    def _add_col_combo(self, layout, label):
        """Добавляет в layout подпись + комбобокс выбора колонки."""
        lbl = QLabel(label)
        layout.addWidget(lbl)
        combo = QComboBox()
        combo.addItem("—")
        combo.setSizeAdjustPolicy(COL_COMBO_POLICY)
        combo.setMinimumContentsLength(COL_COMBO_MIN_CHARS)
        combo.setMaximumWidth(200)
        layout.addWidget(combo)
        return combo, lbl

    # --------------------------------------------------------
    # Настройки через QgsSettings
    # --------------------------------------------------------
    def _load_settings(self):
        """Восстанавливает последние значения полей окна.

        Все ключи лежат под префиксом SETTINGS_PREFIX. Если настройки
        ещё не сохранялись или повреждены — берутся значения по умолчанию.
        """
        s = QgsSettings()
        try:
            v = s.value(SETTINGS_PREFIX + "delim", "авто", type=str)
            i = self.delim.findText(v)
            if i >= 0:
                self.delim.setCurrentIndex(i)

            v = s.value(SETTINGS_PREFIX + "encoding", "UTF-8", type=str)
            i = self.enc.findText(v)
            if i >= 0:
                self.enc.setCurrentIndex(i)

            v = s.value(SETTINGS_PREFIX + "geometry", "Точка", type=str)
            i = self.geom_combo.findText(v)
            if i >= 0:
                self.geom_combo.setCurrentIndex(i)

            authid = s.value(SETTINGS_PREFIX + "crs", "EPSG:4326", type=str)
            crs = QgsCoordinateReferenceSystem(authid)
            if crs.isValid():
                self.crs_widget.setCrs(crs)

            v = s.value(SETTINGS_PREFIX + "poly_style", "Контур", type=str)
            i = self.poly_style.findText(v)
            if i >= 0:
                self.poly_style.setCurrentIndex(i)

            v = s.value(SETTINGS_PREFIX + "order", ORDERS[0], type=str)
            i = self.order_combo.findText(v)
            if i >= 0:
                self.order_combo.setCurrentIndex(i)

            v = s.value(SETTINGS_PREFIX + "axes", AXES[0], type=str)
            i = self.axes_combo.findText(v)
            if i >= 0:
                self.axes_combo.setCurrentIndex(i)

            self.cb_numbering.setChecked(
                s.value(SETTINGS_PREFIX + "numbering", False, type=bool)
            )
            self.cb_vertices.setChecked(
                s.value(SETTINGS_PREFIX + "vertices", False, type=bool)
            )

            self.save_path_edit.setText(
                s.value(SETTINGS_PREFIX + "save_path", "", type=str)
            )
            self.cb_save_file.setChecked(
                s.value(SETTINGS_PREFIX + "save_enabled", False, type=bool)
            )

            v = s.value(SETTINGS_PREFIX + "vnum_mode", "Авто (по объектам)", type=str)
            i = self.vnum_mode_combo.findText(v)
            if i >= 0:
                self.vnum_mode_combo.setCurrentIndex(i)

            self._saved_vnum_col = s.value(SETTINGS_PREFIX + "vnum_col", "", type=str)

        except Exception as e:  # noqa: BLE001 — слот не должен ронять плагин
            _log_ignored_exception(e, "некритичная ошибка")

    def _save_settings(self):
        """Сохраняет текущие значения полей в QgsSettings."""
        s = QgsSettings()
        try:
            s.setValue(SETTINGS_PREFIX + "delim", self.delim.currentText())
            s.setValue(SETTINGS_PREFIX + "encoding", self.enc.currentText())
            s.setValue(SETTINGS_PREFIX + "geometry", self.geom_combo.currentText())
            s.setValue(SETTINGS_PREFIX + "crs", self.crs_widget.crs().authid())
            s.setValue(SETTINGS_PREFIX + "poly_style", self.poly_style.currentText())
            s.setValue(SETTINGS_PREFIX + "order", self.order_combo.currentText())
            s.setValue(SETTINGS_PREFIX + "axes", self.axes_combo.currentText())
            s.setValue(SETTINGS_PREFIX + "numbering", self.cb_numbering.isChecked())
            s.setValue(SETTINGS_PREFIX + "vertices", self.cb_vertices.isChecked())
            s.setValue(SETTINGS_PREFIX + "save_path", self.save_path_edit.text())
            s.setValue(SETTINGS_PREFIX + "save_enabled", self.cb_save_file.isChecked())
            s.setValue(
                SETTINGS_PREFIX + "vnum_mode", self.vnum_mode_combo.currentText()
            )
            s.setValue(SETTINGS_PREFIX + "vnum_col", self.vnum_col_combo.currentText())
        except Exception as e:  # noqa: BLE001 — слот не должен ронять плагин
            _log_ignored_exception(e, "некритичная ошибка")

    def done(self, result):
        """Перехват закрытия окна.

        Перед закрытием сохраняем настройки и чистим превью-карту,
        чтобы не оставлять временные объекты на канве QGIS.
        """
        self._save_settings()
        self._clear_rubber()
        self._clear_temp_layer()
        super().done(result)

    # --------------------------------------------------------
    # Превью-карта
    # --------------------------------------------------------
    def _init_map_canvas(self):
        """Готовит превью-карту и резиновые ленты для рисования.

        Отдельные ленты под разные типы геометрии: точки, линии,
        полигоны и вершины.
        """
        self.map_canvas.setCanvasColor(QColor(255, 255, 255))
        try:
            self.map_canvas.enableAntiAliasing(True)
        except Exception as e:  # noqa: BLE001 — слот не должен ронять плагин
            _log_ignored_exception(e, "некритичная ошибка")
        try:
            self.map_canvas.setDestinationCrs(self.crs_widget.crs())
        except Exception as e:  # noqa: BLE001 — слот не должен ронять плагин
            _log_ignored_exception(e, "некритичная ошибка")

        self.rb_point = QgsRubberBand(self.map_canvas, _QgsWkbTypesGeom_Point)
        self.rb_line = QgsRubberBand(self.map_canvas, _QgsWkbTypesGeom_Line)
        self.rb_poly = QgsRubberBand(self.map_canvas, _QgsWkbTypesGeom_Polygon)
        self.rb_vertex = QgsRubberBand(self.map_canvas, _QgsWkbTypesGeom_Point)

        self.rb_point.setColor(QColor(0, 90, 230, 255))
        self.rb_line.setColor(QColor(20, 160, 60, 255))
        self.rb_point.setWidth(2)
        self.rb_line.setWidth(2)

        # Синий — угловые точки.
        self.rb_vertex.setColor(QColor(0, 90, 230, 255))
        self.rb_vertex.setWidth(5)
        self.rb_vertex.setIconSize(6)

    def _clear_rubber(self):
        """Стирает всё нарисованное на превью-карте."""
        try:
            self.rb_point.reset(_QgsWkbTypesGeom_Point)
            self.rb_line.reset(_QgsWkbTypesGeom_Line)
            self.rb_poly.reset(_QgsWkbTypesGeom_Polygon)
            self.rb_vertex.reset(_QgsWkbTypesGeom_Point)
        except Exception as e:  # noqa: BLE001 — слот не должен ронять плагин
            _log_ignored_exception(e, "некритичная ошибка")

    def _clear_temp_layer(self):
        """Убирает все временные слои превью с карты.

        ВАЖНО: setLayers([]) вызывается всегда, а не только когда
        _temp_layer установлен. Иначе слои площадей (они кладутся
        в _preview_layers, но не в _temp_layer) остаются на канве.
        """
        self._preview_layers = []
        try:
            self.map_canvas.setLayers([])
        except Exception as e:  # noqa: BLE001 — слот не должен ронять плагин
            _log_ignored_exception(e, "некритичная ошибка")
        self._temp_layer = None

    def _apply_poly_preview_style(self):
        """Применяет стиль полигона и текущие настройки отображения.

        Логика:
            • Контур          — обводка цвета poly_outline_color,
                                заливка прозрачная;
            • Заливка         — обводка прозрачная,
                                заливка poly_fill_color;
            • Контур + заливка — обе части.

        Толщина контура — poly_outline_width.
        """
        ds = self.display_settings
        style = self.poly_style.currentText()

        outline_color = ds.get("poly_outline_color", QColor(230, 0, 0, 220))
        outline_width = ds.get("poly_outline_width", 2)
        fill_color = ds.get("poly_fill_color", QColor(230, 0, 0, 50))

        if style == "Контур":
            self.rb_poly.setColor(outline_color)
            self.rb_poly.setFillColor(QColor(0, 0, 0, 0))
            self.rb_poly.setWidth(outline_width)
        elif style == "Заливка":
            self.rb_poly.setColor(QColor(0, 0, 0, 0))
            self.rb_poly.setFillColor(fill_color)
            self.rb_poly.setWidth(0)
        else:  # 'Контур + заливка'
            self.rb_poly.setColor(outline_color)
            self.rb_poly.setFillColor(fill_color)
            self.rb_poly.setWidth(outline_width)

    def _update_scale_label(self):
        """Обновляет масштабную линейку под текущий экстент карты."""
        try:
            self.scale_bar.update_scale()
        except Exception as e:  # noqa: BLE001 — слот не должен ронять плагин
            _log_ignored_exception(e, "некритичная ошибка")

    def _update_map_preview(self):
        """Перерисовывает превью-карту.

        Рисует геометрию, вершины (если включено), номера и подписи
        площадей для полигонов. Обновляет индикатор общей площади
        в левом верхнем углу.
        """
        if self.rb_point is None:
            return
        self._clear_rubber()
        self._clear_temp_layer()
        # Для пространственного входа — своя логика отрисовки.
        if self._is_spatial_input:
            self._update_spatial_map_preview()
            return

        # Сбрасываем индикатор общей площади — пересчитается ниже.
        self._total_area_m2 = 0.0
        self.total_area_label.setVisible(False)

        if not self.data_blocks:
            self.map_canvas.refresh()
            return

        parsed_blocks = []
        for block in self.data_blocks:
            pblock = []
            for row in block:
                try:
                    x, y = self._get_xy(row)
                    pblock.append((x, y, row))
                except ValueError:
                    continue
            if pblock:
                parsed_blocks.append(pblock)

        if not parsed_blocks:
            self.map_canvas.refresh()
            return

        geom_name = self.geom_combo.currentText()
        wkb = GEOM_WKB[geom_name]
        is_point = wkb == _QgsWkbTypesType_Point
        is_poly = wkb in (_QgsWkbTypesType_Polygon, _QgsWkbTypesType_MultiPolygon)
        units = self._current_units()

        want_vertices = self.cb_vertices.isChecked() and not is_point
        want_numbering = self.cb_numbering.isChecked()

        self._apply_poly_preview_style()

        geoms = self._collect_geometries(wkb, parsed_blocks)
        rect = None

        if geoms:
            if is_point:
                rb = self.rb_point
            elif wkb == _QgsWkbTypesType_LineString:
                rb = self.rb_line
            else:
                rb = self.rb_poly

            for g in geoms:
                rb.addGeometry(g, None)
                bb = g.boundingBox()
                rect = QgsRectangle(bb) if rect is None else _extend(rect, bb)

        # --- Номера точек и углов ---
        # Сбор номеров: для точек — сами точки, для линий/полигонов — углы.
        _meta, row_vnum = self._calculate_meta(parsed_blocks, wkb)

        pts_data = []

        if is_point:
            if want_numbering:
                for bi, block in enumerate(parsed_blocks):
                    for ri, (x, y, row) in enumerate(block):
                        vnum_str = row_vnum.get(id(row), "?")
                        pts_data.append((vnum_str, QgsPointXY(x, y)))
        else:
            if want_vertices or want_numbering:
                for block in parsed_blocks:
                    pts_xyz = [(x, y, row) for x, y, row in block]
                    if is_poly:
                        subs = self._split_polygon_points(pts_xyz)
                    else:
                        subs = [pts_xyz]
                    for pts in subs:
                        for x, y, row in pts:
                            vnum_str = row_vnum.get(id(row), "?")
                            pts_data.append((vnum_str, QgsPointXY(x, y)))

        if (want_vertices or want_numbering) and not is_point and pts_data:
            for _n, pt in pts_data:
                self.rb_vertex.addPoint(pt)
                bb = QgsRectangle(pt.x(), pt.y(), pt.x(), pt.y())
                rect = bb if rect is None else _extend(rect, bb)

        if want_numbering and pts_data:
            self._make_number_layer(pts_data, self.crs_widget.crs())

        # --- Площади полигонов ---
        # --- Площади полигонов ---
        if is_poly and geoms:
            area_data = []
            total = 0.0
            for num, g in enumerate(geoms, 1):
                area_m2 = _geom_area_m2(g, units)
                total += area_m2
                c = self._label_anchor_for_poly(g)
                # Передаём отдельно: номер, текст площади, точку подписи.
                # HTML собирается внутри _make_area_label_layer.
                area_data.append((num, f"{area_m2:.2f}", c))

            if area_data:
                self._make_area_label_layer(area_data, self.crs_widget.crs())

            self._total_area_m2 = total
            self.total_area_label.setText(f"Общая площадь: {total:.2f} м²")
            self.total_area_label.setVisible(True)

        # Обновляем список слоёв на канве — номера и площади вместе.
        if self._preview_layers:
            self.map_canvas.setLayers(list(self._preview_layers))

        if rect is not None and not rect.isEmpty():
            if rect.width() == 0 and rect.height() == 0:
                rect.grow(1.0)
            rect.scale(1.15)
            self.map_canvas.setExtent(rect)

        self.map_canvas.refresh()

    def _update_spatial_map_preview(self):
        """Рисует объекты из пространственного файла.

        Каждый тип — своим цветом:
            точки — синие кружки;
            линии — зелёные ломаные;
            полигоны — красные контуры с полупрозрачной заливкой.

        Стиль полигона учитывается: для полигонов берём цвет
        и заливку как в комбобоксе «Стиль». Нумерация и точки
        по углам рисуются как обычно.
        """
        self._clear_rubber()
        self._clear_temp_layer()
        self._total_area_m2 = 0.0
        self.total_area_label.setVisible(False)

        if not self.spatial_data:
            self.map_canvas.refresh()
            return

        rect = None
        ds = self.display_settings
        colors = {
            _QgsWkbTypesGeom_Point: (
                ds.get("point_color", QColor(0, 90, 230, 255)),
                ds.get("point_size", 6),
            ),
            _QgsWkbTypesGeom_Line: (
                ds.get("line_color", QColor(20, 160, 60, 255)),
                ds.get("line_width", 2),
            ),
            _QgsWkbTypesGeom_Polygon: (
                ds.get("poly_outline_color", QColor(230, 0, 0, 220)),
                ds.get("poly_outline_width", 2),
            ),
        }

        want_vertices = self.cb_vertices.isChecked()
        want_numbering = self.cb_numbering.isChecked()

        num_points_data = []
        area_data = []
        num = 0

        for part in self.spatial_data:
            base = QgsWkbTypes.geometryType(part["wkb"])
            color, width = colors.get(base, (QColor(0, 0, 0, 255), 2))

            # --- Рисуем геометрию ---
            if base == _QgsWkbTypesGeom_Point:
                self.rb_point.setColor(color)
                self.rb_point.setWidth(width)
                rb = self.rb_point
            elif base == _QgsWkbTypesGeom_Line:
                self.rb_line.setColor(color)
                self.rb_line.setWidth(width)
                rb = self.rb_line
            else:
                self._apply_poly_preview_style()
                rb = self.rb_poly

            for f in part["features"]:
                g = f.geometry()
                if g is None or g.isEmpty():
                    continue
                rb.addGeometry(g, None)
                bb = g.boundingBox()
                rect = QgsRectangle(bb) if rect is None else _extend(rect, bb)

            # --- Считаем номера, вершины, площади ---
            units = self._current_units()
            for f in part["features"]:
                g = f.geometry()
                if g is None or g.isEmpty():
                    continue

                num += 1

                if base == _QgsWkbTypesGeom_Point:
                    if want_numbering:
                        c = g.asPoint()
                        num_points_data.append((num, QgsPointXY(c)))
                else:
                    if want_vertices or want_numbering:
                        for vnum, v in enumerate(self._iter_vertices(g), 1):
                            num_points_data.append((vnum, v))
                            self.rb_vertex.addPoint(v)
                            bb = QgsRectangle(v.x(), v.y(), v.x(), v.y())
                            rect = bb if rect is None else _extend(rect, bb)

                    if base == _QgsWkbTypesGeom_Polygon:
                        area_m2 = _geom_area_m2(g, units)
                        self._total_area_m2 += area_m2
                        c = self._label_anchor_for_poly(g)
                        area_data.append((num, f"{area_m2:.2f}", c))

        # --- Слои подписей ---
        if want_numbering and num_points_data:
            self._make_number_layer(num_points_data, self.crs_widget.crs())
        if area_data:
            self._make_area_label_layer(area_data, self.crs_widget.crs())

        if self._preview_layers:
            self.map_canvas.setLayers(list(self._preview_layers))

        if self._total_area_m2 > 0:
            self.total_area_label.setText(
                f"Общая площадь: {self._total_area_m2:.2f} м²"
            )
            self.total_area_label.setVisible(True)

        if rect is not None and not rect.isEmpty():
            if rect.width() == 0 and rect.height() == 0:
                rect.grow(1.0)
            rect.scale(1.15)
            self.map_canvas.setExtent(rect)

        self.map_canvas.refresh()

    def _iter_vertices(self, geom):
        """Идёт по всем вершинам геометрии, включая мульти-части.

        Возвращает QgsPointXY-точки по одной.
        """
        if geom.isMultipart():
            for part in geom.asGeometryCollection():
                for v in self._iter_vertices(part):
                    yield v
        else:
            for v in geom.vertices():
                yield QgsPointXY(v.x(), v.y())

    def _label_anchor_for_poly(self, geom):
        """Возвращает точку для подписи площади полигона.

        Для обычного полигона — центроид.
        Для мультиполигона центроид всей геометрии может лежать
        вне контуров. Тогда берём центроид самого крупного контура —
        чтобы подпись гарантированно оказалась внутри.

        Параметры:
            geom — QgsGeometry (Polygon или MultiPolygon).

        Возвращает QgsPointXY.
        """
        if not geom.isMultipart():
            return geom.centroid().asPoint()

        parts = geom.asGeometryCollection()
        if not parts:
            return geom.centroid().asPoint()

        biggest = max(parts, key=lambda p: p.area())
        return biggest.centroid().asPoint()

    def _make_area_label_layer(self, pts_data, crs):
        """Создаёт временный точечный слой для подписей площадей.

        Параметры:
            pts_data — список (номер_объекта, текст_площади, QgsPointXY).
                       Номер используется как нижний индекс: S₁, S₂, …
                       Точка — центроид объекта или крупнейшего контура.
            crs      — СК исходных данных.

        Слой не сохраняется на диск. Маркер прозрачный, видны
        только подписи. Единицы — м². Нижний индекс — через HTML-тег
        <sub>, поэтому у формата подписи включён setAllowHtmlFormatting.
        """
        layer = QgsVectorLayer(f"Point?crs={crs.authid()}", "preview_area", "memory")
        prov = layer.dataProvider()
        prov.addAttributes([QgsField("label", T_STRING)])
        layer.updateFields()

        feats = []
        for num, area_text, pt in pts_data:
            # HTML-разметка: S с нижним индексом = площадь + единицы.
            label = f"S<sub>{num}</sub>={area_text} м²"
            f = QgsFeature(layer.fields())
            f.setGeometry(QgsGeometry.fromPointXY(pt))
            f.setAttributes([label])
            feats.append(f)
        prov.addFeatures(feats)
        layer.updateExtents()

        symbol = QgsMarkerSymbol.createSimple(
            {
                "name": "circle",
                "color": "0,0,0,0",
                "size": "0.1",
                "outline_style": "no",
            }
        )
        layer.renderer().setSymbol(symbol)

        # Подписи площадей — тёмно-синие, чуть крупнее номеров.
        settings = QgsPalLayerSettings()
        settings.fieldName = "label"
        settings.isExpression = False
        try:
            settings.enabled = True
        except Exception as e:  # noqa: BLE001 — слот не должен ронять плагин
            _log_ignored_exception(e, "некритичная ошибка")

        ds = self.display_settings
        area_color = ds.get("area_label_color", QColor(0, 60, 160, 255))
        area_size = ds.get("area_label_size", 10)

        fmt = QgsTextFormat()
        fmt.setSize(area_size)
        try:
            fmt.setColor(area_color)
        except Exception as e:  # noqa: BLE001 — слот не должен ронять плагин
            _log_ignored_exception(e, "некритичная ошибка")
        # Разрешаем HTML-разметку в подписи — иначе <sub> выведется
        # буквально как текст. Метод есть в QGIS 3.16+, у нас 3.44.
        try:
            fmt.setAllowHtmlFormatting(True)
        except Exception as e:  # noqa: BLE001 — слот не должен ронять плагин
            _log_ignored_exception(e, "некритичная ошибка")
        settings.setFormat(fmt)
        layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
        layer.setLabelsEnabled(True)
        layer.triggerRepaint()

        self._preview_layers.append(layer)

    def _make_number_layer(self, pts_data, crs):
        """Создаёт временный точечный слой только для подписей номеров.

        Параметры:
            pts_data — список (номер, QgsPointXY)
            crs      — СК исходных данных

        Слой не добавляется в QgsProject и не сохраняется на диск.
        Маркер прозрачный, чтобы были видны только подписи.
        """
        layer = QgsVectorLayer(f"Point?crs={crs.authid()}", "preview_num", "memory")
        prov = layer.dataProvider()
        prov.addAttributes([QgsField("num", T_INT)])
        layer.updateFields()

        feats = []
        for num, pt in pts_data:
            f = QgsFeature(layer.fields())
            f.setGeometry(QgsGeometry.fromPointXY(pt))
            f.setAttributes([num])
            feats.append(f)
        prov.addFeatures(feats)
        layer.updateExtents()

        symbol = QgsMarkerSymbol.createSimple(
            {
                "name": "circle",
                "color": "0,0,0,0",
                "size": "0.1",
                "outline_style": "no",
            }
        )
        layer.renderer().setSymbol(symbol)

        ds = self.display_settings
        num_color = ds.get("num_label_color", QColor(180, 0, 0, 255))
        num_size = ds.get("num_label_size", 10)
        _enable_number_labels(
            layer,
            color=f"{num_color.red()},{num_color.green()},"
            f"{num_color.blue()},{num_color.alpha()}",
            size=num_size,
        )

        self._preview_layers.append(layer)
        self._temp_layer = layer

    def _collect_geometries(self, wkb, parsed_blocks):
        """Собирает список QgsGeometry без добавления в слой.

        Используется для превью-карты. Логика полностью совпадает
        с _build_features, чтобы превью было 1:1 с результатом импорта.
        """
        geoms = []
        is_poly = wkb in (_QgsWkbTypesType_Polygon, _QgsWkbTypesType_MultiPolygon)

        if wkb == _QgsWkbTypesType_Point:
            for block in parsed_blocks:
                for x, y, _row in block:
                    geoms.append(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
            return geoms

        for block in parsed_blocks:
            if not block:
                continue

            # Кортежи из (x, y, row) — чтобы _split_polygon_points
            # мог работать с ними и сохранять связь с исходной строкой.
            pts_xyz = [(x, y, row) for x, y, row in block]

            if is_poly:
                sub_groups = self._split_polygon_points(pts_xyz)
            else:
                sub_groups = [pts_xyz]

            for pts in sub_groups:
                if wkb == _QgsWkbTypesType_LineString and len(pts) < 2:
                    continue
                if is_poly and len(pts) < 3:
                    continue

                ring = [QgsPointXY(x, y) for x, y, _ in pts]
                if wkb == _QgsWkbTypesType_LineString:
                    g = QgsGeometry.fromPolylineXY(ring)
                elif wkb == _QgsWkbTypesType_Polygon:
                    g = QgsGeometry.fromPolygonXY([ring])
                else:
                    g = QgsGeometry.fromMultiPolygonXY([[ring]])

                if not g.isEmpty():
                    geoms.append(g)

        return geoms

    # --------------------------------------------------------
    # Загрузка данных
    # --------------------------------------------------------
    def on_browse(self):
        """Открывает диалог выбора файла и грузит выбранный.

        Поддерживаются три группы форматов:
            • текстовые — .csv, .txt, .tab;
            • Excel — .xls, .xlsx, .ods (через GDAL/OGR);
            • пространственные — .shp, .geojson, .json, .kml, .gpkg.
        """
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Файл",
            "",
            "Все поддерживаемые (*.csv *.txt *.tab *.xls *.xlsx *.ods "
            "*.shp *.geojson *.json *.kml *.gpkg);;"
            "Текстовые (*.csv *.txt *.tab);;"
            "Excel (*.xls *.xlsx *.ods);;"
            "Пространственные (*.shp *.geojson *.json *.kml *.gpkg);;"
            "Все файлы (*.*)",
        )
        if not path:
            return
        self._load_file(path)

    def on_browse_save(self):
        """Открывает диалог сохранения .gpkg и проставляет путь."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить в GeoPackage", "", "GeoPackage (*.gpkg)"
        )
        if not path:
            return
        if not path.lower().endswith(".gpkg"):
            path += ".gpkg"
        self.save_path_edit.setText(path)
        self.cb_save_file.setChecked(True)

    def _load_file(self, path):
        """Читает файл и запускает разбор.

        По расширению определяем тип:
            • Excel (.xls/.xlsx/.ods) — через GDAL/OGR как таблица;
            • пространственные (.shp/.geojson/.json/.kml/.gpkg) —
              через OGR как готовая геометрия;
            • всё остальное — как текстовый файл в выбранной кодировке.
        """
        # Сбрасываем всё, что осталось от предыдущей загрузки.
        self._reset_before_load()

        self.file_edit.setText(path)

        ext = os.path.splitext(path)[1].lower()

        if ext in (".xls", ".xlsx", ".ods"):
            self._load_excel_file(path)
            return

        if ext in (".shp", ".geojson", ".json", ".kml", ".gpkg"):
            self._load_spatial_file(path)
            return

        # Текстовый формат.
        try:
            with open(path, "r", encoding=self._py_encoding()) as f:
                text = f.read()
        except (OSError, UnicodeDecodeError, LookupError) as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось прочитать файл:\n{e}")
            return
        self._load_text(text, source=f"файл «{path}»")

    def on_clipboard(self):
        """Загружает текст из буфера обмена."""
        text = QApplication.clipboard().text()
        if not text.strip():
            QMessageBox.warning(self, "Пусто", "В буфере нет текста")
            return

        # Сбрасываем всё, что осталось от предыдущей загрузки,
        # включая spatial-состояние.
        self._reset_before_load()
        self.file_edit.clear()

        self._load_text(text, source="буфер обмена")

    def _reset_before_load(self):
        """Сбрасывает состояние перед загрузкой нового источника.

        Вызывается в самом начале любой загрузки — из файла или
        из буфера. Без этого возможна «смесь»: например, загрузили
        KML (spatial), потом из буфера (текст) — spatial_data
        остаётся висеть, карта рисует одно, таблица другое.

        Что сбрасываем:
            • блоки текста и заголовки;
            • сохранённый исходный текст;
            • признаки spatial-входа и его данные;
            • таблицу предпросмотра;
            • резиновые ленты и временные слои на карте.
        """
        self.blocks = []
        self.data_blocks = []
        self.rows = []
        self.headers = []
        self._source_text = ""

        self.spatial_data = []
        self._is_spatial_input = False

        self.preview.blockSignals(True)
        self.preview.clear()
        self.preview.setRowCount(0)
        self.preview.setColumnCount(0)
        self.preview.blockSignals(False)

        self.format_label.setText("Формат: —")
        self.headers_label.setText("Заголовки: —")

        self._clear_rubber()
        self._clear_temp_layer()

        self._total_area_m2 = 0.0
        self.total_area_label.setVisible(False)

        # Поле «Геометрия» возвращаем к доступному состоянию.
        try:
            self.geom_combo.setEnabled(True)
        except Exception as e:  # noqa: BLE001 — слот не должен ронять плагин
            _log_ignored_exception(e, "некритичная ошибка")

    def on_clear(self):
        """Полностью очищает форму и превью."""
        self.file_edit.clear()
        self._source_text = ""
        # Сбрасываем пространственный вход.
        self.spatial_data = []
        self._is_spatial_input = False
        self.geom_combo.setEnabled(True)
        self.blocks = []
        self.data_blocks = []
        self.rows = []
        self.headers = []
        self._clear_layer_name_error()
        self._clear_crs_error()
        self.name_warning.setVisible(False)
        self._name_warn_shown = False
        self.crs_warning.setVisible(False)

        self.preview.clear()
        self.preview.setRowCount(0)
        self.preview.setColumnCount(0)
        self.format_label.setText("Формат: —")
        self.headers_label.setText("Заголовки: —")

        combos = [
            self.x_combo,
            self.y_combo,
            self.c1_combo,
            self.c2_combo,
            self.c1d,
            self.c1m,
            self.c1s,
            self.c2d,
            self.c2m,
            self.c2s,
        ]
        for c in combos:
            c.blockSignals(True)
            c.clear()
            c.addItem("—")
            c.blockSignals(False)
        self.coord_stack.setCurrentIndex(0)
        # Возвращаем видимость всех текстовых опций —
        # spatial-режим снят, обычная раскладка восстановлена.
        self._update_options_visibility()
        self._clear_rubber()
        self._clear_temp_layer()

        try:
            self.map_canvas.refresh()
        except Exception as e:  # noqa: BLE001 — слот не должен ронять плагин
            _log_ignored_exception(e, "некритичная ошибка")

    def _py_encoding(self):
        """Возвращает имя кодировки Python для выбранного варианта."""
        e = self.enc.currentText()
        return {"UTF-8": "utf-8", "CP1251": "cp1251", "UTF-16": "utf-16"}.get(
            e, "utf-8"
        )

    def _current_delim(self):
        """Возвращает символ-разделитель с учётом режима 'авто'."""
        name = self.delim.currentText()
        if name == "авто":
            if self._source_text:
                return self._detect_delimiter(self._source_text)
            return "\t"
        return DELIMS.get(name) or "\t"

    def _detect_delimiter(self, text):
        """Автоопределение разделителя.

        Для каждого кандидата считаем число колонок в первых строках.
        Побеждает самый стабильный. Если ни один не дал ≥2 колонок,
        возвращается таб.
        """
        lines = [line for line in text.splitlines() if line.strip()][:15]
        if not lines:
            return "\t"

        candidates = ["\t", ",", ";", " "]
        best = "\t"
        best_score = -1

        for d in candidates:
            counts = []
            for line in lines:
                if d == " ":
                    counts.append(len(line.split()))
                else:
                    try:
                        counts.append(len(next(csv.reader([line], delimiter=d))))
                    except (csv.Error, ValueError):
                        counts.append(0)

            multi = [c for c in counts if c > 1]
            if not multi:
                continue

            cnt = Counter(multi)
            top_count, top_freq = cnt.most_common(1)[0]
            consistency = top_freq / len(multi)
            score = consistency * 100 + top_count

            if score > best_score:
                best_score = score
                best = d

        return best

    def _clean_cell(self, c):
        """Убирает обрамляющие двойные кавычки и пробелы.

        Нужно, чтобы строка из одной ячейки "" считалась пустой.
        """
        if c is None:
            return ""
        s = str(c).strip()
        while len(s) >= 2 and s[0] == '"' and s[-1] == '"':
            s = s[1:-1].strip()
        return s

    def _parse_text(self, text, delim):
        """Разбирает текст в блоки строк.

        Пустая строка = граница нового блока. Для пробела используется
        line.split(), чтобы двойные пробелы не давали пустых ячеек.
        """
        blocks = []
        current = []
        for line in text.splitlines():
            if delim == " ":
                cells = line.split()
            else:
                try:
                    cells = next(csv.reader([line], delimiter=delim))
                except (csv.Error, ValueError):
                    cells = [line]
            cells = [self._clean_cell(c) for c in cells]
            if any(c for c in cells):
                current.append(cells)
            else:
                if current:
                    blocks.append(current)
                    current = []
        if current:
            blocks.append(current)
        return blocks

    def _load_excel_file(self, path):
        """Читает Excel через GDAL/OGR и загружает как таблицу."""
        blocks = self._read_excel_via_ogr(path)
        if blocks is None:
            QMessageBox.warning(
                self,
                "Не удалось прочитать Excel",
                f"Файл «{path}» не читается через GDAL/OGR.\n\n"
                f"Возможные причины:\n"
                f"  • файл повреждён или защищён паролем;\n"
                f"  • формат не поддерживается сборкой GDAL.\n\n"
                f"Откройте файл в Excel/LibreOffice и сохраните в .csv.",
            )
            return
        self._load_from_blocks(blocks, source=f"Excel «{path}»")

    def _read_excel_via_ogr(self, path):
        """Читает первый непустой лист Excel через OGR.

        Возвращает список блоков (как _parse_text) или None при ошибке.
        Первая строка листа трактуется как заголовки — OGR иначе не умеет.
        """
        try:
            from osgeo import ogr
        except ImportError:
            return None

        try:
            ds = ogr.Open(path)
        except (RuntimeError, OSError):
            return None
        if ds is None:
            return None

        try:
            target_layer = None
            for i in range(ds.GetLayerCount()):
                layer = ds.GetLayer(i)
                if layer is not None and layer.GetFeatureCount() > 0:
                    target_layer = layer
                    break
            if target_layer is None:
                return None

            defn = target_layer.GetLayerDefn()
            field_count = defn.GetFieldCount()
            headers = [defn.GetFieldDefn(j).GetName() for j in range(field_count)]

            rows = [headers]
            target_layer.ResetReading()
            feat = target_layer.GetNextFeature()
            while feat is not None:
                row = []
                for j in range(field_count):
                    val = feat.GetField(j)
                    row.append("" if val is None else str(val))
                rows.append(row)
                feat = target_layer.GetNextFeature()
        finally:
            ds = None

        if len(rows) < 2:
            return None

        blocks = []
        current = []
        for r in rows[1:]:
            if any(str(c).strip() for c in r):
                current.append([str(c).strip() for c in r])
            else:
                if current:
                    blocks.append(current)
                    current = []
        if current:
            blocks.append(current)
        if not blocks:
            return None

        blocks[0].insert(0, headers)
        return blocks

    def _load_from_blocks(self, blocks, source="данные"):
        """Загружает уже разобранные блоки (например, из Excel).

        Разделитель не применяется — данные пришли готовыми.
        _source_text остаётся пустым, чтобы смена разделителя
        не пыталась пересобрать таблицу.
        """
        self._source_text = ""

        if not blocks:
            QMessageBox.warning(self, "Пусто", "Нет данных")
            return

        ok, num_cells, _nonempty_cells, total_rows = self._looks_like_coords(blocks)
        if not ok:
            QMessageBox.warning(
                self,
                "Не похоже на координаты",
                f"Загруженные данные ({source}) не похожи на таблицу "
                f"с координатами.\n\n"
                f"Строк: {total_rows}\n"
                f"Из них чисел: {num_cells}\n\n"
                f"Проверьте, что в файле есть колонки с координатами.",
            )
            return

        self.blocks = blocks
        self._rebuild_from_raw()

    def _load_spatial_file(self, path):
        """Загружает .shp/.geojson/.kml/.gpkg через GDAL/OGR.

        Файл НЕ добавляется в проект. Объекты разбиваются по типам
        геометрии и складываются в self.spatial_data. Пользователь
        видит превью-карту и таблицу, но в проект ничего не попадает,
        пока он не нажмёт «Импортировать».
        """
        parts = self._read_spatial_via_ogr(path)
        if not parts:
            QMessageBox.warning(
                self,
                "Не удалось прочитать файл",
                f"Файл «{path}» не читается через GDAL/OGR.\n\n"
                f"Возможные причины:\n"
                f"  • файл повреждён;\n"
                f"  • это не пространственный файл;\n"
                f"  • формат не поддерживается сборкой GDAL.",
            )
            return

        self.spatial_data = parts
        self._is_spatial_input = True
        self._source_text = ""

        # СК файла — берём у первого слоя.
        try:
            self._spatial_crs = parts[0]["layer"].crs()
        except (KeyError, AttributeError, RuntimeError):
            self._spatial_crs = None

        # Подставляем реальный тип геометрии в поле «Геометрия».
        # Если типов несколько — ставим первый, пользователь увидит
        # остальные при импорте как отдельные слои.
        try:
            base = QgsWkbTypes.geometryType(parts[0]["wkb"])
            if base == _QgsWkbTypesGeom_Point:
                i = self.geom_combo.findText("Точка")
            elif base == _QgsWkbTypesGeom_Line:
                i = self.geom_combo.findText("Линия")
            else:
                i = self.geom_combo.findText("Полигон")
            if i >= 0:
                self.geom_combo.setCurrentIndex(i)
        except Exception as e:  # noqa: BLE001 — слот не должен ронять плагин
            _log_ignored_exception(e, "некритичная ошибка")

        # Нумерация углов и точки по углам для spatial-файла
        # смысла не имеют — сразу снимаем, чтобы не засорять
        # превью. Пользователь может включить их вручную.
        self.cb_vertices.setChecked(False)
        self.cb_numbering.setChecked(False)

        # Обновляем интерфейс.
        self._update_options_visibility()
        self._fill_spatial_preview_table()
        self._update_map_preview()

        total = sum(len(p["features"]) for p in parts)
        self.iface.messageBar().pushInfo(
            "Импорт", f"Загружено объектов: {total} (слоёв по типам: {len(parts)})"
        )

    def _read_spatial_via_ogr(self, path):
        """Читает пространственный файл и разбивает объекты по типам.

        Возвращает список словарей:
            [{'name': 'Точки', 'wkb': _QgsWkbTypesType_Point,
              'layer': QgsVectorLayer, 'features': [QgsFeature, ...]}, ...]

        Один элемент = один тип геометрии. Если в файле точки + линии +
        полигоны, вернётся три элемента.

        Геометрия объектов приводится к одному типу (мульти-X остаётся
        мульти-X, одиночные X — одиночными).
        """
        try:
            import importlib

            importlib.import_module("osgeo.ogr")
            from qgis.core import (
                QgsFeature,
                QgsField,
                QgsGeometry,
                QgsVectorLayer,
                QgsWkbTypes,
            )
        except ImportError:
            return []

        # Открываем через QgsVectorLayer — так удобнее работать с полями,
        # объектами и геометрией.
        layer = QgsVectorLayer(path, "spatial_source", "ogr")
        if not layer.isValid():
            return []

        # Группируем объекты по базовому типу (Point/Line/Polygon).
        groups = {}  # base_type -> {'wkb': int, 'features': [...]}

        for f in layer.getFeatures():
            geom = f.geometry()
            if geom is None or geom.isEmpty():
                continue

            wkb = geom.wkbType()
            base = QgsWkbTypes.geometryType(wkb)
            # Сохраняем исходный (возможно, мульти-) тип,
            # чтобы при сборке слоя не упростить его.
            is_multi = QgsWkbTypes.isMultiType(wkb)

            if base not in groups:
                groups[base] = {"wkb": wkb, "features": [], "is_multi": is_multi}
            groups[base]["features"].append(f)
            # Если хоть один объект — мульти, тип группы остаётся мульти.
            if is_multi:
                groups[base]["is_multi"] = True

        if not groups:
            return []

        # Готовим по слою-обёртке на каждый тип. Атрибуты копируем
        # из исходного слоя — чтобы при импорте их можно было перенести.
        result = []
        source_fields = layer.fields()

        def type_name(wkb):
            base = QgsWkbTypes.geometryType(wkb)
            if base == _QgsWkbTypesGeom_Point:
                return "Точки"
            if base == _QgsWkbTypesGeom_Line:
                return "Линии"
            if base == _QgsWkbTypesGeom_Polygon:
                return "Полигоны"
            return "Объекты"

        for base, info in groups.items():
            name = type_name(info["wkb"])

            # Создаём memory-слой с СК источника и всеми полями
            # источника. Это не для проекта, а только как «держатель»
            # полей и геометрии.
            uri = f"{QgsWkbTypes.displayString(info['wkb'])}?crs={layer.crs().authid()}"
            holder = QgsVectorLayer(uri, name, "memory")
            hp = holder.dataProvider()
            hp.addAttributes([QgsField(f.name(), f.type()) for f in source_fields])
            holder.updateFields()

            new_feats = []
            for src in info["features"]:
                nf = QgsFeature(holder.fields())
                nf.setGeometry(QgsGeometry(src.geometry()))
                # Копируем атрибуты по индексам.
                attrs = []
                for i in range(len(source_fields)):
                    attrs.append(src[i])
                nf.setAttributes(attrs)
                new_feats.append(nf)

            result.append(
                {
                    "name": name,
                    "wkb": info["wkb"],
                    "layer": holder,
                    "features": new_feats,
                }
            )

        return result

    def _load_text(self, text, source="данные"):
        """Загружает текст и запускает разбор.

        Если текущий разделитель не даёт распознать данные как
        координаты — плагин пробует остальные разделители и, если
        находится подходящий, предлагает пользователю переключиться.

        Алгоритм:
            1. Парсим с текущим разделителем.
            2. Если получилось — работаем как обычно.
            3. Если нет — пробуем альтернативы в порядке:
               авто, таб, запятая, точка с запятой, пробел.
               Первый подходящий — кандидат на переключение.
            4. Спрашиваем пользователя: переключить?
            5. Согласен — меняем разделитель и парсим заново.
               Отказался — показываем исходное сообщение об ошибке.
        """
        self._source_text = text
        delim = self._current_delim()
        blocks = self._parse_text(text, delim)

        # Быстрый путь — текущий разделитель подошёл.
        if blocks:
            ok, _, _, _ = self._looks_like_coords(blocks)
            if ok:
                self.blocks = blocks
                self._rebuild_from_raw()
                return

        # Пробуем альтернативы.
        current_name = self.delim.currentText()
        all_names = ["авто", "таб", "запятая", "точка с запятой", "пробел"]
        candidates = [n for n in all_names if n != current_name]

        best_name = None
        for name in candidates:
            if name == "авто":
                d = self._detect_delimiter(text)
            else:
                d = DELIMS.get(name)
            if d is None:
                continue

            b = self._parse_text(text, d)
            if not b:
                continue
            ok, _, _, _ = self._looks_like_coords(b)
            if ok:
                best_name = name
                break

        # Нашли альтернативу — спрашиваем пользователя.
        if best_name is not None:
            ans = QMessageBox.question(
                self,
                "Возможно, другой разделитель",
                f"Текущий разделитель «{current_name}» не подходит "
                f"для этих данных.\n\n"
                f"С разделителем «{best_name}» данные распознаются "
                f"как координаты.\n\n"
                f"Переключить разделитель на «{best_name}»?",
                _QMessageBox_Yes | _QMessageBox_No,
                _QMessageBox_Yes,
            )

            if ans == _QMessageBox_Yes:
                # Меняем разделитель без вызова _reload_from_source —
                # он бы снова дёрнул парсинг и получилась рекурсия.
                self.delim.blockSignals(True)
                i = self.delim.findText(best_name)
                if i >= 0:
                    self.delim.setCurrentIndex(i)
                self.delim.blockSignals(False)

                new_delim = self._current_delim()
                new_blocks = self._parse_text(text, new_delim)
                if new_blocks:
                    self.blocks = new_blocks
                    self._rebuild_from_raw()
                    return

        # Ничего не подошло — стандартные сообщения об ошибке.
        if not blocks:
            QMessageBox.warning(self, "Пусто", "Нет данных")
            self._source_text = ""
            return

        ok, num_cells, nonempty_cells, total_rows = self._looks_like_coords(blocks)
        QMessageBox.warning(
            self,
            "Не похоже на координаты",
            f"Загруженные данные ({source}) не похожи на таблицу "
            f"с координатами.\n\n"
            f"Строк: {total_rows}\n"
            f"Непустых ячеек: {nonempty_cells}\n"
            f"Из них чисел: {num_cells}\n\n"
            f"Проверьте разделитель и кодировку.\n\n"
            f"Ожидается таблица, где в каждой строке — точка, а в "
            f"колонках — числа.\n\n"
            f"Примеры:\n"
            f"  55.7244\t36.3638\n"
            f"  465457.47\t1305443.78\n"
            f"  55°43'28.05\"\t36°21'49.94\"\n"
            f"  55\t43\t28.05\t36\t21\t49.94",
        )
        self._source_text = ""

    def _reload_from_source(self):
        """Пересобирает таблицу при смене разделителя из сохранённого текста."""
        if not self._source_text:
            return
        delim = self._current_delim()
        blocks = self._parse_text(self._source_text, delim)
        if not blocks:
            self.blocks = []
            self.data_blocks = []
            self.rows = []
            self.headers = []
            self.preview.clear()
            self.preview.setRowCount(0)
            self.preview.setColumnCount(0)
            self.format_label.setText("Формат: —")
            self.headers_label.setText("Заголовки: —")
            self._clear_rubber()
            self._clear_temp_layer()
            try:
                self.map_canvas.refresh()
            except Exception as e:  # noqa: BLE001 — слот не должен ронять плагин
                _log_ignored_exception(e, "некритичная ошибка")
            return
        self.blocks = blocks
        self._rebuild_from_raw()

    def _looks_like_coords(self, blocks):
        """Проверка "похоже ли содержимое на координаты".

        Возвращает (ok, число_числовых_ячеек, число_непустых_ячеек, число_строк).
        Критерий: минимум NUM_MIN чисел и доля чисел среди непустых
        ячеек не ниже NUM_RATIO_MIN.
        """
        num_cells = 0
        nonempty_cells = 0
        total_rows = 0
        for block in blocks:
            for r in block:
                row_nonempty = 0
                for c in r:
                    if str(c).strip():
                        row_nonempty += 1
                        nonempty_cells += 1
                        if _is_num_or_hms(c):
                            num_cells += 1
                if row_nonempty > 0:
                    total_rows += 1

        if nonempty_cells == 0:
            return False, 0, 0, total_rows

        ok = num_cells >= NUM_MIN and num_cells / nonempty_cells >= NUM_RATIO_MIN
        return ok, num_cells, nonempty_cells, total_rows

    def _detect_headers(self):
        """Определяет, есть ли заголовки в первой строке.

        Логика: если чисел в первой строке заметно меньше, чем
        в среднем по первым строкам данных — считаем её заголовком.
        """
        if not self.blocks:
            return False
        first_block = self.blocks[0]
        if not first_block:
            return False
        first = first_block[0]

        data_all = list(first_block[1:])
        for b in self.blocks[1:]:
            data_all.extend(b)

        if not data_all:
            for c in first:
                s = str(c).strip()
                if s and not _is_num_or_hms(s):
                    return True
            return False

        data_rows = data_all[:6]

        def count_num(r):
            return sum(1 for c in r if _is_num_or_hms(str(c)))

        def count_nonempty(r):
            return sum(1 for c in r if str(c).strip())

        f_ne = count_nonempty(first)
        if f_ne == 0:
            return False

        data_num_counts = [count_num(r) for r in data_rows if count_nonempty(r) > 0]
        if not data_num_counts:
            return False
        avg_data = sum(data_num_counts) / len(data_num_counts)

        f_num = count_num(first)
        return f_num < avg_data

    def _rebuild_from_raw(self):
        """Пересобирает всё после разбора.

        Что делает:
            - отделяет заголовки;
            - применяет диапазон строк;
            - сохраняет границы блоков;
            - определяет формат и единицы;
            - перестраивает колонки, подписи, таблицу, карту, плашку СК.
        """
        if not self.blocks:
            return

        has_headers = self._detect_headers()

        if has_headers:
            self.headers = list(self.blocks[0][0])
            data_blocks = []
            for bi, b in enumerate(self.blocks):
                if bi == 0:
                    bb = list(b[1:])
                    if bb:
                        data_blocks.append(bb)
                else:
                    data_blocks.append(list(b))
        else:
            n = max(len(r) for b in self.blocks for r in b)
            self.headers = [f"col{i + 1}" for i in range(n)]
            data_blocks = [list(b) for b in self.blocks]

        self.headers_label.setText(
            "Заголовки: есть" if has_headers else "Заголовки: нет"
        )

        flat = []
        for bi, b in enumerate(data_blocks):
            for r in b:
                flat.append((bi, r))

        s = self.start_line.value() - 1
        e = self.end_line.value()
        flat = flat[s:e] if e > 0 else flat[s:]

        new_blocks = []
        cur_bi = None
        cur = []
        for bi, r in flat:
            if bi != cur_bi:
                if cur:
                    new_blocks.append(cur)
                cur = []
                cur_bi = bi
            cur.append(r)
        if cur:
            new_blocks.append(cur)

        self.data_blocks = new_blocks
        self.rows = [r for b in self.data_blocks for r in b]

        self.detected_format = self._detect_format()
        units = self._current_units()
        units_ru = "градусы" if units == "degrees" else "метры"
        self.format_label.setText(
            f"Формат: {FMT_LABELS[self.detected_format]} ({units_ru})"
        )

        idx = {FMT_DECIMAL: 0, FMT_HMS_ONE: 1, FMT_HMS_THREE: 2}[self.detected_format]
        self.coord_stack.setCurrentIndex(idx)

        self._fill_column_combos()
        self._auto_map_columns()
        self._update_axis_visibility()
        self._update_axis_labels()
        self._update_crs_warning()
        self._fill_preview()
        self._update_map_preview()

    def _cell(self, row, idx):
        """Безопасно берёт значение ячейки. Нет индекса — ''."""
        return row[idx] if 0 <= idx < len(row) else ""

    def _detect_format(self):
        """Определяет формат координат по данным.

        1. Есть '°' → ГМС в одной колонке.
        2. Шесть числовых колонок и валидные минуты/секунды → ГМС в трёх.
        3. Иначе — десятичные.
        """
        if not self.rows:
            return FMT_DECIMAL
        for r in self.rows[:10]:
            for cell in r:
                if "°" in str(cell):
                    return FMT_HMS_ONE

        num_cols = self._find_numeric_columns()
        if len(num_cols) >= 6:
            r = self.rows[0]
            vals = [_num(self._cell(r, c)) for c in num_cols[:6]]
            if all(v is not None for v in vals):
                _, m1, s1, _, m2, s2 = vals
                if 0 <= m1 < 60 and 0 <= s1 < 60 and 0 <= m2 < 60 and 0 <= s2 < 60:
                    return FMT_HMS_THREE
        return FMT_DECIMAL

    def _current_units(self):
        """Возвращает 'degrees' или 'meters'.

        Для пространственного входа — по СК файла.
        Для ГМС — всегда градусы.
        Для десятичного текста — по модулю значений.
        """
        if self._is_spatial_input and self.spatial_data:
            crs = self.spatial_data[0]["layer"].crs()
            if crs and crs.isValid() and crs.isGeographic():
                return "degrees"
            return "meters"

        if self.detected_format in (FMT_HMS_ONE, FMT_HMS_THREE):
            return "degrees"
        return self._detect_units()

    def _detect_units(self):
        """Определяет единицы по величине чисел в первых строках.

        Порог — 180. Всё, что больше по модулю, уже не может быть
        широтой/долготой, значит метры.
        """
        if not self.rows:
            return "meters"
        num_cols = self._find_numeric_columns()
        if not num_cols:
            return "meters"
        sample = self.rows[: min(20, len(self.rows))]
        max_abs = 0.0
        for r in sample:
            for j in num_cols[:2]:
                v = _num(self._cell(r, j))
                if v is not None and abs(v) > max_abs:
                    max_abs = abs(v)
        return "degrees" if max_abs <= 180 else "meters"

    def _find_numeric_columns(self):
        """Индексы колонок, где ≥70% значений — числа."""
        if not self.rows:
            return []
        n = max(len(r) for r in self.rows[:10])
        sample = self.rows[: min(10, len(self.rows))]
        cols = []
        for j in range(n):
            ok = tot = 0
            for r in sample:
                if j < len(r):
                    tot += 1
                    if _num(r[j]) is not None:
                        ok += 1
            if tot and ok / tot >= 0.7:
                cols.append(j)
        return cols

    def _find_hms_one_columns(self):
        """Индексы колонок, где ≥70% значений — валидные ГМС."""
        if not self.rows:
            return []
        n = max(len(r) for r in self.rows[:10])
        sample = self.rows[: min(10, len(self.rows))]
        cols = []
        for j in range(n):
            ok = tot = 0
            for r in sample:
                if j < len(r):
                    tot += 1
                    val, _ = parse_hms_one(r[j])
                    if val is not None:
                        ok += 1
            if tot and ok / tot >= 0.7:
                cols.append(j)
        return cols

    def _fill_column_combos(self):
        """Наполняет все выпадашки колонок актуальными именами."""
        combos = [
            self.x_combo,
            self.y_combo,
            self.c1_combo,
            self.c2_combo,
            self.c1d,
            self.c1m,
            self.c1s,
            self.c2d,
            self.c2m,
            self.c2s,
            self.vnum_col_combo,
        ]
        for c in combos:
            c.blockSignals(True)
            c.clear()
            c.addItem("—")
            for h in self.headers:
                c.addItem(h)
            c.blockSignals(False)
            c.setMinimumContentsLength(COL_COMBO_MIN_CHARS)
            c.setSizeAdjustPolicy(COL_COMBO_POLICY)
            c.view().setMinimumWidth(c.fontMetrics().horizontalAdvance("—" * 4))
            c.updateGeometry()
        # Восстанавливаем ранее выбранную колонку для номеров.
        if hasattr(self, "_saved_vnum_col") and self._saved_vnum_col:
            i = self.vnum_col_combo.findText(self._saved_vnum_col)
            if i >= 0:
                self.vnum_col_combo.setCurrentIndex(i)

    def _auto_map_columns(self):
        """Автоматически привязывает колонки по формату.

        Десятичные — первые две числовые колонки.
        ГМС одна — первые две колонки с валидными ГМС.
        ГМС три — шесть подряд числовых колонок.
        """
        if self.detected_format == FMT_DECIMAL:
            num = self._find_numeric_columns()
            if len(num) >= 2:
                self.x_combo.setCurrentIndex(num[0] + 1)
                self.y_combo.setCurrentIndex(num[1] + 1)

        elif self.detected_format == FMT_HMS_ONE:
            cols = self._find_hms_one_columns()
            if len(cols) >= 2:
                self.c1_combo.setCurrentIndex(cols[0] + 1)
                self.c2_combo.setCurrentIndex(cols[1] + 1)

        elif self.detected_format == FMT_HMS_THREE:
            num = self._find_numeric_columns()
            if len(num) >= 6:
                self.c1d.setCurrentIndex(num[0] + 1)
                self.c1m.setCurrentIndex(num[1] + 1)
                self.c1s.setCurrentIndex(num[2] + 1)
                self.c2d.setCurrentIndex(num[3] + 1)
                self.c2m.setCurrentIndex(num[4] + 1)
                self.c2s.setCurrentIndex(num[5] + 1)

    def _col_index(self, combo):
        """Индекс выбранной колонки. -1, если не выбрана."""
        i = combo.currentIndex()
        return i - 1 if i > 0 else -1

    def _get_xy(self, row):
        """Главная функция разбора одной строки.

        Возвращает пару в порядке QGIS:
            (east, north) — для метров,
            (lon, lat)    — для градусов.

        Возбуждает ValueError с понятным сообщением при любой проблеме.
        """
        fmt = self.detected_format

        # --- Десятичные ---
        if fmt == FMT_DECIMAL:
            xi = self._col_index(self.x_combo)
            yi = self._col_index(self.y_combo)
            if xi < 0 or yi < 0:
                raise ValueError("не выбраны колонки координат")
            r1 = self._cell(row, xi)
            r2 = self._cell(row, yi)
            v1 = _num(r1)
            v2 = _num(r2)
            if v1 is None:
                raise ValueError(f"Коорд.1 = {r1!r} — не число")
            if v2 is None:
                raise ValueError(f"Коорд.2 = {r2!r} — не число")

            units = self._current_units()
            if units == "degrees":
                if self.order_combo.currentText().startswith("Широта"):
                    lat, lon = v1, v2
                else:
                    lat, lon = v2, v1
                return lon, lat
            else:
                if self.axes_combo.currentText().startswith("Восток"):
                    east, north = v1, v2
                else:
                    north, east = v1, v2
                return east, north

        # --- ГМС в одной колонке ---
        if fmt == FMT_HMS_ONE:
            i1 = self._col_index(self.c1_combo)
            i2 = self._col_index(self.c2_combo)
            if i1 < 0 or i2 < 0:
                raise ValueError("не выбраны колонки координат")
            v1 = self._cell(row, i1)
            v2 = self._cell(row, i2)
            a, err = parse_hms_one(v1)
            if a is None:
                raise ValueError(f"Коорд.1 = {v1!r}: {err}")
            b, err = parse_hms_one(v2)
            if b is None:
                raise ValueError(f"Коорд.2 = {v2!r}: {err}")
            if self.order_combo.currentText().startswith("Широта"):
                lat, lon = a, b
            else:
                lat, lon = b, a
            return lon, lat

        # --- ГМС в трёх колонках ---
        if fmt == FMT_HMS_THREE:
            cols = [
                self._col_index(self.c1d),
                self._col_index(self.c1m),
                self._col_index(self.c1s),
                self._col_index(self.c2d),
                self._col_index(self.c2m),
                self._col_index(self.c2s),
            ]
            if any(c < 0 for c in cols):
                raise ValueError("не все колонки ГМС выбраны")
            vals = [self._cell(row, c) for c in cols]
            nums = [_num(v) for v in vals]
            for i, v in enumerate(vals):
                if nums[i] is None:
                    raise ValueError(f"Коорд.{i + 1} = {v!r} — не число")
            a, err = _hms_to_dec(nums[0], nums[1], nums[2])
            if a is None:
                raise ValueError(f"Коорд.1: {err}")
            b, err = _hms_to_dec(nums[3], nums[4], nums[5])
            if b is None:
                raise ValueError(f"Коорд.2: {err}")
            if self.order_combo.currentText().startswith("Широта"):
                lat, lon = a, b
            else:
                lat, lon = b, a
            return lon, lat

        raise ValueError("неизвестный формат координат")

    def _display_values(self, east_or_lon, north_or_lat):
        """Приводит (east, north)/(lon, lat) к порядку отображения."""
        labels = self._axis_labels()
        units = self._current_units()
        if units == "degrees":
            lon, lat = east_or_lon, north_or_lat
            if labels[0] == "Широта":
                return lat, lon
            else:
                return lon, lat
        else:
            east, north = east_or_lon, north_or_lat
            if labels[0] == "Север":
                return north, east
            else:
                return east, north

    def _fill_spatial_preview_table(self):
        """Показывает объекты из пространственного файла в таблице.

        Одна строка = одна вершина. Объект идентифицируется
        колонкой «№» — строки с одинаковым номером принадлежат
        одному объекту.

        Колонки:
            № — номер объекта;
            №верш — номер вершины внутри объекта;
            Тип — Точка / Линия / Полигон;
            Коорд.1 / Коорд.2 — координаты вершины
                (Широта/Долгота или Север/Восток — по СК файла);
            Площадь / Периметр / Длина — заполняются только в
                первой строке объекта, чтобы не дублировать
                одно и то же значение в каждой вершине.

        Лимит вершин:
            Если у объекта больше MAX_VERTICES_PER_OBJECT вершин —
            показываются первые MAX_VERTICES_PER_OBJECT, а вместо
            остальных идёт серая строка «... скрыто вершин: N ...».
            Так видны все объекты, даже если один из них очень
            длинный. Полный набор вершин можно посмотреть после
            импорта в атрибутах слоя.

        Координаты показываются в порядке Y, X (как принято в
        геодезии), а не X, Y — так пользователю привычнее.
        """
        self.preview.blockSignals(True)
        self.preview.clear()

        # Единицы и подписи колонок — по СК файла.
        crs = self.spatial_data[0]["layer"].crs()
        is_geo = crs.isGeographic() if crs and crs.isValid() else False
        if is_geo:
            c1_label, c2_label = "Широта", "Долгота"
        else:
            c1_label, c2_label = "Север", "Восток"

        headers = [
            "№",
            "№верш",
            "Тип",
            c1_label,
            c2_label,
            "Площадь, м²",
            "Площадь, га",
            "Периметр/длина, м",
        ]
        self.preview.setColumnCount(len(headers))
        self.preview.setHorizontalHeaderLabels(headers)

        units = self._current_units()

        # display — список строк для таблицы. Обычная строка — это
        # кортеж с данными. Строка-заглушка — ('skipped', count).
        display = []
        num = 0

        for part in self.spatial_data:
            base = QgsWkbTypes.geometryType(part["wkb"])
            if base == _QgsWkbTypesGeom_Point:
                type_label = "Точка"
            elif base == _QgsWkbTypesGeom_Line:
                type_label = "Линия"
            else:
                type_label = "Полигон"

            # Между группами разных типов (точки/линии/полигоны)
            # ставим серый разделитель, если это не первая группа.
            if display:
                display.append(("divider",))

            for f in part["features"]:
                num += 1
                g = f.geometry()
                if g is None or g.isEmpty():
                    continue

                # Все вершины объекта плоским списком.
                verts = list(self._iter_vertices(g))
                if not verts:
                    continue

                # Свойства объекта — считаем один раз.
                if base == _QgsWkbTypesGeom_Polygon:
                    area_m2 = _geom_area_m2(g, units)
                    area_ha = area_m2 / 10000.0
                    per_m = _geom_length_m(g, units)
                    props = (f"{area_m2:.2f}", f"{area_ha:.4f}", f"{per_m:.2f}")
                elif base == _QgsWkbTypesGeom_Line:
                    length_m = _geom_length_m(g, units)
                    props = ("", "", f"{length_m:.2f}")
                else:
                    props = ("", "", "")

                # Сколько вершин показывать и сколько скрыть.
                show_count = min(len(verts), MAX_VERTICES_PER_OBJECT)
                hidden = len(verts) - show_count

                for vi in range(show_count):
                    v = verts[vi]
                    c1_s = self._fmt_value(v.y())
                    c2_s = self._fmt_value(v.x())

                    if vi == 0:
                        # Первая вершина — с площадью и периметром.
                        display.append(
                            (
                                str(num),
                                "1",
                                type_label,
                                c1_s,
                                c2_s,
                                props[0],
                                props[1],
                                props[2],
                            )
                        )
                    else:
                        # Остальные вершины — только координаты.
                        display.append(
                            (str(num), str(vi + 1), type_label, c1_s, c2_s, "", "", "")
                        )

                # Если объект длинный — добавим строку-заглушку.
                if hidden > 0:
                    display.append(("skipped", hidden))

        # --- Отрисовка ---
        self.preview.setRowCount(len(display))
        self.preview.setUpdatesEnabled(False)

        for i, row_data in enumerate(display):
            # Серая строка-разделитель между группами типов.
            if (
                isinstance(row_data, tuple)
                and len(row_data) == 1
                and row_data[0] == "divider"
            ):
                for j in range(len(headers)):
                    item = QTableWidgetItem("———")
                    item.setBackground(QColor(225, 225, 225))
                    self.preview.setItem(i, j, item)
                continue

            # Строка «... скрыто вершин: N ...».
            if (
                isinstance(row_data, tuple)
                and len(row_data) == 2
                and row_data[0] == "skipped"
            ):
                count = row_data[1]
                item = QTableWidgetItem(f"... скрыто вершин: {count} ...")
                item.setBackground(QColor(240, 240, 240))
                item.setForeground(QColor(120, 120, 120))
                self.preview.setItem(i, 0, item)
                self.preview.setSpan(i, 0, 1, len(headers))
                continue

            # Обычная строка с данными.
            for j, val in enumerate(row_data):
                self.preview.setItem(i, j, QTableWidgetItem(str(val)))

        self.preview.setUpdatesEnabled(True)

        # Фиксированная ширина колонок — чтобы не тормозить
        # на больших объектах.
        for j in range(len(headers)):
            self.preview.setColumnWidth(j, 110)

        self.preview.blockSignals(False)

    def _fill_preview(self):
        """Обновляет таблицу предпросмотра (единый вид).

        Колонки: исходные | → № | → №верш | → Тип | → Коорд1 | → Коорд2 |
                 → Площадь м² | → Площадь га | → Периметр/длина м.

        Особенность:
            Показываются не все вершины, а не больше MAX_VERTICES_PER_OBJECT
            на каждый объект. Если вершин больше — вместо остальных
            выводится строка «... ещё N вершин скрыто ...».
        """
        self.preview.blockSignals(True)
        self.preview.clear()

        valid_vnum = self._validate_vnum()

        parsed_blocks = []
        for block in self.data_blocks:
            pblock = []
            for row in block:
                try:
                    x, y = self._get_xy(row)
                    pblock.append((x, y, row))
                except ValueError:
                    pblock.append((0, 0, row))
            parsed_blocks.append(pblock)

        wkb = GEOM_WKB[self.geom_combo.currentText()]
        meta, _ = self._calculate_meta(parsed_blocks, wkb)

        objects_data = self._build_objects_data(parsed_blocks, wkb)
        row_to_obj = {}
        for ob in objects_data:
            for r in ob["rows"]:
                row_to_obj[id(r)] = ob

        # --- Собираем объекты (группировка по obj_num) ---
        ordered_objects = []
        current_obj = []
        last_obj_num = None

        for bi, block in enumerate(self.data_blocks):
            for ri, r in enumerate(block):
                obj_info = meta.get((bi, ri))
                # Пропускаем замыкающие точки полигонов: их нет в meta,
                # потому что _split_polygon_points их отбрасывает.
                if obj_info is None:
                    continue
                obj_num = obj_info[0]

                if last_obj_num is not None and obj_num != last_obj_num:
                    if current_obj:
                        ordered_objects.append(current_obj)
                    current_obj = []

                current_obj.append((bi, ri))
                last_obj_num = obj_num

        if current_obj:
            ordered_objects.append(current_obj)

        # --- Формируем display с лимитом вершин на объект ---
        display = []
        self._preview_map = []

        for i, obj_rows in enumerate(ordered_objects):
            if i > 0:
                display.append(None)
                self._preview_map.append(None)

            if len(obj_rows) <= MAX_VERTICES_PER_OBJECT:
                for loc in obj_rows:
                    display.append(loc)
                    self._preview_map.append(loc)
            else:
                for loc in obj_rows[:MAX_VERTICES_PER_OBJECT]:
                    display.append(loc)
                    self._preview_map.append(loc)
                # Маркер пропуска. Хранится как спец-кортеж.
                display.append(("skipped", len(obj_rows) - MAX_VERTICES_PER_OBJECT))
                self._preview_map.append(None)

        labels = self._axis_labels()
        headers = list(self.headers) + [
            "→ №",
            "→ №верш",
            "→ Тип",
            f"→ {labels[0]}",
            f"→ {labels[1]}",
            "→ Площадь, м²",
            "→ Площадь, га",
            "→ Периметр/длина, м",
        ]
        self.preview.setColumnCount(len(headers))
        self.preview.setHorizontalHeaderLabels(headers)

        self.preview.setRowCount(len(display))
        self.preview.setUpdatesEnabled(False)

        for i, loc in enumerate(display):
            if loc is None:
                for j in range(len(headers)):
                    item = QTableWidgetItem("———")
                    item.setBackground(QColor(225, 225, 225))
                    self.preview.setItem(i, j, item)
                continue

            if isinstance(loc, tuple) and len(loc) == 2 and loc[0] == "skipped":
                count = loc[1]
                item = QTableWidgetItem(f"... скрыто вершин: {count} ...")
                item.setBackground(QColor(240, 240, 240))
                item.setForeground(QColor(120, 120, 120))
                self.preview.setItem(i, 0, item)
                self.preview.setSpan(i, 0, 1, len(headers))
                continue

            bi, ri = loc
            row = self.data_blocks[bi][ri]

            for j in range(len(self.headers)):
                val = self._cell(row, j)
                self.preview.setItem(i, j, QTableWidgetItem(str(val)))

            try:
                e_or_lon, n_or_lat = self._get_xy(row)
                v1, v2 = self._display_values(e_or_lon, n_or_lat)

                if valid_vnum:
                    obj_num, vnum_str, type_str = meta.get((bi, ri), ("?", "?", "?"))
                else:
                    obj_num, vnum_str, type_str = "?", "?", "?"

                ob = row_to_obj.get(id(row))
                is_first = False
                if ob and ob["rows"] and ob["rows"][0] is row:
                    is_first = True

                area_m2_s = (
                    f"{ob.get('area_m2', 0):.2f}"
                    if is_first and "area_m2" in ob
                    else ""
                )
                area_ha_s = (
                    f"{ob.get('area_ha', 0):.4f}"
                    if is_first and "area_ha" in ob
                    else ""
                )
                length_s = (
                    f"{ob.get('perimeter_m', 0):.2f}"
                    if is_first and "perimeter_m" in ob
                    else ""
                )
                if is_first and "length_m" in ob:
                    length_s = f"{ob['length_m']:.2f}"

                items = [
                    QTableWidgetItem(str(obj_num)),
                    QTableWidgetItem(str(vnum_str)),
                    QTableWidgetItem(str(type_str)),
                    QTableWidgetItem(self._fmt_value(v1)),
                    QTableWidgetItem(self._fmt_value(v2)),
                    QTableWidgetItem(area_m2_s),
                    QTableWidgetItem(area_ha_s),
                    QTableWidgetItem(length_s),
                ]
                for j, item in enumerate(items):
                    item.setFlags(item.flags() & ~_QT_ITEM_EDITABLE)
                    self.preview.setItem(i, len(self.headers) + j, item)
            except (ValueError, TypeError, AttributeError, KeyError):
                for j in range(8):
                    item = QTableWidgetItem("—")
                    item.setFlags(item.flags() & ~_QT_ITEM_EDITABLE)
                    self.preview.setItem(i, len(self.headers) + j, item)

        self.preview.setUpdatesEnabled(True)

        # Ширина колонок — фиксированная, чтобы не тормозить на больших данных.
        for j in range(len(headers)):
            self.preview.setColumnWidth(j, 100)

        self.preview.blockSignals(False)

    # --------------------------------------------------------
    # Контекстное меню таблицы предпросмотра
    # --------------------------------------------------------
    def _on_preview_context_menu(self, pos):
        """Показывает меню по правой кнопке в таблице предпросмотра.

        Пункты:
            Копировать       — выделенные ячейки в буфер (TSV).
            Добавить строку  — вставить пустую строку после текущей.
            Удалить строку   — удалить текущую строку.

        Правки идут в self.data_blocks — источник данных. После
        изменения таблица и превью-карта пересобираются.
        """
        if not self.data_blocks:
            return

        index = self.preview.indexAt(pos)
        preview_row = index.row() if index.isValid() else -1

        is_data_row = (
            0 <= preview_row < len(self._preview_map)
            and self._preview_map[preview_row] is not None
        )

        menu = QMenu(self)
        act_copy = menu.addAction("Копировать")
        act_add = menu.addAction("Добавить строку")
        act_del = menu.addAction("Удалить строку")

        act_copy.setEnabled(preview_row >= 0)
        act_add.setEnabled(is_data_row)
        act_del.setEnabled(is_data_row)

        chosen = menu.exec(self.preview.viewport().mapToGlobal(pos))
        if chosen is None:
            return

        if chosen == act_copy:
            self._preview_copy()
        elif chosen == act_add:
            self._preview_add_row(preview_row)
        elif chosen == act_del:
            self._preview_delete_row(preview_row)

    def _on_preview_item_changed(self, item):
        """Записывает отредактированное значение ячейки обратно в данные.
        ...
        """
        if item is None:
            return

        row = item.row()
        col = item.column()

        if col >= len(self.headers):
            return  # вычисленные колонки только для чтения

        # Колонка должна быть из исходных данных.
        if col < 0 or col >= len(self.headers):
            return

        if not (0 <= row < len(self._preview_map)):
            return
        loc = self._preview_map[row]
        if loc is None:
            return  # серая строка-разделитель

        bi, ri = loc
        if not (0 <= bi < len(self.data_blocks)):
            return
        if not (0 <= ri < len(self.data_blocks[bi])):
            return

        # Дополняем строку до длины шапки, если была короче.
        block_row = self.data_blocks[bi][ri]
        while len(block_row) <= col:
            block_row.append("")

        block_row[col] = item.text()

        # Плоский список строк — для _get_xy и повторных парсингов.
        self.rows = [r for b in self.data_blocks for r in b]

        # Обновляем предупреждение о СК и карту.
        self._update_crs_warning()
        self._update_map_preview()

    def _preview_copy(self):
        """Копирует выделенные ячейки в буфер обмена.

        Собирает TSV-фрагмент (значения через таб, строки через
        перевод строки) — такой формат понимают Excel и LibreOffice.
        """
        sel = self.preview.selectionModel().selectedIndexes()
        if not sel:
            return

        rows = sorted({i.row() for i in sel})
        cols = sorted({i.column() for i in sel})

        lines = []
        for r in rows:
            vals = []
            for c in cols:
                item = self.preview.item(r, c)
                vals.append(item.text() if item is not None else "")
            lines.append("\t".join(vals))

        QApplication.clipboard().setText("\n".join(lines))

    def _preview_add_row(self, preview_row):
        """Вставляет пустую строку после указанной.

        Новая строка содержит столько же пустых ячеек, сколько колонок
        в шапке. Данные в неё пользователь вводит вручную.
        """
        if not (0 <= preview_row < len(self._preview_map)):
            return
        loc = self._preview_map[preview_row]
        if loc is None:
            return

        bi, ri = loc
        empty = [""] * len(self.headers)
        self.data_blocks[bi].insert(ri + 1, empty)
        self._rebuild_after_edit()

    def _preview_delete_row(self, preview_row):
        """Удаляет указанную строку из данных.

        Если после удаления блок становится пустым — он тоже убирается,
        чтобы не создавать пустой объект на карте.
        """
        if not (0 <= preview_row < len(self._preview_map)):
            return
        loc = self._preview_map[preview_row]
        if loc is None:
            return

        bi, ri = loc
        if not (0 <= bi < len(self.data_blocks)):
            return
        if not (0 <= ri < len(self.data_blocks[bi])):
            return

        del self.data_blocks[bi][ri]
        if not self.data_blocks[bi]:
            del self.data_blocks[bi]

        self._rebuild_after_edit()

    def _rebuild_after_edit(self):
        """Пересобирает таблицу и превью-карту после ручного редактирования.

        Полная пересборка через _rebuild_from_raw не делается: она бы
        сбросила ручную привязку колонок. Здесь достаточно обновить
        плоский список строк и перерисовать оба превью.
        """
        self.rows = [r for b in self.data_blocks for r in b]
        self._update_crs_warning()
        self._fill_preview()
        self._update_map_preview()

    # --------------------------------------------------------
    # Проверка системы координат
    # --------------------------------------------------------
    def _check_crs(self):
        """Проверяет выбранную СК: валидность и согласованность единиц.

        Уровень 1 — СК разбирается QGIS. Блокирует импорт.
        Уровень 2 — единицы данных и тип СК не противоречат друг другу.
                    Предупреждение с возможностью продолжить.

        Возвращает True, если можно продолжать импорт, и False — если
        пользователь отказался или СК невалидна.
        """
        crs = self.crs_widget.crs()

        # --- Уровень 1: СК валидна ---
        if not crs.isValid():
            self.crs_frame.setStyleSheet(ERROR_STYLE_FRAME)
            QMessageBox.warning(
                self,
                "Неверная система координат",
                "Выбранная система координат не распознана QGIS.\n\n"
                "Проверьте выбор исходной СК — откройте список и укажите "
                "правильную. Если ваша СК отсутствует в списке, добавьте "
                "её через «Настройки → Свои СК» и выберите здесь.",
            )
            return False

        # --- Уровень 2: согласованность единиц ---
        units = self._current_units()
        crs_is_geographic = crs.isGeographic()

        warn = None
        if units == "degrees" and not crs_is_geographic:
            warn = (
                "Данные похожи на градусы (значения ≤ 180), "
                "а выбранная СК — проекционная (в метрах).\n\n"
                "Возможно, выбранная СК не подходит.\n\n"
                "Продолжить импорт?"
            )
        elif units == "meters" and crs_is_geographic:
            warn = (
                "Данные похожи на метры (значения > 180), "
                "а выбранная СК — географическая (в градусах).\n\n"
                "Возможно, выбранная СК не подходит.\n\n"
                "Продолжить импорт?"
            )

        if warn:
            ans = QMessageBox.question(
                self,
                "Проверьте систему координат",
                warn,
                _QMessageBox_Yes | _QMessageBox_No,
                _QMessageBox_No,
            )
            if ans != _QMessageBox_Yes:
                self.crs_frame.setStyleSheet(ERROR_STYLE_FRAME)
                return False

        return True

    # --------------------------------------------------------
    # Импорт
    # --------------------------------------------------------
    def on_import(self):
        """Собирает слой(и) и добавляет их в проект."""
        # --- Имя слоя ---
        layer_name = self.layer_name_edit.text().strip()
        if not layer_name:
            self.layer_name_edit.setStyleSheet(ERROR_STYLE_QLE)
            self.layer_name_edit.setFocus()
            self._show_name_warning()
            return

        # Пространственный вход — своя ветка импорта.
        if self._is_spatial_input:
            self._import_spatial(layer_name)
            return

        if not self.data_blocks:
            QMessageBox.warning(
                self, "Нет данных", "Сначала загрузи данные из буфера или файла"
            )
            return

        # --- Путь сохранения ---
        save_to_file = self.cb_save_file.isChecked()
        save_path = self.save_path_edit.text().strip()
        if save_to_file and not save_path:
            QMessageBox.warning(
                self,
                "Нет пути сохранения",
                "Укажите путь к .gpkg или снимите галочку «Сохранить в файл».",
            )
            return

        # --- Проверка СК (уровни 1 и 2) ---
        if not self._check_crs():
            return

        # Проверка нумерации вершин (если выбрано «Из колонки»).
        if not self._validate_vnum():
            return

        # --- Разбор строк ---
        errors = []
        parsed_blocks = []
        row_num = 0
        stop = False
        for block in self.data_blocks:
            pblock = []
            for row in block:
                row_num += 1
                try:
                    x, y = self._get_xy(row)
                    pblock.append((x, y, row))
                except ValueError as e:
                    errors.append((row_num, str(e)))
                    if len(errors) >= 10:
                        stop = True
                        break
            if stop:
                break
            parsed_blocks.append(pblock)

        if errors:
            msg = "Найдены ошибки в данных:\n\n"
            for n, e in errors:
                msg += f"• Строка {n}: {e}\n"
            if len(errors) >= 10:
                msg += "\n(показаны первые 10 ошибок)"
            msg += "\n\nШаблоны координат:\n"
            msg += "  • десятичные: 55.7244\t36.3638\n"
            msg += "  • ГМС одной колонкой: 55°43'28.05\"\t36°21'49.94\"\n"
            msg += "  • ГМС тремя колонками: 55\t43\t28.05\t36\t21\t49.94\n"
            msg += "\nИсправьте исходные данные и загрузите заново."
            QMessageBox.warning(self, "Ошибки в данных", msg)
            return

        if not any(parsed_blocks):
            QMessageBox.warning(self, "Пусто", "Не удалось построить ни одного объекта")
            return

        # --- Создание слоёв ---
        geom_name = self.geom_combo.currentText()
        wkb = GEOM_WKB[geom_name]
        uri_geom = GEOM_URI[geom_name]
        is_point = wkb == _QgsWkbTypesType_Point
        is_poly = wkb in (_QgsWkbTypesType_Polygon, _QgsWkbTypesType_MultiPolygon)

        want_vertices = self.cb_vertices.isChecked() and not is_point
        want_numbering = self.cb_numbering.isChecked()
        need_vertex_layer = (not is_point) and (want_vertices or want_numbering)

        crs = self.crs_widget.crs()

        main_layer = self._make_layer(uri_geom, crs, layer_name)
        feats, vertex_points = self._build_features(main_layer, wkb, parsed_blocks)
        if not feats:
            QMessageBox.warning(self, "Пусто", "Не удалось построить ни одного объекта")
            return
        self._fill_layer(main_layer, feats)

        final_main = main_layer

        if save_to_file:
            ok, err = self._save_layer_to_gpkg(main_layer, save_path, layer_name)
            if not ok:
                QMessageBox.critical(
                    self, "Ошибка сохранения", f"Не удалось сохранить слой:\n{err}"
                )
                return
            loaded = QgsVectorLayer(
                f"{save_path}|layername={layer_name}", layer_name, "ogr"
            )
            if loaded.isValid():
                final_main = loaded

        ds = self.display_settings
        if is_poly:
            _apply_polygon_style(
                final_main,
                self.poly_style.currentText(),
                outline_color=ds.get("poly_outline_color", QColor(0, 0, 0, 255)),
                outline_width=ds.get("poly_outline_width", 2) * 0.5,
                fill_color=ds.get("poly_fill_color", QColor(150, 150, 150, 128)),
            )
        if is_point and want_numbering:
            num_color = ds.get("num_label_color", QColor(0, 0, 0, 255))
            _enable_number_labels(
                final_main,
                color=f"{num_color.red()},{num_color.green()},"
                f"{num_color.blue()},{num_color.alpha()}",
                size=ds.get("num_label_size", 10),
            )

        QgsProject.instance().addMapLayer(final_main)

        # --- Слой вершин ---
        if need_vertex_layer and vertex_points:
            v_name = f"{layer_name} — вершины"
            v_layer = self._make_layer("Point", crs, v_name, vertex_only=True)
            v_feats = []
            for v_idx, pt in vertex_points:
                f = QgsFeature(v_layer.fields())
                f.setGeometry(QgsGeometry.fromPointXY(pt))
                f.setAttributes([v_idx, v_idx])
                v_feats.append(f)
            self._fill_layer(v_layer, v_feats)

            final_vertex = v_layer

            if save_to_file:
                ok, err = self._save_layer_to_gpkg(v_layer, save_path, v_name)
                if ok:
                    loaded = QgsVectorLayer(
                        f"{save_path}|layername={v_name}", v_name, "ogr"
                    )
                    if loaded.isValid():
                        final_vertex = loaded

            if want_numbering:
                _enable_number_labels(final_vertex)
            QgsProject.instance().addMapLayer(final_vertex)

        self.iface.messageBar().pushSuccess("Импорт", f"Готово. Объектов: {len(feats)}")
        self.accept()

    def _import_spatial(self, layer_name):
        """Импортирует объекты из пространственного файла.

        По каждому типу геометрии создаётся отдельный слой:
            <layer_name> — точки
            <layer_name> — линии
            <layer_name> — полигоны

        Все оригинальные атрибуты исходного файла переносятся в слой.
        Дополнительно добавляются наши расчётные поля:
            num, area_m2, area_ha, perimeter_m (для полигонов)
            num, length_m (для линий)
            num (для точек)
        """
        save_to_file = self.cb_save_file.isChecked()
        save_path = self.save_path_edit.text().strip()
        if save_to_file and not save_path:
            QMessageBox.warning(
                self,
                "Нет пути сохранения",
                "Укажите путь к .gpkg или снимите галочку «Сохранить в файл».",
            )
            return

        if not self.spatial_data:
            QMessageBox.warning(
                self, "Нет данных", "Сначала загрузи пространственный файл."
            )
            return

        crs = self.spatial_data[0]["layer"].crs()
        units = self._current_units()
        added = 0

        suffix_map = {
            _QgsWkbTypesGeom_Point: "точки",
            _QgsWkbTypesGeom_Line: "линии",
            _QgsWkbTypesGeom_Polygon: "полигоны",
        }

        # Разделяем на выходные слои по каждому типу.
        for idx, part in enumerate(self.spatial_data, 1):
            base = QgsWkbTypes.geometryType(part["wkb"])
            suffix = suffix_map.get(base, f"слой{idx}")
            out_name = f"{layer_name} — {suffix}"

            # Источник полей — держатель из _read_spatial_via_ogr.
            src_layer = part["layer"]
            src_fields = src_layer.fields()

            # Итоговый memory-слой с СК источника.
            wkb_str = QgsWkbTypes.displayString(part["wkb"])
            uri = f"{wkb_str}?crs={crs.authid()}"
            out = QgsVectorLayer(uri, out_name, "memory")
            op = out.dataProvider()

            # Копируем исходные поля.
            op.addAttributes([QgsField(f.name(), f.type()) for f in src_fields])

            # Добавляем наши расчётные поля поверх.
            op.addAttributes([QgsField("num", T_INT)])
            if base == _QgsWkbTypesGeom_Polygon:
                op.addAttributes(
                    [
                        QgsField("area_m2", T_DOUBLE),
                        QgsField("area_ha", T_DOUBLE),
                        QgsField("perimeter_m", T_DOUBLE),
                    ]
                )
            elif base == _QgsWkbTypesGeom_Line:
                op.addAttributes([QgsField("length_m", T_DOUBLE)])
            out.updateFields()

            num_src = len(src_fields)
            new_feats = []
            num = 0
            for f in part["features"]:
                g = f.geometry()
                if g is None or g.isEmpty():
                    continue
                num += 1

                nf = QgsFeature(out.fields())
                nf.setGeometry(QgsGeometry(g))

                # Исходные атрибуты + наши в нужном порядке.
                attrs = [f[i] for i in range(num_src)]
                attrs.append(num)
                if base == _QgsWkbTypesGeom_Polygon:
                    area_m2 = _geom_area_m2(g, units)
                    per_m = _geom_length_m(g, units)
                    attrs.extend([area_m2, area_m2 / 10000.0, per_m])
                elif base == _QgsWkbTypesGeom_Line:
                    attrs.append(_geom_length_m(g, units))
                nf.setAttributes(attrs)
                new_feats.append(nf)

            if not new_feats:
                continue
            op.addFeatures(new_feats)
            out.updateExtents()

            ds = self.display_settings
            # Стиль полигона.
            if base == _QgsWkbTypesGeom_Polygon:
                _apply_polygon_style(
                    out,
                    self.poly_style.currentText(),
                    outline_color=ds.get("poly_outline_color", QColor(0, 0, 0, 255)),
                    outline_width=ds.get("poly_outline_width", 2) * 0.5,
                    fill_color=ds.get("poly_fill_color", QColor(150, 150, 150, 128)),
                )

            # Подписи номеров — если включена нумерация.
            if self.cb_numbering.isChecked():
                num_color = ds.get("num_label_color", QColor(0, 0, 0, 255))
                _enable_number_labels(
                    out,
                    color=f"{num_color.red()},{num_color.green()},"
                    f"{num_color.blue()},{num_color.alpha()}",
                    size=ds.get("num_label_size", 10),
                )
            # Сохранение в GeoPackage.
            final = out
            if save_to_file:
                ok, _err = self._save_layer_to_gpkg(out, save_path, out_name)
                if ok:
                    loaded = QgsVectorLayer(
                        f"{save_path}|layername={out_name}", out_name, "ogr"
                    )
                    if loaded.isValid():
                        final = loaded

            QgsProject.instance().addMapLayer(final)
            added += 1

        if added == 0:
            QMessageBox.warning(self, "Пусто", "Не удалось собрать ни одного слоя.")
            return

        self.iface.messageBar().pushSuccess("Импорт", f"Добавлено слоёв: {added}")
        self.accept()

    def _make_layer(self, uri_geom, crs, name, vertex_only=False):
        """Создаёт пустой memory-слой с нужными атрибутами.

        Набор атрибутов зависит от типа геометрии:
            Point         — num, z
            LineString    — num, z, length_m
            Polygon/Multi — num, z, area_m2, area_ha, perimeter_m

        Слой вершин (vertex_only=True) получает только num и vertex.
        """
        uri = f"{uri_geom}?crs={crs.authid()}"
        layer = QgsVectorLayer(uri, name, "memory")
        prov = layer.dataProvider()

        if vertex_only:
            prov.addAttributes(
                [
                    QgsField("num", T_INT),
                    QgsField("vertex", T_STRING),  # поддерживает "A-12" и текст
                ]
            )
        elif uri_geom in ("Polygon", "MultiPolygon"):
            prov.addAttributes(
                [
                    QgsField("num", T_INT),
                    QgsField("z", T_DOUBLE),
                    QgsField("area_m2", T_DOUBLE),
                    QgsField("area_ha", T_DOUBLE),
                    QgsField("perimeter_m", T_DOUBLE),
                ]
            )
        elif uri_geom == "LineString":
            prov.addAttributes(
                [
                    QgsField("num", T_INT),
                    QgsField("z", T_DOUBLE),
                    QgsField("length_m", T_DOUBLE),
                ]
            )
        else:
            prov.addAttributes(
                [
                    QgsField("num", T_INT),
                    QgsField("z", T_DOUBLE),
                ]
            )

        layer.updateFields()
        return layer

    def _fill_layer(self, layer, feats):
        """Пакетно добавляет объекты в слой и обновляет охват."""
        prov = layer.dataProvider()
        prov.addFeatures(feats)
        layer.updateExtents()

    def _save_layer_to_gpkg(self, layer, path, layer_name):
        """Пишет слой в GeoPackage. Возвращает (успех, сообщение)."""
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = layer_name
        if os.path.exists(path):
            options.actionOnExistingFile = _QgsVectorFileWriter_Action
        try:
            res = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer, path, QgsProject.instance().transformContext(), options
            )
            err_code = res[0]
            if err_code != _QgsVectorFileWriter_Error:
                return False, str(res)
            return True, ""
        except Exception as e:  # noqa: BLE001 — QgsVectorFileWriter бросает всё
            return False, str(e)

    def _split_polygon_points(self, points):
        """Делит точки блока на подполигоны по повтору первой точки.

        points — список кортежей, где [0] и [1] — координаты.
        Возвращает список подсписков исходных кортежей.
        """
        groups = []
        current = []
        first_pt = None
        for item in points:
            x, y = item[0], item[1]
            pt = (round(x, 8), round(y, 8))
            if first_pt is None:
                first_pt = pt
                current = [item]
            elif pt == first_pt and len(current) >= 3:
                groups.append(current)
                current = []
                first_pt = None
            else:
                current.append(item)
        if len(current) >= 3:
            groups.append(current)
        return groups

    def _calculate_meta(self, parsed_blocks, wkb):
        """Вычисляет номера объектов и вершин для всех строк.

        Возвращает кортеж (meta, row_vnum):
            meta      — словарь (bi, ri) -> (obj_num, vnum_str, type_str)
            row_vnum  — словарь id(row) -> vnum_str
        """
        meta = {}
        row_vnum = {}
        obj_num = 1
        global_vnum = 1
        is_point = wkb == _QgsWkbTypesType_Point
        is_poly = wkb in (_QgsWkbTypesType_Polygon, _QgsWkbTypesType_MultiPolygon)
        is_line = wkb == _QgsWkbTypesType_LineString

        for bi, block in enumerate(parsed_blocks):
            if not block:
                continue

            if is_point:
                for ri, (x, y, row) in enumerate(block):
                    vnum_str = self._get_vertex_number(row, 1, global_vnum)
                    meta[(bi, ri)] = (obj_num, vnum_str, "Точка")
                    row_vnum[id(row)] = vnum_str
                    obj_num += 1
                    global_vnum += 1

            elif is_poly:
                # Для полигонов используем ту же разбивку, что и в _build_features.
                # Она отбрасывает замыкающие точки, поэтому они не попадут в meta.
                pts_xyz = [(x, y, row, ri) for ri, (x, y, row) in enumerate(block)]
                sub_groups = self._split_polygon_points(pts_xyz)

                for pts in sub_groups:
                    local_vnum = 1
                    for x, y, row, ri in pts:
                        vnum_str = self._get_vertex_number(row, local_vnum, global_vnum)
                        meta[(bi, ri)] = (obj_num, vnum_str, "Полигон")
                        row_vnum[id(row)] = vnum_str
                        local_vnum += 1
                        global_vnum += 1
                    obj_num += 1

            elif is_line:
                local_vnum = 1
                for ri, (x, y, row) in enumerate(block):
                    vnum_str = self._get_vertex_number(row, local_vnum, global_vnum)
                    meta[(bi, ri)] = (obj_num, vnum_str, "Линия")
                    row_vnum[id(row)] = vnum_str
                    local_vnum += 1
                    global_vnum += 1
                obj_num += 1

        return meta, row_vnum

    def _build_objects_data(self, parsed_blocks, wkb):
        """Собирает объекты (как в _build_features) и считает их свойства.

        Возвращает список словарей:
            {'obj_num': int, 'geom': QgsGeometry, 'rows': [row, ...],
             'area_m2': float, 'area_ha': float, 'perimeter_m': float,
             'length_m': float}
        Нужен для отображения площади/длины в таблице без дублирования.
        """
        objects = []
        units = self._current_units()
        is_poly = wkb in (_QgsWkbTypesType_Polygon, _QgsWkbTypesType_MultiPolygon)
        is_line = wkb == _QgsWkbTypesType_LineString

        if wkb == _QgsWkbTypesType_Point:
            for block in parsed_blocks:
                for x, y, row in block:
                    objects.append(
                        {
                            "obj_num": len(objects) + 1,
                            "geom": QgsGeometry.fromPointXY(QgsPointXY(x, y)),
                            "rows": [row],
                        }
                    )
            return objects

        obj_num = 0
        for block in parsed_blocks:
            if not block:
                continue
            pts_xyz = [(x, y, row) for x, y, row in block]

            if is_poly:
                sub_groups = self._split_polygon_points(pts_xyz)
            else:
                sub_groups = [pts_xyz]

            for pts in sub_groups:
                if is_line and len(pts) < 2:
                    continue
                if is_poly and len(pts) < 3:
                    continue

                ring = [QgsPointXY(x, y) for x, y, _ in pts]
                if is_line:
                    geom = QgsGeometry.fromPolylineXY(ring)
                elif is_poly:
                    geom = QgsGeometry.fromPolygonXY([ring])
                else:
                    geom = QgsGeometry.fromMultiPolygonXY([[ring]])

                if geom.isEmpty():
                    continue

                obj_num += 1
                ob = {"obj_num": obj_num, "geom": geom, "rows": [r for _, _, r in pts]}
                if is_poly:
                    a = _geom_area_m2(geom, units)
                    ob["area_m2"] = a
                    ob["area_ha"] = a / 10000.0
                    ob["perimeter_m"] = _geom_length_m(geom, units)
                elif is_line:
                    ob["length_m"] = _geom_length_m(geom, units)

                objects.append(ob)

        return objects

    def _build_features(self, layer, wkb, parsed_blocks):
        """Собирает объекты для основного слоя и список вершин."""
        feats = []
        vertex_points = []
        units = self._current_units()
        meta, row_vnum = self._calculate_meta(parsed_blocks, wkb)

        is_poly = wkb in (_QgsWkbTypesType_Polygon, _QgsWkbTypesType_MultiPolygon)
        is_line = wkb == _QgsWkbTypesType_LineString

        if wkb == _QgsWkbTypesType_Point:
            for bi, block in enumerate(parsed_blocks):
                for ri, (x, y, row) in enumerate(block):
                    obj_num, _, _ = meta.get((bi, ri), (1, "1", "Точка"))
                    f = QgsFeature(layer.fields())
                    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
                    f.setAttributes([obj_num, None])
                    feats.append(f)
            return feats, vertex_points

        obj_num = 0
        for block in parsed_blocks:
            if not block:
                continue
            pts_xyz = [(x, y, row) for x, y, row in block]

            if is_poly:
                sub_groups = self._split_polygon_points(pts_xyz)
            else:
                sub_groups = [pts_xyz]

            for pts in sub_groups:
                if wkb == _QgsWkbTypesType_LineString and len(pts) < 2:
                    continue
                if is_poly and len(pts) < 3:
                    continue

                ring = [QgsPointXY(x, y) for x, y, _ in pts]
                if wkb == _QgsWkbTypesType_LineString:
                    geom = QgsGeometry.fromPolylineXY(ring)
                elif wkb == _QgsWkbTypesType_Polygon:
                    geom = QgsGeometry.fromPolygonXY([ring])
                else:
                    geom = QgsGeometry.fromMultiPolygonXY([[ring]])

                if geom.isEmpty():
                    continue

                obj_num += 1
                f = QgsFeature(layer.fields())

                if is_poly:
                    area_m2 = _geom_area_m2(geom, units)
                    perimeter_m = _geom_length_m(geom, units)
                    area_ha = area_m2 / 10000.0
                    f.setAttributes([obj_num, None, area_m2, area_ha, perimeter_m])
                elif is_line:
                    length_m = _geom_length_m(geom, units)
                    f.setAttributes([obj_num, None, length_m])
                else:
                    f.setAttributes([obj_num, None])

                f.setGeometry(geom)
                feats.append(f)

                for x, y, row in pts:
                    vnum_str = row_vnum.get(id(row), "?")
                    vertex_points.append((vnum_str, QgsPointXY(x, y)))

        return feats, vertex_points
