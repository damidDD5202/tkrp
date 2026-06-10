"""Тесты подсистемы «Отображение свободных и занятых мест» — по одному на каждую из 15 функций."""
from __future__ import annotations

import time

import pytest


def _create_booking(client, slot_id: str = "slot_func_test", hours: float = 3.0) -> int:
    r = client.post(
        "/api/me/bookings",
        json={"slot_id": slot_id, "hours": hours, "plate": "A123BC77"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("ok") is True
    return int(data["booking_id"])


class TestFunction01CancelBooking:
    """Функция 1 — отмена брони в один клик."""

    def test_cancel_active_booking(self, user_client):
        bid = _create_booking(user_client, "slot_cancel_1")
        r = user_client.delete(f"/api/me/bookings/{bid}")
        assert r.status_code == 200
        assert r.json().get("ok") is True
        listed = user_client.get("/api/me/bookings").json()
        row = next(x for x in listed["bookings"] if x["id"] == bid)
        assert row["status"] == "cancelled"


class TestFunction02TariffCalculator:
    """Функция 2 — тарифный калькулятор."""

    def test_tariff_calc_for_two_hours(self, user_client):
        hour = user_client.get("/api/tariff").json()["hour_rub"]
        r = user_client.post("/api/tariff/calc", json={"hours": 2})
        assert r.status_code == 200
        data = r.json()
        assert data.get("ok") is True
        assert data["price_rub"] == pytest.approx(float(hour) * 2)


class TestFunction03ExtendParking:
    """Функция 3 — продление времени парковки."""

    def test_extend_active_booking(self, user_client):
        bid = _create_booking(user_client, "slot_extend_1")
        before = user_client.get("/api/me/bookings").json()
        end_before = next(x for x in before["bookings"] if x["id"] == bid)["end_ts"]
        r = user_client.patch(f"/api/me/bookings/{bid}", json={"extend_hours": 1})
        assert r.status_code == 200
        assert r.json().get("ok") is True
        after = user_client.get("/api/me/bookings").json()
        end_after = next(x for x in after["bookings"] if x["id"] == bid)["end_ts"]
        assert end_after > end_before


class TestFunction04ExpiryNotification:
    """Функция 4 — уведомление об истечении времени (данные для баннера)."""

    def test_booking_with_soon_end_has_remaining_under_15_min(self, user_client):
        bid = _create_booking(user_client, "slot_expiry_1", hours=0.25)
        rows = user_client.get("/api/me/bookings").json()["bookings"]
        row = next(x for x in rows if x["id"] == bid)
        assert row["status"] == "active"
        assert 0 < float(row["remaining_s"]) <= 900


class TestFunction05PersonalCabinet:
    """Функция 5 — личный кабинет, карта мест и «светофор»."""

    def test_overview_map_and_traffic(self, user_client):
        me = user_client.get("/api/auth/me").json()
        assert me.get("ok") is True
        assert me.get("user", {}).get("display_name")
        overview = user_client.get("/api/me/overview").json()
        assert overview.get("ok") is True
        smap = user_client.get("/api/parking/slots-map").json()
        assert isinstance(smap.get("slots"), list)
        assert "traffic" in smap
        traffic = user_client.get("/api/parking/traffic").json()
        assert "level" in traffic


class TestFunction06ChangePassword:
    """Функция 6 — смена пароля."""

    def test_change_password_and_restore(self, client):
        client.post("/api/auth/login", json={"username": "maria", "password": "user123"})
        r = client.post(
            "/api/auth/change-password",
            json={"current_password": "user123", "new_password": "MariaNew123"},
        )
        assert r.status_code == 200
        assert r.json().get("ok") is True
        client.post("/api/auth/logout")
        bad = client.post("/api/auth/login", json={"username": "maria", "password": "user123"})
        assert bad.status_code == 401
        good = client.post("/api/auth/login", json={"username": "maria", "password": "MariaNew123"})
        assert good.status_code == 200
        client.post(
            "/api/auth/change-password",
            json={"current_password": "MariaNew123", "new_password": "user123"},
        )


class TestFunction07TripHistory:
    """Функция 7 — история поездок и сессий."""

    def test_sessions_list_returns_bookings(self, user_client):
        _create_booking(user_client, "slot_history_1", hours=1)
        r = user_client.get("/api/me/sessions")
        assert r.status_code == 200
        data = r.json()
        assert data.get("ok") is True
        assert isinstance(data.get("sessions"), list)
        assert len(data["sessions"]) >= 1


class TestFunction08PaymentAndReceipt:
    """Функция 8 — оплата и чек."""

    def test_demo_payment_returns_receipt(self, user_client):
        bid = _create_booking(user_client, "slot_pay_1", hours=1)
        r = user_client.post(f"/api/me/bookings/{bid}/pay", json={})
        assert r.status_code == 200
        data = r.json()
        assert data.get("ok") is True
        assert data.get("receipt_id")


class TestFunction09AdminPanel:
    """Функция 9 — панель администратора."""

    def test_admin_summary_access(self, client):
        client.post("/api/auth/login", json={"username": "ivan", "password": "user123"})
        assert client.get("/api/admin/summary").status_code == 403
        client.post("/api/auth/logout")
        client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        r = client.get("/api/admin/summary")
        assert r.status_code == 200
        assert r.json().get("ok") is True


class TestFunction10UserManagement:
    """Функция 10 — управление пользователями."""

    def test_admin_lists_and_creates_user(self, admin_client):
        lst = admin_client.get("/api/admin/users")
        assert lst.status_code == 200
        assert isinstance(lst.json().get("users"), list)
        uname = f"pytest_{int(time.time())}"
        created = admin_client.post(
            "/api/admin/users",
            json={
                "username": uname,
                "password": "TestUser123",
                "display_name": "Pytest User",
                "role": "user",
            },
        )
        assert created.status_code == 200
        assert created.json().get("ok") is True


class TestFunction11AccountBlock:
    """Функция 11 — блокировка аккаунта с причиной."""

    def test_block_user_with_reason(self, admin_client, client):
        uname = f"block_{int(time.time())}"
        admin_client.post(
            "/api/admin/users",
            json={
                "username": uname,
                "password": "BlockTest123",
                "display_name": "Block Me",
                "role": "user",
            },
        )
        users = admin_client.get("/api/admin/users").json()["users"]
        uid = next(u["id"] for u in users if u["username"] == uname)
        patch = admin_client.patch(
            f"/api/admin/users/{uid}",
            json={"active": False, "block_reason": "Тест блокировки"},
        )
        assert patch.status_code == 200
        login = client.post("/api/auth/login", json={"username": uname, "password": "BlockTest123"})
        assert login.status_code == 403
        admin_client.patch(f"/api/admin/users/{uid}", json={"active": True, "block_reason": None})


class TestFunction12AdminBookings:
    """Функция 12 — просмотр и управление бронями (админ)."""

    def test_admin_lists_and_extends_booking(self, user_client, admin_client):
        bid = _create_booking(user_client, "slot_admin_bk_1")
        lst = admin_client.get("/api/admin/bookings")
        assert lst.status_code == 200
        ids = [b["id"] for b in lst.json().get("bookings", [])]
        assert bid in ids
        ext = admin_client.patch(f"/api/admin/bookings/{bid}", json={"extend_hours": 0.5})
        assert ext.status_code == 200
        assert ext.json().get("ok") is True


class TestFunction13ManualSlotStatus:
    """Функция 13 — ручной статус места."""

    def test_admin_sets_closed_override(self, admin_client):
        r = admin_client.put(
            "/api/admin/slot-overrides/slot_override_13",
            json={"status": "closed", "note": "pytest"},
        )
        assert r.status_code == 200
        assert r.json().get("ok") is True
        listed = admin_client.get("/api/admin/slot-overrides").json()
        overrides = {o["slot_id"]: o for o in listed.get("overrides", [])}
        assert overrides.get("slot_override_13", {}).get("status") == "closed"


class TestFunction14OccupancyAnalytics:
    """Функция 14 — аналитика загрузки по датам."""

    def test_occupancy_analytics_structure(self, admin_client):
        r = admin_client.get("/api/admin/analytics/occupancy?days=7")
        assert r.status_code == 200
        data = r.json()
        assert data.get("ok") is True
        assert "hourly" in data and "daily" in data


class TestFunction15FinanceAnalytics:
    """Функция 15 — финансовая аналитика."""

    def test_finance_summary_structure(self, admin_client):
        r = admin_client.get("/api/admin/finance/summary?days=30")
        assert r.status_code == 200
        data = r.json()
        assert data.get("ok") is True
        assert "revenue_rub" in data and "tariff_hour_rub" in data
