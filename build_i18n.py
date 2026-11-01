"""build_i18n.py — извлечение строк, генерация .ts и .qm для KYB_import_coords.

Использование:
    python build_i18n.py --extract   # только извлечь строки
    python build_i18n.py             # извлечь + сгенерировать .ts + lrelease

Логика v2:
    Парсит dialog.py и plugin.py через AST. Находит:
      • QCoreApplication.translate("Ctx", "строка")
      • QCoreApplication.translate(ctx, "строка") где ctx="Ctx" в том же методе
      • _tr("строка") в plugin.py (обёртка с контекстом "plugin")
    Многострочные (конкатенация строк) — восстанавливаются корректно.
"""

import argparse
import ast
import glob
import importlib
import os
import shutil
import subprocess
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
I18N_DIR = os.path.join(PLUGIN_DIR, "i18n")
SOURCE_FILES = [
    os.path.join(PLUGIN_DIR, "dialog.py"),
    os.path.join(PLUGIN_DIR, "plugin.py"),
]
LANGUAGES = ["ru", "en", "de", "fr", "es", "it", "zh", "kk"]


def extract_from_ast(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    try:
        tree = ast.parse(content, filename=filepath)
    except SyntaxError as e:
        print(f"Синтаксическая ошибка в {filepath}: {e}")
        return []

    results = []
    filename = os.path.basename(filepath)

    def walk(node, var_ctx):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            new_ctx = {}
            for child in node.body:
                walk(child, new_ctx)
            return
        if isinstance(node, ast.Assign) and (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            var_ctx[node.targets[0].id] = node.value.value
        if isinstance(node, ast.Call):
            func = node.func
            is_qcapp_translate = False
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "translate"
                and (
                    (
                        isinstance(func.value, ast.Name)
                        and func.value.id == "QCoreApplication"
                    )
                    or (
                        isinstance(func.value, ast.Attribute)
                        and func.value.attr == "QCoreApplication"
                    )
                )
            ):
                is_qcapp_translate = True
            if is_qcapp_translate and len(node.args) >= 2:
                ctx_node, src_node = node.args[0], node.args[1]
                if isinstance(src_node, ast.Constant) and isinstance(
                    src_node.value, str
                ):
                    ctx = None
                    if isinstance(ctx_node, ast.Constant) and isinstance(
                        ctx_node.value, str
                    ):
                        ctx = ctx_node.value
                    elif isinstance(ctx_node, ast.Name):
                        ctx = var_ctx.get(ctx_node.id)
                    if ctx is not None:
                        results.append((ctx, src_node.value))
            elif (
                filename == "plugin.py"
                and isinstance(func, ast.Name)
                and func.id == "_tr"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                results.append(("plugin", node.args[0].value))
        for child in ast.iter_child_nodes(node):
            walk(child, var_ctx)

    walk(tree, {})
    return results


# Строки, которые AST не видит: подставляются из списков через
# переменную цикла (_geom_display(g), translate("KYB", s) и т. п.).
EXTRA_SOURCES = [
    ("KYB", "Многоконтурный полигон"),
    ("KYB", "Контур + заливка"),
    ("KYB", "авто"),
    ("KYB", "таб"),
    ("KYB", "запятая"),
    ("KYB", "точка с запятой"),
    ("KYB", "пробел"),
    ("KYB", "Авто (по объектам)"),
    ("KYB", "Авто (сквозная)"),
    ("KYB", "Из колонки"),
    ("KYB", "Широта, Долгота"),
    ("KYB", "Долгота, Широта"),
    ("KYB", "Север, Восток"),
    ("KYB", "Восток, Север"),
]


def extract_all():
    all_pairs = list(EXTRA_SOURCES)
    for f in SOURCE_FILES:
        all_pairs.extend(extract_from_ast(f))
    seen = set()
    unique = []
    for pair in all_pairs:
        if pair in seen:
            continue
        seen.add(pair)
        unique.append(pair)
    return unique


def write_strings_file():
    pairs = extract_all()
    os.makedirs(I18N_DIR, exist_ok=True)
    path = os.path.join(I18N_DIR, "strings_to_translate.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# Всего уникальных пар (ctx, source): {len(pairs)}\n")
        f.write("# Формат: CTX=... / SRC=... / ---\n\n")
        for ctx, src in pairs:
            f.write(f"CTX={ctx}\n")
            f.write(f"SRC={src}\n")
            f.write("---\n")
    return path, len(pairs)


def _escape(s):
    """Экранирует строку для XML-содержимого <source>/<translation>.

    XML использует &amp;, &lt;, &gt; для спецсимволов.
    \\n, \\t в тексте <translation> допустимы как есть.
    """
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def load_translations():
    path = os.path.join(PLUGIN_DIR, "translations_data.py")
    if not os.path.isfile(path):
        return {}
    sys.path.insert(0, PLUGIN_DIR)
    try:
        import translations_data

        importlib.reload(translations_data)
        return getattr(translations_data, "TRANSLATIONS", {})
    finally:
        sys.path.pop(0)


def write_ts(lang, translations):
    pairs = extract_all()
    by_ctx = {}
    for ctx, src in pairs:
        by_ctx.setdefault(ctx, []).append(src)

    path = os.path.join(I18N_DIR, f"plugin_{lang}.ts")
    with open(path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n')
        f.write("<!DOCTYPE TS>\n")
        f.write(f'<TS version="2.1" language="{lang}">\n')
        for ctx in sorted(by_ctx.keys()):
            f.write("  <context>\n")
            f.write(f"    <name>{ctx}</name>\n")
            for src in by_ctx[ctx]:
                esc_src = _escape(src)
                if lang == "ru":
                    trans = esc_src
                    attrs = ""
                else:
                    entry = translations.get(src, {})
                    tr = entry.get(lang)
                    if tr is None:
                        trans = ""
                        attrs = ' type="unfinished"'
                    else:
                        trans = _escape(tr)
                        attrs = ""
                f.write(f"    <message{attrs}>\n")
                f.write(f"      <source>{esc_src}</source>\n")
                f.write(f"      <translation>{trans}</translation>\n")
                f.write("    </message>\n")
            f.write("  </context>\n")
        f.write("</TS>\n")
    return path


def write_missing(translations):
    pairs = extract_all()
    missing = []
    seen = set()
    for _, src in pairs:
        if src in seen:
            continue
        seen.add(src)
        entry = translations.get(src, {})
        for lang in LANGUAGES:
            if lang == "ru":
                continue
            if not entry.get(lang):
                missing.append((src, lang))
                break
    if not missing:
        return None
    path = os.path.join(I18N_DIR, "missing_strings.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# Строк с неполным переводом: {len(missing)}\n\n")
        for src, lang in missing:
            f.write(f"LANG={lang}\nSRC={src}\n---\n")
    return path, len(missing)


def find_lrelease():
    # 1. В PATH
    for name in ("lrelease", "lrelease.exe", "lrelease-qt5", "lrelease-qt6"):
        p = shutil.which(name)
        if p:
            return p

    # 2. Рядом с текущим Python (если запуск из QGIS-консоли)
    exe_dir = os.path.dirname(sys.executable)
    for c in (
        os.path.join(exe_dir, "lrelease.exe"),
        os.path.join(exe_dir, "lrelease"),
        os.path.join(exe_dir, "..", "..", "bin", "lrelease.exe"),
        os.path.join(exe_dir, "..", "..", "bin", "lrelease"),
    ):
        if os.path.isfile(c):
            return os.path.abspath(c)

    # 3. Стандартные места установки QGIS / OSGeo4W (Windows)
    names = ("lrelease.exe", "lrelease-qt5.exe", "lrelease")
    known_dirs = [
        r"C:\Program Files\QGIS 3.44.12\apps\Qt5\bin",
        r"C:\Program Files\QGIS 3.44.12\bin",
        r"C:\Program Files\QGIS 3.44.12\apps\qgis-ltr\bin",
        r"C:\OSGeo4W\apps\Qt5\bin",
        r"C:\OSGeo4W\bin",
        r"C:\OSGeo4W64\apps\Qt5\bin",
        r"C:\OSGeo4W64\bin",
    ]
    for d in known_dirs:
        for n in names:
            c = os.path.join(d, n)
            if os.path.isfile(c):
                return os.path.abspath(c)

    # 4. Рекурсивный обход C:\Program Files\QGIS* (на случай другой версии)
    for pattern in (
        r"C:\Program Files\QGIS*\**\lrelease.exe",
        r"C:\Program Files (x86)\QGIS*\**\lrelease.exe",
        r"C:\OSGeo4W*\**\lrelease.exe",
    ):
        for c in glob.glob(pattern, recursive=True):
            return os.path.abspath(c)

    return None


def run_lrelease():
    exe = find_lrelease()
    if exe is None:
        print("\nlrelease не найден.")
        print("Варианты:")
        print("  1. Открой .ts в Qt Linguist → File → Release As .qm.")
        print("  2. Или в OSGeo4W Shell: lrelease i18n\\plugin_translation.pro")
        return False
    ok = True
    for lang in LANGUAGES:
        ts = os.path.join(I18N_DIR, f"plugin_{lang}.ts")
        qm = os.path.join(I18N_DIR, f"plugin_{lang}.qm")
        r = subprocess.run(
            [exe, ts, "-qm", qm], check=False, capture_output=True, text=True
        )
        if r.returncode != 0:
            print(f"  ОШИБКА lrelease {lang}: {r.stderr}")
            ok = False
        else:
            print(f"  OK: plugin_{lang}.qm")
    return ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--extract", action="store_true")
    args = parser.parse_args()

    os.makedirs(I18N_DIR, exist_ok=True)
    path, count = write_strings_file()
    print(f"Извлечено {count} уникальных пар (ctx, source) → {path}")

    if args.extract:
        return

    translations = load_translations()
    if not translations:
        print("\nВНИМАНИЕ: translations_data.py не найден.")
    else:
        print(f"Загружено переводов: {len(translations)} строк.")

    for lang in LANGUAGES:
        p = write_ts(lang, translations)
        print(f"  {os.path.basename(p)}")

    missing = write_missing(translations)
    if missing:
        p, n = missing
        print(f"\nСтрок с неполным переводом: {n} → {p}")

    run_lrelease()
    print("\nГотово.")


if __name__ == "__main__":
    main()
