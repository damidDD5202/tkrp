#!/usr/bin/env python3
"""Generate lab report docx (Parking Eye) + fetch UML PNG from PlantUML server."""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UML_DIR = ROOT / "reports" / "uml"
OUT_DOCX = ROOT / "reports" / "smart_parking_lab1_parking_eye.docx"

FEATURES_30 = [
    ("Блок 1 — Доступ и интерфейс", [
        "Регистрация и вход (сессии, cookie pe_session).",
        "Личный дашборд после входа (/dashboard.html, /api/me/overview).",
        "Единая навигация: главная, мониторинг, кабинет, админ (app-shell.js).",
        "Тёмная и светлая тема (localStorage, settings.js).",
        "Мультиязычность: русский / английский (I18n).",
        "Крупный шрифт для слабовидящих (data-a11y=large).",
    ]),
    ("Блок 2 — Мониторинг парковки", [
        "Мониторинг в реальном времени: камера / загрузка кадра, POST /api/detect.",
        "Режим клиента: просмотр потока без камеры (SSE /api/stream).",
        "Подсчёт свободных и занятых мест на дашборде и в мониторинге.",
        "Светофор загруженности (зелёный / жёлтый / красный), /api/parking/traffic.",
        "Интерактивная карта загруженности слотов (/api/parking/slots-map).",
        "Снимки и история наблюдений (таблица observations, /api/snapshots).",
        "Toast-уведомления об успехе и ошибке без перезагрузки (ui.js).",
    ]),
    ("Блок 3 — Бронирование и тарифы", [
        "Онлайн-бронь места по ID слота (POST /api/me/bookings).",
        "Онлайн-бронь по карте мест + привязка госномера (plate).",
        "Отмена брони в один клик (DELETE /api/me/bookings/{id}).",
        "Тарифный калькулятор: стоимость от длительности (/api/tariff/calc).",
        "Продление оплаченного времени (PATCH extend_hours).",
        "Уведомление об истечении времени (баннер за 15 мин до конца).",
    ]),
    ("Блок 4 — Кабинет пользователя", [
        "Личный кабинет: профиль, приветствие (/cabinet.html).",
        "Смена пароля (POST /api/auth/change-password).",
        "История поездок / сессий (/api/me/sessions).",
        "Оплата (MVP) и скачивание чека PDF (/api/me/bookings/{id}/pay, receipt PDF).",
    ]),
    ("Блок 5 — Администрирование", [
        "Панель администратора (/admin.html, роль admin).",
        "Управление пользователями: создание, вкл/выкл (/api/admin/users).",
        "Блокировка аккаунта с причиной и разблокировка (block_reason, 403).",
        "Просмотр и управление бронями: отмена, продление, перенос.",
        "Ручной статус места: ремонт, резерв (slot_overrides).",
        "Аналитика по датам: загрузка по часам/дням (/api/admin/analytics/occupancy).",
        "Финансовая аналитика: выручка, тарифы (/api/admin/finance/summary).",
    ]),
]


def fetch_plantuml_png(puml_path: Path) -> bytes | None:
    try:
        from plantuml import PlantUML
    except ImportError:
        print("pip install plantuml", file=sys.stderr)
        return None
    text = puml_path.read_text(encoding="utf-8")
    server = PlantUML(url="https://www.plantuml.com/plantuml/png/")
    try:
        return server.processes(text)
    except Exception as exc:
        print(f"PlantUML fetch failed for {puml_path.name}: {exc}", file=sys.stderr)
        return None


def build_docx(images: dict[str, bytes]) -> None:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(14)

    def center(text: str, bold: bool = False, size: int | None = None):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(text)
        r.bold = bold
        if size:
            r.font.size = Pt(size)

    def heading(text: str):
        doc.add_heading(text, level=1)

    def body(text: str):
        doc.add_paragraph(text)

    def numbered(items: list[str], start: int = 1):
        for i, item in enumerate(items, start=start):
            doc.add_paragraph(f"{i}. {item}", style="List Number")

    # Титул
    center("МИНИСТЕРСТВО НАУКИ И ВЫСШЕГО ПРОФЕССИОНАЛЬНОГО ОБРАЗОВАНИЯ", size=12)
    center("РОССИЙСКОЙ ФЕДЕРАЦИИ", size=12)
    doc.add_paragraph()
    center("Федеральное государственное бюджетное образовательное", size=12)
    center("учреждение высшего образования", size=12)
    center("«_________________________________»", size=12)
    doc.add_paragraph()
    center("Кафедра ________________________________", size=12)
    doc.add_paragraph()
    center("ОТЧЁТ", bold=True, size=16)
    center("по лабораторной работе № 1", size=14)
    center("«Проектирование информационных систем»", size=14)
    center("«Моделирование предметной области и диаграмма классов»", size=14)
    doc.add_paragraph()
    doc.add_paragraph()
    p = doc.add_paragraph()
    p.add_run("Выполнил: студент гр. ____________\n")
    p.add_run("__________________________________\n\n")
    p.add_run("Проверил: ________________________")
    doc.add_paragraph()
    center("Москва, 2026 г.", size=12)
    doc.add_page_break()

    heading("Цель работы")
    body(
        "Освоить построение диаграммы классов предметной области и спецификаций ассоциаций "
        "для информационной системы «Parking Eye» (умная парковка с компьютерным зрением), "
        "реализованной в рамках курсового проекта на стеке FastAPI + YOLO + SQLite + веб-клиент."
    )

    heading("Задачи")
    tasks = [
        "Проанализировать предметную область веб-приложения Parking Eye и выделить сущности БД.",
        "Сформировать диаграмму классов предметной области (рис. 1).",
        "Задать имена ролей и кратности для ключевых ассоциаций (рис. 2).",
        "Выделить агрегации и композиции для мониторинга, броней и наблюдений (рис. 3).",
        "Сопоставить 30 реализованных функций продукта с элементами модели.",
    ]
    numbered(tasks)

    heading("Постановка задачи предметной области")
    body(
        "ИС «Parking Eye» предназначена для мониторинга парковочных мест с помощью нейросети YOLO "
        "(сегментация слотов slot_free / slot_occupied), онлайн-бронирования мест пользователями, "
        "демо-оплаты, личного кабинета и администрирования. В отличие от учебного примера с сущностями "
        "ParkingLot и Camera как отдельными таблицами, в реализованном MVP камера представлена браузером "
        "источника, а слоты идентифицируются строковым slot_id (slot_1, slot_12, …) из результата детекта. "
        "Состояние парковки периодически сохраняется в Observation; брони и платежи — в SQLite."
    )

    heading("Реализованные функции продукта (30)")
    n = 1
    for block_title, items in FEATURES_30:
        doc.add_heading(block_title, level=2)
        for item in items:
            doc.add_paragraph(f"{n}. {item}")
            n += 1

    heading("Функциональные требования (выборка по реализации)")
    fr = [
        "Аутентификация по логину/паролю с серверной сессией (cookie pe_session).",
        "Детекция мест на кадре с камеры или загруженного файла (POST /api/detect, YOLO train4).",
        "Трансляция состояния клиентам через SSE (/api/stream) и снимок /api/latest.",
        "Бронирование с проверкой занятости слота и тарифом 120 ₽/ч (настраивается в kv).",
        "Демо-оплата брони с формированием PDF-чека.",
        "Админ-панель: пользователи, брони, override мест, аналитика occupancy и finance.",
    ]
    numbered(fr)

    heading("Нефункциональные требования")
    nfr = [
        "Обработка /api/detect в отдельном потоке (run_in_threadpool), чтобы не блокировать оплату и кабинет.",
        "Время ответа payment-quote после устранения взаимоблокировки БД — не более нескольких секунд.",
        "Интерфейс: toast-уведомления без полной перезагрузки страницы.",
        "Хранение данных в SQLite с режимом WAL и реентерабельной блокировкой RLock.",
        "Поддержка тёмной/светлой темы и локализации RU/EN.",
        "Кэш-контроль статики (no-store) для актуальных JS/CSS на клиенте.",
        "Роли: user и admin; блокировка пользователя с указанием причины.",
        "Работа в Chrome / Edge; локальный запуск через run_with_train4.bat (uvicorn :8000).",
    ]
    numbered(nfr)

    heading("Требования к данным (Data Requirements)")
    dr = [
        "User: уникальный username, password_hash, display_name, role, active, block_reason.",
        "AuthSession: token_hash, user_id, expires_ts — привязка к пользователю.",
        "Booking: slot_id, start_ts, end_ts, status, plate, user_id — бронь места.",
        "Payment: amount_rub, receipt_id, booking_id, user_id — демо-оплата и чек.",
        "Observation: ts, total, free, occupied, slots_json — история детекта.",
        "SlotOverride: slot_id, status, note — ручной статус места администратором.",
        "TariffSettings (kv): tariff_hour_rub, tariff_currency.",
        "YoloModel: конфигурация весов runs/segment/train4/weights/best.pt, порог conf.",
    ]
    numbered(dr)

    heading("Диаграмма классов предметной области")
    body(
        "На рисунке 1 представлена диаграмма классов ИС «Parking Eye», отражающая пользователей, "
        "сессии, бронирования, платежи, слоты, результаты детекции YOLO и тариф."
    )
    if images.get("fig1"):
        doc.add_picture(io.BytesIO(images["fig1"]), width=Cm(16))
    else:
        body("[Вставьте рисунок: reports/uml/fig1_domain_class.png]")
    center("Рисунок 1 – Диаграмма классов предметной области ИС «Parking Eye»", size=12)

    heading("Интерпретация диаграммы")
    body(
        "Класс User — зарегистрированный пользователь или администратор. AuthSession хранит серверную "
        "сессию входа. Booking связывает пользователя с ParkingSlot (идентификатор из детекта). "
        "Payment фиксирует демо-оплату и номер чека. Observation агрегирует результат кадра YOLO; "
        "SlotOverride позволяет админу задать ремонт/резерв. TariffSettings задаёт почасовой тариф."
    )

    heading("Спецификация ассоциаций")
    body("На рисунке 2 указаны роли и кратности для основных связей.")
    if images.get("fig2"):
        doc.add_picture(io.BytesIO(images["fig2"]), width=Cm(16))
    else:
        body("[Вставьте рисунок: reports/uml/fig2_associations.png]")
    center("Рисунок 2 – Спецификация ассоциаций (имена ролей и кратности)", size=12)
    body(
        "Booking.payments → Payment: одна бронь может иметь несколько записей об оплате (0..*). "
        "Booking.slot → ParkingSlot: каждая бронь относится ровно к одному месту. "
        "Observation.detected_slots → ParkingSlot: один кадр описывает множество мест в JSON."
    )

    heading("Агрегации и композиции")
    body("На рисунке 3 показаны отношения целого и части для мониторинга и бронирования.")
    if images.get("fig3"):
        doc.add_picture(io.BytesIO(images["fig3"]), width=Cm(16))
    else:
        body("[Вставьте рисунок: reports/uml/fig3_aggregation.png]")
    center("Рисунок 3 – Спецификация агрегаций и композиций", size=12)
    body(
        "ParkingMonitor ◇ YoloModel — агрегация: веса модели train4 можно заменить. "
        "ParkingMonitor ◆ ParkingSlot — композиция: слоты определяются в контексте мониторинга. "
        "Booking ◆ Payment — композиция: платёж существует только в рамках брони. "
        "ParkingMonitor ◆ Observation — композиция: запись наблюдения хранит снимок состояния парковки."
    )

    heading("Соответствие модели и кода")
    body(
        "Таблицы SQLite (server.py, parking.db): users, sessions, bookings, payments, observations, "
        "snapshots, slot_overrides, kv. API-слой FastAPI реализует сценарии из 30 функций. "
        "Детекция: _detect_from_raw() + Ultralytics YOLO; фронтенд: static/cabinet.js, app-shell.js."
    )

    heading("Вывод")
    body(
        "В ходе лабораторной работы построена диаграмма классов предметной области для реализованной "
        "ИС «Parking Eye», специфицированы ассоциации, агрегации и композиции. Модель согласована "
        "с 30 функциями продукта (FEATURES.md) и фактической схемой базы данных проекта TKRP2."
    )

    OUT_DOCX.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT_DOCX)
    print(f"Saved: {OUT_DOCX}")


def main() -> None:
    images: dict[str, bytes] = {}
    for key, fname in [
        ("fig1", "fig1_domain_class.puml"),
        ("fig2", "fig2_associations.puml"),
        ("fig3", "fig3_aggregation.puml"),
    ]:
        path = UML_DIR / fname
        png = fetch_plantuml_png(path)
        if png:
            images[key] = png
            out_png = path.with_suffix(".png")
            out_png.write_bytes(png)
            print(f"Saved: {out_png}")
    build_docx(images)


if __name__ == "__main__":
    main()
