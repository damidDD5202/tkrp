#!/usr/bin/env python3
"""Генерация раздела 4 ПЗ (4.1–4.3) под Parking Eye.

Запуск:
  python scripts/generate_pz_section_41_43.py

Файлы:
  reports/pz_section_41_43.docx
  reports/pz_section_41_43.txt
  reports/uml/fig4_1_frontend_components_parking.puml
  reports/uml/fig4_2_backend_components_parking.puml
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt


ROOT = Path(__file__).resolve().parents[1]
OUT_DOCX = ROOT / "reports" / "pz_section_41_43.docx"
OUT_TXT = ROOT / "reports" / "pz_section_41_43.txt"


TEXT: list[str] = [
    "4. Разработка документации приложения",
    "",
    "4.1 Выбор и обоснование технологий, используемых в программном модуле",
    "",
    "Для реализации подсистемы «Отображение свободных и занятых мест» в составе ИС «Умная парковка» "
    "выбрана клиент‑серверная архитектура с веб‑интерфейсом, REST API и реляционной базой данных. "
    "Выбор технологий выполнен с учётом требований индивидуальной темы: мониторинг парковки по видеокадру "
    "с наложением результатов детекции, отображение карты мест в личном кабинете, вычисление индикатора загрузки "
    "(«светофор»), объединение источников состояния (детекция slot_free/slot_occupied, активные брони bookings и "
    "ручные статусы slot_overrides), а также административные операции (отключение места и поиск по госномеру). "
    "При выборе стека также учитывалась необходимость быстрого развёртывания учебного проекта и удобство сопровождения.",
    "",
    "Python используется как основной язык серверной части подсистемы. На нём реализованы обработчики HTTP‑запросов, "
    "проверка прав доступа, бизнес‑правила объединения state(s) и bookable(s), а также интеграция с моделью детекции. "
    "Выбор Python обоснован наличием зрелой экосистемы для веб‑API и компьютерного зрения и высокой скоростью разработки "
    "в учебном проекте.",
    "",
    "FastAPI применяется как веб‑фреймворк для построения REST API. Через FastAPI объявлены конечные точки "
    "POST /api/detect (детекция), GET /api/parking/slots-map (карта мест), GET /api/parking/traffic (индикатор загрузки), "
    "POST/GET /api/me/bookings (бронирования) и административные операции PUT /api/admin/slot-overrides/{slot_id}, "
    "GET /api/admin/find-by-plate. Кроме того, платформа предоставляет эндпоинты регистрации и входа (/api/auth/*), "
    "что обеспечивает единый контур аутентификации для всех страниц. Выбор FastAPI обусловлен высокой производительностью, "
    "встроенной валидацией входных данных и удобной организацией зависимостей (Depends) для авторизации и разграничения ролей.",
    "",
    "SQLite выбрана в качестве СУБД проекта (файл parking.db). В подсистеме используются таблицы bookings "
    "(активные брони), slot_overrides (ручные статусы мест), users и sessions (аутентификация по cookie), "
    "а также observations (архив агрегатов детекции). SQLite обеспечивает целостность данных через первичные ключи "
    "и внешние ключи (например, bookings.user_id → users.id), выполнение выборок активных броней и обновление "
    "ручных статусов мест (UPSERT slot_overrides). Выбор SQLite обоснован простотой развёртывания в учебном проекте, "
    "поддержкой транзакций и достаточной производительностью для требуемых операций чтения/записи.",
    "",
    "JavaScript используется на клиентской стороне для реализации поведения страниц мониторинга, кабинета и админ‑панели. "
    "Модули app.js, cabinet.js, admin.js, pe-features.js выполняют отрисовку overlay и карты мест, вызывают API "
    "через единый адаптер Auth.fetchJson (cookie‑сессии) и обновляют интерфейс по JSON‑ответам. Выбор JavaScript "
    "обоснован нативной поддержкой в браузере и прямой интеграцией с HTML/CSS.",
    "",
    "HTML/CSS используются для разметки страниц (index.html, cabinet.html, admin.html) и единого оформления панелей "
    "и карты мест (styles.css). Такой подход позволяет отделить представление от логики и упростить сопровождение.",
    "",
    "JSON используется как базовый формат обмена данными между клиентом и сервером. Через JSON передаются элементы слотов "
    "(id, detected, state, override, bookable), данные бронирования и результаты административных операций.",
    "",
    "Cookie‑сессии (pe_session) применяются для авторизации пользователей без передачи токена в каждом запросе. "
    "Сервер хранит хэш токена сессии в таблице sessions, а браузер автоматически отправляет cookie при вызовах API "
    "через fetch с credentials. Такой подход упрощает интеграцию страниц кабинета и админ‑панели и позволяет "
    "разграничить роли user/admin через require_login и require_admin.",
    "",
    "YOLOv8-seg (модель сегментации Ultralytics) используется для детекции парковочных мест на кадре. "
    "Результат детекции представляется в виде полигонов в нормализованных координатах (0..1) и меток slot_free/slot_occupied; "
    "далее сервер присваивает стабильные идентификаторы местам и применяет сглаживание меток (debounce). "
    "Выбор модели обоснован практической применимостью для задач компьютерного зрения и качеством сегментации.",
    "",
    "Таким образом, выбранный технологический стек обеспечивает реализацию всех ключевых функций подсистемы: "
    "получение детекции слотов, расчёт индикатора загрузки, объединение статусов и отображение карты мест, "
    "создание броней и административное управление доступностью мест.",
    "",
    "4.2 Описание используемых структур данных",
    "",
    "На рисунке 4.1 представлена диаграмма компонентов пользовательского интерфейса подсистемы. "
    "Пользователь взаимодействует со страницами index.html (мониторинг), cabinet.html (кабинет) и admin.html (администрирование). "
    "Разметка страниц отделена от программной логики: поведение интерфейса реализовано в JavaScript‑модулях app.js "
    "(video + canvas overlay, отправка кадра на детекцию), cabinet.js (загрузка карты мест и бронирование), "
    "admin.js (управление slot_overrides и поиск по госномеру) и pe-features.js (отрисовка карты мест и индикатора traffic).",
    "",
    "Модуль auth.js выделен отдельным компонентом: он выполняет запросы к API с учётом cookie‑сессии (pe_session), "
    "предоставляет функцию Auth.fetchJson и обрабатывает сценарии входа/выхода. Компонент app-shell.js "
    "обеспечивает единый каркас интерфейса (навигация, доступ к админ‑разделу по роли). "
    "Компоненты settings.js и styles.css обеспечивают настройки (i18n, темы) и единообразное оформление.",
    "",
    "Все обращения UI к backend сведены к группам эндпоинтов подсистемы: /api/detect, /api/parking/slots-map, "
    "/api/parking/traffic, /api/me/bookings, /api/admin/slot-overrides и /api/admin/find-by-plate. "
    "Это позволяет изменять формат хранения в SQLite или правила объединения state(s), не перерабатывая разметку страниц, "
    "если сохраняются контракты JSON.",
    "",
    "Рисунок 4.1 – Диаграмма компонентов пользовательского интерфейса подсистемы «Отображение свободных и занятых мест».",
    "",
    "На рисунке 4.2 представлена диаграмма компонентов серверной части подсистемы. "
    "Сервер реализован как единое приложение FastAPI (server.py). Для подсистемы выделены логические группы обработчиков: "
    "детекция (POST /api/detect), парковочные сводки и карта (GET /api/parking/traffic, GET /api/parking/slots-map), "
    "бронирования (/api/me/bookings) и административные операции (/api/admin/slot-overrides, /api/admin/find-by-plate).",
    "",
    "Проверка прав реализована через зависимости require_login и require_admin (cookie‑сессии). "
    "Все обработчики используют единый слой доступа к данным (_db(), _db_lock) и SQLite. "
    "Важно, что live‑детекция хранится в памяти процесса (_last_slots) и объединяется с данными БД "
    "в _parking_slots_map_payload, а таблица observations служит для истории и аналитики.",
    "",
    "Рисунок 4.2 – Диаграмма компонентов серверной части подсистемы «Отображение свободных и занятых мест».",
    "",
    "4.3 Описание потоков данных и связей компонентов",
    "",
    "На таблицах 4.1–4.3 приведено описание связи компонентов, назначение компонентов и передача данных по эндпоинтам. "
    "Таблицы позволяют проследить полный маршрут прохождения управления в подсистеме «Отображение свободных и занятых мест»: "
    "от действий пользователя на страницах мониторинга/кабинета/админки до вызовов REST API и операций чтения/записи в SQLite.",
]


TABLE_4_1_HEADERS = ["От", "К", "Описание"]
TABLE_4_1_ROWS = [
    ["Пользователь", "index.html", "Открытие мониторинга (видео + overlay) и просмотр счётчиков."],
    ["Пользователь", "cabinet.html", "Открытие кабинета: карта мест, форма брони, список броней."],
    ["Администратор", "admin.html", "Открытие админ‑панели: сводка, поиск по госномеру, статусы мест."],
    ["index.html", "app.js", "Логика мониторинга: камера/поток, отрисовка overlay, вызов POST /api/detect."],
    ["cabinet.html", "cabinet.js", "Логика кабинета: загрузка slots-map, создание/отмена брони."],
    ["admin.html", "admin.js", "Логика админки: PUT slot-overrides, GET find-by-plate, обновление карты."],
    ["pe-features.js", "server.py", "GET /api/parking/slots-map и /api/parking/traffic для карты и «светофора»."],
    ["auth.js", "server.py", "Сессия и роли: /api/auth/*, cookie pe_session, доступ require_login/admin."],
    ["server.py", "SQLite parking.db", "Запросы к bookings, slot_overrides, users, sessions, observations."],
    ["app.js", "server.py", "POST /api/detect; обновление _last_slots; запись observations (фон)."],
]


TABLE_4_2_HEADERS = ["Уровень", "Компонент", "Назначение"]
TABLE_4_2_ROWS = [
    ["Frontend", "index.html", "Страница мониторинга: video, canvas overlay, счётчики, режимы source/client."],
    ["Frontend", "cabinet.html", "Кабинет пользователя: карта мест, форма брони, список броней."],
    ["Frontend", "admin.html", "Админ‑панель: поиск по госномеру, ручные статусы мест, сводка."],
    ["Frontend", "static/app.js", "Захват кадра и POST /api/detect, отрисовка overlay."],
    ["Frontend", "static/pe-features.js", "Виджеты traffic и карты мест (renderTraffic, renderSlotMap)." ],
    ["Frontend", "static/cabinet.js", "Сценарии бронирования и обновления карты мест."],
    ["Frontend", "static/admin.js", "Сценарии администрирования slot_overrides и поиска по plate."],
    ["Frontend", "static/auth.js", "Auth.fetchJson, login/register/logout, cookie‑сессия."],
    ["Backend", "server.py — /api/detect", "Детекция слотов, stable id, debounce, обновление live‑состояния."],
    ["Backend", "server.py — /api/parking/slots-map, /traffic", "Выдача карты мест и индикатора загрузки."],
    ["Backend", "server.py — /api/me/bookings", "Создание/список/отмена/изменение броней."],
    ["Backend", "server.py — /api/admin/*", "Админ‑операции: slot_overrides, find-by-plate, сводка."],
    ["Data Storage", "SQLite parking.db", "users, sessions, bookings, slot_overrides, observations."],
]


TABLE_4_3_HEADERS = ["Компонент", "Метод", "Эндпоинт", "Тело запроса", "Ответ"]
TABLE_4_3_ROWS = [
    ["app.js", "POST", "/api/detect", "multipart: image", "JSON: slots(points,label,conf), counts, ts"],
    ["pe-features.js/cabinet.js", "GET", "/api/parking/slots-map", "—", "JSON: slots(id,detected,state,override,bookable), traffic"],
    ["pe-features.js", "GET", "/api/parking/traffic", "—", "JSON: level, pct_free, free,total,occupied"],
    ["cabinet.js", "GET", "/api/me/bookings", "—", "JSON: список броней + remaining_s"],
    ["cabinet.js", "POST", "/api/me/bookings", "JSON: slot_id, hours, plate, note?", "201/JSON booking"],
    ["cabinet.js", "DELETE", "/api/me/bookings/{id}", "—", "200/ok (status cancelled)"],
    ["admin.js", "PUT", "/api/admin/slot-overrides/{slot_id}", "JSON: status, note?", "200/ok + override"],
    ["admin.js", "GET", "/api/admin/find-by-plate?plate=", "—", "JSON: slot_id, booking + live_state"],
]


def _setup_doc() -> Document:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style._element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
    style.font.size = Pt(14)
    return doc


def _add_table(doc: Document, headers: list[str], rows: list[list[str]]) -> None:
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    hdr = table.rows[0].cells
    for i, h in enumerate(headers):
        hdr[i].text = h
    for r in rows:
        cells = table.add_row().cells
        for i, v in enumerate(r):
            cells[i].text = str(v)


def build_docx() -> Document:
    doc = _setup_doc()
    for line in TEXT:
        if not line.strip():
            doc.add_paragraph()
            continue
        if line.startswith("4.") and (" " in line):
            p = doc.add_paragraph(line)
            if p.runs:
                p.runs[0].bold = True
            continue
        if line.startswith("Рисунок 4."):
            p = doc.add_paragraph(line)
            if p.runs:
                p.runs[0].italic = True
            continue
        doc.add_paragraph(line)

    doc.add_paragraph()
    p = doc.add_paragraph("Таблица 4.1 – Предоставлено описание связи компонентов.")
    if p.runs:
        p.runs[0].bold = True
    _add_table(doc, TABLE_4_1_HEADERS, TABLE_4_1_ROWS)

    doc.add_paragraph()
    doc.add_paragraph(
        "Таблица 4.1 показывает маршруты взаимодействия: пользователь работает со страницами интерфейса, "
        "клиентские модули JavaScript формируют HTTP‑запросы и получают JSON‑ответы, а сервер выполняет "
        "проверку доступа и обращается к таблицам SQLite. Такой подход исключает обращение интерфейса "
        "к базе данных напрямую и обеспечивает единые контракты API для всех сценариев."
    )

    doc.add_paragraph()
    p = doc.add_paragraph("Таблица 4.2 – Описание компонентов подсистемы.")
    if p.runs:
        p.runs[0].bold = True
    _add_table(doc, TABLE_4_2_HEADERS, TABLE_4_2_ROWS)

    doc.add_paragraph()
    doc.add_paragraph(
        "Таблица 4.2 фиксирует распределение компонентов по уровням. На стороне клиента выделены модули, "
        "обеспечивающие индивидуальные сценарии: overlay детекции, карта мест и администрирование статусов. "
        "На стороне сервера логические группы обработчиков соответствуют эндпоинтам подсистемы и используют "
        "единый слой доступа к данным и live‑состояние детекции (_last_slots)."
    )

    doc.add_paragraph()
    p = doc.add_paragraph("Таблица 4.3 – Описание передачи данных по эндпоинтам.")
    if p.runs:
        p.runs[0].bold = True
    _add_table(doc, TABLE_4_3_HEADERS, TABLE_4_3_ROWS)

    doc.add_paragraph()
    doc.add_paragraph(
        "Таблица 4.3 отражает контракт обмена данными: детекция передаёт полигоны слотов и метки, "
        "карта мест получает объединённый state(s) и traffic, а операции бронирования и административные "
        "изменения приводят к записи в таблицы bookings и slot_overrides. Такой перечень эндпоинтов "
        "используется при проверке корректности реализации и демонстрации работы подсистемы."
    )
    return doc


def main() -> None:
    OUT_DOCX.parent.mkdir(parents=True, exist_ok=True)
    OUT_TXT.write_text("\n".join(TEXT) + "\n", encoding="utf-8")
    build_docx().save(OUT_DOCX)
    print(f"OK: {OUT_DOCX}")
    print(f"OK: {OUT_TXT}")


if __name__ == "__main__":
    main()

