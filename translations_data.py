"""translations_data.py — объединяет 4 части словаря переводов."""

from translations_data_p1 import TRANSLATIONS as _P1
from translations_data_p2 import TRANSLATIONS as _P2
from translations_data_p3 import TRANSLATIONS as _P3
from translations_data_p4 import TRANSLATIONS as _P4

TRANSLATIONS = {}
TRANSLATIONS.update(_P1)
TRANSLATIONS.update(_P2)
TRANSLATIONS.update(_P3)
TRANSLATIONS.update(_P4)
