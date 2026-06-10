# Parking Eye (Demo для показа на iPhone без iOS/Xcode)

Это веб-приложение (PWA-like), которое:
- показывает **картинку с камеры** (если страница открыта по HTTPS),
- отправляет кадры на сервер (Windows) для **YOLOv8-seg** на **5 FPS**,
- **само** находит парковочные места и подсвечивает их:
  - зелёным = свободно (`slot_free`)
  - красным = занято (`slot_occupied`)

## 1) Запуск сервера на Windows

В PowerShell:

```bash
cd d:\TKRP2
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn server:app --host 0.0.0.0 --port 8000
```

Проверьте в браузере на ПК: `http://localhost:8000`

## 2) ВАЖНО: iPhone Safari требует HTTPS для камеры

Если вы откроете `http://<ip>:8000` на iPhone, камера **не заработает**.

### Вариант A (самый простой): Cloudflare Tunnel (даёт HTTPS ссылку)

1) Скачайте `cloudflared` для Windows
2) В отдельном окне:

```bash
cloudflared tunnel --url http://localhost:8000
```

3) Он выдаст HTTPS-ссылку вида `https://xxxxx.trycloudflare.com`
4) Откройте её на iPhone → разрешите камеру → можно “Поделиться → На экран «Домой»”.

### Вариант B: ngrok (аналогично HTTPS)

Запустите:

```bash
ngrok http 8000
```

Откройте выданный `https://...` на iPhone.

## 3) Как пользоваться

- Откройте страницу на iPhone (через HTTPS) → разрешите камеру.
- Места будут подсвечиваться автоматически:
  - **красный** = `slot_occupied`
  - **зелёный** = `slot_free`
- “Разметить заново” — очищает текущий оверлей/статистику (без сохранения).

## 4) Модель YOLO

Сервер ожидает сегментационную модель, обученную на классах `slot_free` / `slot_occupied`.
Можно указать свои веса:

```bash
set PARKING_EYE_MODEL=best.pt
python -m uvicorn server:app --host 0.0.0.0 --port 8000
```

## 5) PKLot → YOLOv8-seg (подготовка и обучение)

### 5.1) Подготовка датасета из `Voxel51/PKLot`

Рекомендуется делать это в Python 3.11 окружении `.venv-pklot`:

```bash
cd d:\TKRP2
.\.venv-pklot\Scripts\activate
python .\convert_pklot_to_yolo_seg.py
```

Сгенерируется папка `pklot_yolo_seg\` с `images/`, `labels/`, `data.yaml`.

### 5.2) Обучение

```bash
yolo segment train model=yolov8n-seg.pt data=pklot_yolo_seg/data.yaml imgsz=960 epochs=50 batch=8 device=0
```

После обучения веса будут в `runs/segment/train/weights/best.pt`.

## Идея: режим Источник/Клиент (трансляция разметки)

Цель: чтобы один телефон (оператор) смотрел камерой на парковку, отправлял кадры на сервер, сервер делал детект и сохранял "последний кадр + полигоны", а другие пользователи открывали веб‑страницу и видели ту же парковку с разметкой в реальном времени.

### Как работает
- Source (оператор): `/?mode=source`
  - включает камеру
  - раз в N мс отправляет кадр на `/api/detect`
- Server:
  - делает YOLO detect
  - сохраняет `last_frame_jpeg`, `last_slots`, `last_ts`
- Client (пользователь): `/?mode=client`
  - камеру не включает
  - получает `/api/latest` и рисует `last_frame + last_slots`

### Что добавить
- `GET /api/latest` → `{ jpg_base64 (или url), slots, ts }`
- опционально WebSocket/SSE вместо опроса

Ограничения: задержка 0.5–2с, приватность (транслируется картинка), клиент видит именно камеру оператора.
