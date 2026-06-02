"""
finance — голосовой учёт расходов/доходов для Тройки.

Хранилище: ``~/.troika/finance.db``, одна таблица ``txn`` (id, ts, amount,
currency, category, description, kind). Без API банков, без OCR — только то
что Миша надиктовал.

operations:
  - ``add`` — записать транзакцию. args:
      ``amount`` (req, число; отрицательное = расход, положительное = доход;
       либо ``kind="expense"|"income"`` и положительный ``amount``),
      ``category`` (str, например "еда", "бензин", "развлечения"),
      ``description`` (str, свободный текст),
      ``currency`` (default "RUB").
  - ``list`` — последние N транзакций. args: ``limit`` (default 20),
      ``period`` ("today"/"yesterday"/"week"/"month"/"all"),
      ``category`` (optional filter).
  - ``summary`` — сводка по категориям. args: ``period`` (default "month"),
      ``category`` (optional). Возвращает {by_category, total_expense,
      total_income, net, count}.
  - ``delete`` — удалить транзакцию по id.

Голосовые триггеры (skill дополнить):
  - «потратил 800 на бензин» → add(amount=-800, category="бензин")
  - «купил еды на 1500» → add(amount=-1500, category="еда")
  - «получил зарплату 80000» → add(amount=80000, kind="income", category="зарплата")
  - «сколько в этом месяце на еду» → summary(period="month", category="еда")
  - «куда уходят деньги» → summary(period="month")
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from tools.registry import registry

logger = logging.getLogger(__name__)

_TROIKA_HOME = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".troika"))
_DB = _TROIKA_HOME / "finance.db"


def _connect() -> sqlite3.Connection:
    _TROIKA_HOME.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS txn (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            amount REAL NOT NULL,
            currency TEXT NOT NULL DEFAULT 'RUB',
            category TEXT NOT NULL DEFAULT 'прочее',
            description TEXT,
            kind TEXT NOT NULL CHECK(kind IN ('expense','income'))
        );
        CREATE INDEX IF NOT EXISTS idx_txn_ts ON txn(ts);
        CREATE INDEX IF NOT EXISTS idx_txn_category ON txn(category);
        """
    )
    conn.commit()
    return conn


def _period_bounds(period: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Возвращает (start_iso, end_iso) включительно/исключительно.

    period: today / yesterday / week / month / all / None.
    None и all → (None, None) — без фильтра.
    """
    if not period or period == "all":
        return None, None
    p = period.strip().lower()
    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if p == "today":
        start = today
        end = today + timedelta(days=1)
    elif p == "yesterday":
        start = today - timedelta(days=1)
        end = today
    elif p == "week":
        start = today - timedelta(days=now.weekday())  # понедельник
        end = start + timedelta(days=7)
    elif p == "month":
        start = today.replace(day=1)
        # начало следующего месяца
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
    else:
        return None, None
    return start.isoformat(), end.isoformat()


def _normalize_amount(args: Dict[str, Any]) -> tuple[float, str]:
    """Возвращает (signed_amount, kind). Расход = отрицательное."""
    raw = args.get("amount")
    if raw is None:
        raise ValueError("missing 'amount'")
    try:
        val = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"amount must be a number, got {raw!r}")

    kind = (args.get("kind") or "").strip().lower()
    if kind == "expense":
        return -abs(val), "expense"
    if kind == "income":
        return abs(val), "income"
    # Без явного kind: знак решает
    if val < 0:
        return val, "expense"
    if val > 0:
        return val, "income"
    raise ValueError("amount cannot be zero")


def _op_add(args: Dict[str, Any]) -> Dict[str, Any]:
    amount, kind = _normalize_amount(args)
    category = (args.get("category") or "прочее").strip().lower()[:64]
    description = (args.get("description") or "").strip()[:500]
    currency = (args.get("currency") or "RUB").strip().upper()[:8]

    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO txn(ts, amount, currency, category, description, kind) "
            "VALUES (?,?,?,?,?,?)",
            (
                datetime.now().isoformat(timespec="seconds"),
                amount,
                currency,
                category,
                description,
                kind,
            ),
        )
        conn.commit()
        new_id = cur.lastrowid

        verb = "Записал расход" if kind == "expense" else "Записал доход"
        return {
            "ok": True,
            "id": new_id,
            "amount": amount,
            "currency": currency,
            "category": category,
            "kind": kind,
            "say_to_user": f"{verb} {abs(amount):g} {currency} на {category}.",
        }
    finally:
        conn.close()


def _op_list(args: Dict[str, Any]) -> Dict[str, Any]:
    limit = max(1, min(int(args.get("limit") or 20), 200))
    period = args.get("period")
    category = (args.get("category") or "").strip().lower() or None

    start, end = _period_bounds(period)

    conn = _connect()
    try:
        sql = "SELECT id, ts, amount, currency, category, description, kind FROM txn"
        clauses: List[str] = []
        params: List[Any] = []
        if start:
            clauses.append("ts >= ?")
            params.append(start)
        if end:
            clauses.append("ts < ?")
            params.append(end)
        if category:
            clauses.append("category = ?")
            params.append(category)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        items = [
            {
                "id": r[0],
                "ts": r[1],
                "amount": r[2],
                "currency": r[3],
                "category": r[4],
                "description": r[5],
                "kind": r[6],
            }
            for r in rows
        ]
        return {
            "ok": True,
            "period": period or "all",
            "category": category,
            "count": len(items),
            "items": items,
        }
    finally:
        conn.close()


def _op_summary(args: Dict[str, Any]) -> Dict[str, Any]:
    period = args.get("period") or "month"
    category = (args.get("category") or "").strip().lower() or None
    currency_filter = (args.get("currency") or "").strip().upper() or None

    start, end = _period_bounds(period)

    conn = _connect()
    try:
        sql = "SELECT category, kind, amount, currency FROM txn"
        clauses: List[str] = []
        params: List[Any] = []
        if start:
            clauses.append("ts >= ?")
            params.append(start)
        if end:
            clauses.append("ts < ?")
            params.append(end)
        if category:
            clauses.append("category = ?")
            params.append(category)
        if currency_filter:
            clauses.append("currency = ?")
            params.append(currency_filter)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)

        rows = conn.execute(sql, params).fetchall()

        # Группируем по (category, currency)
        by_cat: Dict[tuple, Dict[str, Any]] = {}
        total_exp: Dict[str, float] = {}
        total_inc: Dict[str, float] = {}
        count = 0
        for cat, kind, amt, cur in rows:
            count += 1
            key = (cat, cur)
            if key not in by_cat:
                by_cat[key] = {
                    "category": cat,
                    "currency": cur,
                    "expense": 0.0,
                    "income": 0.0,
                    "net": 0.0,
                }
            if kind == "expense":
                by_cat[key]["expense"] += abs(amt)
                total_exp[cur] = total_exp.get(cur, 0.0) + abs(amt)
            else:
                by_cat[key]["income"] += amt
                total_inc[cur] = total_inc.get(cur, 0.0) + amt
            by_cat[key]["net"] = by_cat[key]["income"] - by_cat[key]["expense"]

        # Сортируем категории по сумме расходов (потом дохода)
        cats_sorted = sorted(
            by_cat.values(),
            key=lambda c: (c["expense"], c["income"]),
            reverse=True,
        )

        nets = {cur: total_inc.get(cur, 0.0) - total_exp.get(cur, 0.0)
                for cur in set(list(total_exp.keys()) + list(total_inc.keys()))}

        return {
            "ok": True,
            "period": period,
            "category": category,
            "count": count,
            "total_expense": total_exp,
            "total_income": total_inc,
            "net": nets,
            "by_category": cats_sorted,
        }
    finally:
        conn.close()


def _op_delete(args: Dict[str, Any]) -> Dict[str, Any]:
    tid = args.get("id")
    if tid is None:
        return {"ok": False, "error": "missing 'id'"}
    try:
        tid = int(tid)
    except (TypeError, ValueError):
        return {"ok": False, "error": f"id must be int, got {tid!r}"}

    conn = _connect()
    try:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT amount, currency, category FROM txn WHERE id = ?",
            (tid,),
        ).fetchone()
        if not row:
            return {"ok": False, "error": f"txn_not_found: {tid}"}
        cur.execute("DELETE FROM txn WHERE id = ?", (tid,))
        conn.commit()
        return {
            "ok": True,
            "deleted_id": tid,
            "say_to_user": f"Удалил запись {row[2]} на {abs(row[0]):g} {row[1]}.",
        }
    finally:
        conn.close()


async def _handle(args: Dict[str, Any], **_kw) -> str:
    op = (args.get("operation") or args.get("op") or "").strip().lower()
    if not op:
        return json.dumps({"ok": False, "error": "missing 'operation'"}, ensure_ascii=False)
    try:
        if op == "add":
            res = _op_add(args)
        elif op == "list":
            res = _op_list(args)
        elif op == "summary":
            res = _op_summary(args)
        elif op == "delete":
            res = _op_delete(args)
        else:
            res = {
                "ok": False,
                "error": f"unknown_operation: {op}",
                "allowed": ["add", "list", "summary", "delete"],
            }
        return json.dumps(res, ensure_ascii=False)
    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
    except Exception as e:
        logger.exception("finance tool failure")
        return json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"},
                          ensure_ascii=False)


FINANCE_SCHEMA = {
    "name": "finance",
    "description": (
        "Учёт личных расходов/доходов для Миши. Голосовой ввод: «потратил "
        "800 на бензин» → operation=add, kind=expense, amount=800, "
        "category=\"бензин\". «купил еды на 1500» → add expense 1500 "
        "category=\"еда\". «зарплата 80000» → add income 80000 "
        "category=\"зарплата\". «сколько на еду в этом месяце» → "
        "operation=summary period=month category=\"еда\". «куда уходят "
        "деньги» → summary period=month (всё). Категории: еда, бензин, "
        "транспорт, развлечения, кафе, продукты, одежда, здоровье, "
        "связь, коммуналка, подарки, прочее. Валюта по умолчанию RUB."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["add", "list", "summary", "delete"],
                "description": "add=новая транзакция; list=последние записи; summary=сводка по категориям; delete=по id.",
            },
            "amount": {
                "type": "number",
                "description": (
                    "Сумма. Положительное число с kind=expense будет записано "
                    "как расход. Отрицательное без kind тоже = расход."
                ),
            },
            "kind": {
                "type": "string",
                "enum": ["expense", "income"],
                "description": "Тип. Если опущен — определяется по знаку amount.",
            },
            "category": {
                "type": "string",
                "description": "Категория одним словом на русском: еда, бензин, кафе, транспорт, ...",
            },
            "description": {
                "type": "string",
                "description": "Свободный текст: что именно купил/откуда доход.",
            },
            "currency": {
                "type": "string",
                "description": "ISO код валюты (RUB, USD, EUR). По умолчанию RUB.",
            },
            "period": {
                "type": "string",
                "enum": ["today", "yesterday", "week", "month", "all"],
                "description": "Для list/summary: период. По умолчанию all для list, month для summary.",
            },
            "limit": {
                "type": "integer",
                "description": "Для list: максимум записей (1..200, default 20).",
            },
            "id": {
                "type": "integer",
                "description": "Для delete: id транзакции.",
            },
        },
        "required": ["operation"],
    },
}


registry.register(
    name="finance",
    toolset="finance",
    schema=FINANCE_SCHEMA,
    handler=_handle,
    is_async=True,
    emoji="💰",
)
