# Parking Eye — перенос UML в Enterprise Architect 15.2

Исходники: `fig1_domain_class.puml`, `fig2_associations.puml`, `fig3_aggregation.puml`  
PNG для сверки: `fig1_domain_class.png`, `fig2_associations.png`, `fig3_aggregation.png`  
**Импорт модели:** `parking_eye_ea152.xmi` (XMI 2.1, под EA 15.2)

---

## 0. Быстрый импорт в EA 15.2 (рекомендуется)

1. Запустите **Enterprise Architect 15.2**.
2. **File → New Project** → document type **EAP** (или откройте свой `.eap`).
3. **Publish → Model Exchange → Import Package from XMI**  
   (в некоторых сборках: **Project → Data Transfer → Import Package from XMI**).
4. Укажите файл: `d:\TKRP2\reports\uml\parking_eye_ea152.xmi`.
5. Формат: **XMI 2.1**, тип UML — **UML 2.x** (по умолчанию).
6. Целевой пакет: корень модели или новый пакет `Parking Eye` → **Import**.
7. В **Project Browser** появятся три пакета:
   - `01 Domain Class Diagram`
   - `02 Association Specification`
   - `03 Aggregation Composition`  
   Внутри — классы, перечисления, ассоциации, зависимости, агрегации и композиции.

### Если подпакетов нет (типично для EA 15.2)

EA часто импортирует только **один** пакет `Parking Eye` без вложенных `01`, `02`, `03`. Это нормально.

**Шаг 1.** Разверните `Parking Eye` (треугольник слева). Проверьте, что внутри:

- **Есть классы** (User, Booking, …) — импорт сработал, элементы «сплющены» в один пакет.
- **Пусто** — импорт не подтянул элементы, см. «Вариант Б» ниже.

**Вариант А — работать без подпакетов (проще всего для отчёта):**

1. ПКМ по `Parking Eye` → **Add → Add a Diagram → Class** — создайте **3 диаграммы**:
   - `Рис1 Domain`
   - `Рис2 Associations`
   - `Рис3 Aggregation`
2. На каждой диаграмме вручную добавьте нужные классы (**Insert → Class** или из таблиц в этом файле).
3. Связи: **Insert → Association / Dependency / Aggregation / Composition**.
4. Сверяйтесь с PNG в `reports\uml\`.

**Вариант Б — три отдельных импорта (подпакеты появятся):**

1. Удалите пустой `Parking Eye` (ПКМ → **Delete Package**).
2. Три раза: **Publish → Model Exchange → Import Package from XMI**.
3. Каждый раз **Package = Model**, файлы по очереди:

| Файл | Что внутри |
|------|------------|
| `ea152_fig1_domain.xmi` | рис. 1 — все классы предметной области |
| `ea152_fig2_associations.xmi` | рис. 2 — ассоциации |
| `ea152_fig3_aggregation.xmi` | рис. 3 — агрегация и композиция |

4. В `Model` появятся три пакета с именами `01…`, `02…`, `03…`. Перетащите их мышью **внутрь** `Parking Eye`, если нужна одна папка в отчёте.

**Вариант В — подпакеты вручную:**

1. ПКМ `Parking Eye` → **Add → Package** → `01 Domain Class Diagram` (и 02, 03).
2. Перетащите классы из `Parking Eye` в нужный подпакет в Project Browser.

---
XMI переносит **элементы модели**, но **не раскладку** на диаграмме. Для каждого пакета:

1. ПКМ по пакету → **Add → Add a Diagram using Wizard → UML Static Structure → Class**.
2. Имя диаграммы — как у пакета (см. разделы «Рисунок 1–3» ниже).
3. В **Project Browser** выделите нужные классы → перетащите на диаграмму (**Add to Diagram**).
4. Разложите блоки как на PNG (раздел 1.5).
5. Для рис. 2 и 3 добавьте **Note** на связи (тексты в таблицах ниже).
6. **Diagram → Save as Image** → PNG 300 DPI для отчёта.

Пересоздать XMI из исходников:

```bat
python d:\TKRP2\scripts\generate_ea_xmi.py
```

---

## 1. Создание проекта (если без импорта XMI)

1. **File → New Project** (или открыть существующий `.eap`).
2. В **Project Browser** создайте пакет: `Parking Eye`.
3. Внутри три подпакета (удобно для отчёта):
   - `01 Domain Class Diagram`
   - `02 Association Specification`
   - `03 Aggregation Composition`
4. Для каждого подпакета: **Add → Add a Diagram using Wizard → UML Static Structure → Class** (Class Diagram).

---

## Рисунок 1 — Диаграмма классов предметной области

**Диаграмма:** `01 Domain Class Diagram`  
**Заголовок на диаграмме:** `UML Class Diagram: Parking Eye Domain`

### 1.1 Перечисления (Enumeration)

В EA: **Insert → Enumeration** (или Class со stereotype `enumeration`).

| Имя | Лiterals |
|-----|----------|
| **Role** | user, admin |
| **BookingStatus** | active, cancelled, completed |
| **SlotVisualStatus** | slot_free, slot_occupied |
| **PaymentStatus** | paid, refunded |

### 1.2 Классы и атрибуты

Для каждого класса: **Insert → Class**, вкладка **Attributes**, visibility **Public (+)**.

| Класс | Атрибуты |
|-------|----------|
| **User** | user_id: int, username: string, password_hash: string, display_name: string, role: Role, active: bool, block_reason: string, created_ts: datetime |
| **AuthSession** | session_id: int, token_hash: string, user_id: int, created_ts: datetime, expires_ts: datetime |
| **Booking** | booking_id: int, user_id: int, slot_id: string, plate: string, start_ts: datetime, end_ts: datetime, status: BookingStatus, note: string, created_ts: datetime |
| **Payment** | payment_id: int, user_id: int, booking_id: int, amount_rub: float, status: PaymentStatus, receipt_id: string, created_ts: datetime |
| **ParkingSlot** | slot_id: string, label: string, current_status: SlotVisualStatus, points_norm: float[][], confidence: float |
| **SlotOverride** | slot_id: string, status: string, note: string, updated_ts: datetime |
| **Observation** | observation_id: int, ts: datetime, dt_ms: int, total: int, free: int, occupied: int, slots_json: string |
| **Snapshot** | snapshot_id: int, ts: datetime, event_id: int, name: string, data: blob |
| **TariffSettings** | hour_rub: float, currency: string |
| **YoloModel** | model_id: string, weights_path: string, conf_threshold: float, is_active: bool |
| **TrafficIndicator** | level: string, free: int, occupied: int, total: int |

### 1.3 Ассоциации (Association — сплошная линия)

**Insert → Association** между классами.  
В **Properties → Source/Target Role**: задайте **Multiplicity** и **Role name**.

| От | К | Кратность (источник → цель) | Имя связи (Role) |
|----|---|-----------------------------|------------------|
| User | AuthSession | 1 → 0..* | opens |
| User | Booking | 1 → 0..* | creates |
| User | Payment | 1 → 0..* | pays |
| Booking | User | 0..* → 1 | belongs_to |
| Booking | ParkingSlot | 0..* → 1 | reserves |
| Booking | Payment | 1 → 0..* | paid_by |
| SlotOverride | ParkingSlot | 0..1 → 1 | overrides |

> В EA кратность ставится на концах линии: **0..***, **1**, **0..1**.

### 1.4 Зависимости (Dependency — пунктир со стрелкой)

**Insert → Dependency** (тип **Dependency** / «Uses»).

| От | К | Метка (Name) |
|----|---|--------------|
| YoloModel | Observation | infers |
| Observation | ParkingSlot | describes |
| Observation | TrafficIndicator | derives |
| Snapshot | Observation | stores_frame_of |
| TariffSettings | Booking | prices |
| TariffSettings | Payment | calculates |

### 1.5 Расположение (как на PNG)

- Слева/центр: **User**, под ним **AuthSession**, **Booking**, **Payment**.
- Справа: **ParkingSlot**, **Observation**, **TrafficIndicator**, **YoloModel**.
- Сверху/сбоку: перечисления **Role**, **BookingStatus**, **PaymentStatus**, **SlotVisualStatus**.
- **TariffSettings**, **Snapshot**, **SlotOverride** — рядом со связанными классами.

---

## Рисунок 2 — Спецификация ассоциаций

**Диаграмма:** `02 Association Specification`  
**Заголовок:** `UML: Association Specification (Parking Eye)`

Можно **перетащить** классы Booking, Payment, ParkingSlot, Observation с рис.1 (Related Elements) или создать упрощённые копии только с нужными атрибутами.

### Классы (упрощённые)

| Класс | Атрибуты |
|-------|----------|
| Booking | booking_id, slot_id, start_ts, end_ts |
| Payment | payment_id, amount_rub, receipt_id |
| ParkingSlot | slot_id, current_status |
| Observation | observation_id, slots_json, ts |

### Связи + Notes

| Связь | Кратность | Role name | Текст Note (привязать к линии) |
|-------|-----------|-----------|--------------------------------|
| Booking — Payment | 1 → 0..* | has_payments | `Booking.payments -> Payment`<br>Одна бронь может иметь несколько платежей (демо-оплата, повтор). |
| Booking — ParkingSlot | * → 1 | for_slot | `Booking.slot -> ParkingSlot`<br>Каждая бронь привязана к одному ID места (slot_1, slot_12, ...). |
| Observation — ParkingSlot | 1 → 0..* | detects | `Observation.detected_slots -> ParkingSlot`<br>Один кадр детекции описывает множество мест в slots_json. |

**Note в EA:** Insert → Note → текст → перетащите **Note Link** на ассоциацию.

---

## Рисунок 3 — Агрегация и композиция

**Диаграмма:** `03 Aggregation Composition`  
**Заголовок:** `UML Aggregation and Composition: Parking Eye`

### Классы (упрощённые)

| Класс | Атрибуты |
|-------|----------|
| ParkingMonitor | name: string, sse_endpoint: string |
| YoloModel | model_id: string, weights_path: string |
| ParkingSlot | slot_id: string |
| Booking | booking_id: int |
| Payment | payment_id: int |
| Observation | observation_id: int |

### Типы связей в Enterprise Architect

| Тип в EA | Символ | Когда |
|----------|--------|--------|
| **Aggregation** | ◇ пустой ромб у «целого» | часть может существовать отдельно |
| **Composition** | ◆ закрашенный ромб у «целого» | часть не существует без целого |

**Insert → Aggregation** или **Composition** (в меню Connector).

| От (ромб здесь) | К | Тип | Кратность | Role | Note |
|-----------------|---|-----|-----------|------|------|
| ParkingMonitor | YoloModel | **Aggregation** ◇ | 1..* | uses_models | **Aggregation**: модель YOLO (train4) можно заменить без пересборки всего монитора. |
| ParkingMonitor | ParkingSlot | **Composition** ◆ | 1..* | contains_slots | **Composition**: слоты существуют в контексте мониторинга парковки (детект + карта мест). |
| Booking | Payment | **Composition** ◆ | 0..* | includes | **Composition**: платёж не существует без брони (таблица payments.booking_id). |
| ParkingMonitor | Observation | **Composition** ◆ | 0..* | logs | **Composition**: запись observations хранит снимок состояния парковки во времени. |

Ромб (Aggregation/Composition) ставится на стороне **ParkingMonitor** / **Booking**.

---

## 2. Экспорт для отчёта (из EA)

1. Откройте диаграмму → **Diagram → Save as Image** (PNG, 300 DPI).
2. Или **Publish → Report Builder** — вставить три диаграммы в Word.
3. Подписи в отчёте:
   - Рисунок 1 – Диаграмма классов предметной области ИС «Parking Eye»
   - Рисунок 2 – Спецификация ассоциаций (имена ролей и кратности)
   - Рисунок 3 – Спецификация агрегаций и композиций

---

## 3. Альтернатива: импорт PlantUML (если есть плагин в EA 15.2)

В некоторых версия EA есть **PlantUML Integration** или сторонний MDG:

1. **Specialize → Manage Technology → Import** — проверьте наличие PlantUML.
2. Если плагина нет — используйте ручное построение по таблицам выше (15–25 мин на все три рисунка).

Файлы `.puml` лежат в `d:\TKRP2\reports\uml\`.

---

## 4. Соответствие коду проекта TKRP2

| Класс EA | Таблица / модуль в коде |
|----------|-------------------------|
| User | `users` (server.py) |
| AuthSession | `sessions`, cookie `pe_session` |
| Booking | `bookings` |
| Payment | `payments` |
| Observation | `observations` |
| Snapshot | `snapshots` |
| SlotOverride | `slot_overrides` |
| TariffSettings | `kv` (tariff_hour_rub) |
| YoloModel | `runs/segment/train4/weights/best.pt` |
| ParkingSlot | результат `/api/detect`, slot_id |
| TrafficIndicator | `_traffic_from_counts()` |
| ParkingMonitor | мониторинг `/`, SSE `/api/stream` |

---

## 5. Чек-лист перед сдачей

- [ ] Рис.1: 4 enum, 11 class, 7 association, 6 dependency
- [ ] Рис.2: 3 association с Notes на каждой связи
- [ ] Рис.3: 1 aggregation + 3 composition с Notes
- [ ] Кратности на всех концах связей
- [ ] PNG экспорт совпадает с макетом отчёта
