"""Конвертирует HELP.md и HELP.ru.md в HELP.html и HELP_ru.html для QGIS."""

import os

try:
    import markdown
except ImportError:
    print("Установите библиотеку: pip install markdown")
    exit(1)


def convert(md_file, html_file):
    if not os.path.exists(md_file):
        print(f"❌ Файл {md_file} не найден.")
        return

    with open(md_file, encoding="utf-8") as f:
        md_text = f.read()

    # Конвертация с поддержкой таблиц
    html_text = markdown.markdown(md_text, extensions=["tables"])

    # Обёртка для красивого отображения в QGIS
    full_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: sans-serif; line-height: 1.5; padding: 20px; max-width: 900px; }}
        table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
        th, td {{ border: 1px solid #ccc; padding: 8px; text-align: left; }}
        th {{ background-color: #f4f4f4; }}
        code {{ background-color: #f4f4f4; padding: 2px 4px; border-radius: 3px; }}
    </style>
</head>
<body>
{html_text}
</body>
</html>"""

    with open(html_file, "w", encoding="utf-8") as f:
        f.write(full_html)
    print(f"✅ {html_file} создан.")


if __name__ == "__main__":
    convert("HELP.md", "HELP.html")
    convert("HELP.ru.md", "HELP_ru.html")
