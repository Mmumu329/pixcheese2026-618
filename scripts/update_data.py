"""
像素芝士大促看板 - 数据更新脚本

本脚本从 Metabase 拉取：
- 8539: 大促订单（含 2025 双 11 基线 + 2026 618 订单）
- 8565: 2026 年中大促前端事件
- 8567/8568: 预约/邀请明细（当前账号可能无查询权限，失败时写入数据质量提示）

输出 dashboard_data.json，供 GitHub Pages 静态看板读取。
"""

import csv
import io
import json
import os
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime


METABASE_URL = os.environ.get("METABASE_URL", "https://metabase.pixcakeai.com").rstrip("/")
METABASE_USER = os.environ.get("METABASE_USER")
METABASE_PASS = os.environ.get("METABASE_PASS")

ORDER_MODEL_ID = 8539
EVENT_MODEL_ID = 8565
RESERVE_MODEL_ID = 8567
INVITE_MODEL_ID = 8568

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "dashboard_data.json")


def request_json(url, session_id=None, body=None, timeout=120):
    headers = {"Content-Type": "application/json"}
    if session_id:
        headers["X-Metabase-Session"] = session_id
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def login():
    if not METABASE_USER or not METABASE_PASS:
        sys.exit("缺少 METABASE_USER / METABASE_PASS 环境变量")
    data = request_json(
        f"{METABASE_URL}/api/session",
        body={"username": METABASE_USER, "password": METABASE_PASS},
        timeout=30,
    )
    print(f"登录成功: {METABASE_USER}")
    return data["id"]


def query_card(session_id, card_id, *, ignore_cache=True):
    """使用普通 query 接口。ignore_cache=True 避免 Metabase 返回旧缓存。"""
    body = {"ignore_cache": True} if ignore_cache else {}
    data = request_json(
        f"{METABASE_URL}/api/card/{card_id}/query",
        session_id=session_id,
        body=body,
        timeout=240,
    )
    if data.get("status") != "completed":
        return [], {
            "card_id": card_id,
            "status": data.get("status"),
            "error": data.get("error") or "query failed",
            "error_type": data.get("error_type"),
        }
    cols = [c["name"] for c in data.get("data", {}).get("cols", [])]
    rows = [dict(zip(cols, r)) for r in data.get("data", {}).get("rows", [])]
    quality = {
        "card_id": card_id,
        "status": "completed",
        "row_count": data.get("row_count", len(rows)),
        "rows_returned": len(rows),
        "rows_truncated": data.get("data", {}).get("rows_truncated"),
    }
    return rows, quality


def download_orders(session_id):
    """订单模型 CSV 导出权限可用，优先用 CSV 避免 2000 行 query 截断。"""
    req = urllib.request.Request(
        f"{METABASE_URL}/api/card/{ORDER_MODEL_ID}/query/csv",
        method="POST",
        headers={"X-Metabase-Session": session_id},
    )
    try:
        with urllib.request.urlopen(req, timeout=240) as resp:
            content = resp.read().decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(content)))
        print(f"订单数据: {len(rows)} 行 (CSV)")
        return rows, {"card_id": ORDER_MODEL_ID, "status": "completed", "rows_returned": len(rows), "source": "csv"}
    except Exception as exc:
        print(f"订单 CSV 下载失败，回退 query: {exc}")
        rows, quality = query_card(session_id, ORDER_MODEL_ID)
        print(f"订单数据: {len(rows)} 行 (query)")
        return rows, quality


def download_events(session_id):
    rows, quality = query_card(session_id, EVENT_MODEL_ID, ignore_cache=True)
    print(f"事件数据: {len(rows)} 行 (query, ignore_cache=true)")
    return rows, quality


def download_optional_detail(session_id, card_id):
    rows, quality = query_card(session_id, card_id, ignore_cache=True)
    if quality.get("status") != "completed":
        print(f"模型 {card_id} 暂不可用: {quality.get('error')}")
    else:
        print(f"模型 {card_id}: {len(rows)} 行")
    return rows, quality


def money(value):
    if value in (None, ""):
        return 0.0
    return float(value)


def text(value):
    return "" if value is None else str(value)


def normalize_order(row):
    row = dict(row)
    row["actual_price"] = money(row.get("actual_price"))
    row["product_price"] = money(row.get("product_price"))
    created_at = text(row.get("created_at"))
    row["date"] = created_at[:10]
    row["hour"] = int(created_at[11:13]) if len(created_at) >= 13 and created_at[11:13].isdigit() else 0
    row["user_id"] = text(row.get("user_id"))
    row["org_id"] = text(row.get("org_id"))
    row["product_name"] = text(row.get("product_name"))
    row["buy_type_name"] = text(row.get("buy_type_name")) or "未知"
    row["buy_source_type_name"] = text(row.get("buy_source_type_name")) or "未知"
    row["buy_source_name"] = text(row.get("buy_source_name")) or "未知"
    return row


def phase_of(date_str, campaign_key):
    if campaign_key == "y2025_d11":
        if date_str <= "2025-10-30":
            return "预热期"
        if date_str <= "2025-11-07":
            return "蓄水期"
        if date_str <= "2025-11-12":
            return "正式期"
        return "返场期"
    if date_str <= "2026-05-17":
        return "预约期"
    if date_str <= "2026-05-29":
        return "正式期"
    if date_str <= "2026-06-15":
        return "沉淀期"
    return "返场期"


def phase_ranges(campaign_key):
    if campaign_key == "y2025_d11":
        return [
            {"name": "预热期", "dates": "10/20-10/30", "cls": "warmup", "days": 11, "note": ""},
            {"name": "蓄水期", "dates": "10/31-11/07", "cls": "water", "days": 8, "note": ""},
            {"name": "正式期", "dates": "11/08-11/12", "cls": "formal", "days": 5, "note": ""},
            {"name": "返场期", "dates": "11/13-11/14", "cls": "return", "days": 2, "note": "数据截止 11/14"},
        ]
    return [
        {"name": "预约期", "dates": "05/13-05/17", "cls": "warmup", "days": 5, "note": ""},
        {"name": "正式期", "dates": "05/18-05/29", "cls": "formal", "days": 12, "note": ""},
        {"name": "沉淀期", "dates": "05/30-06/15", "cls": "water", "days": 17, "note": ""},
        {"name": "返场期", "dates": "06/16-06/18", "cls": "return", "days": 3, "note": ""},
    ]


def empty_dataset(campaign_key, campaign_name):
    return {
        "meta": {
            "campaign": campaign_name,
            "campaign_key": campaign_key,
            "date_range": "暂无订单数据",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        },
        "core": {
            "total_gmv": 0,
            "total_orders": 0,
            "unique_users": 0,
            "unique_orgs": 0,
            "aov": 0,
            "member_gmv": 0,
            "voucher_gmv": 0,
            "member_ratio": 0,
            "voucher_ratio": 0,
        },
        "daily": [],
        "phase": {},
        "phase_ranges": phase_ranges(campaign_key),
        "hourly_peak": [{"hour": h, "gmv": 0, "orders": 0, "member": 0, "voucher": 0} for h in range(24)],
        "member_rank": [],
        "voucher_rank": [],
        "buy_type": [],
        "channel": [],
        "sub_channel": [],
        "price_bucket": [],
        "org_freq": [],
        "platform": {"ios": {"gmv": 0, "ratio": 0}, "android_web": {"gmv": 0, "ratio": 0}},
    }


def aggregate_orders(raw_rows, campaign_key, campaign_name):
    rows = [normalize_order(r) for r in raw_rows if text(r.get("created_at"))[:10]]
    if not rows:
        return empty_dataset(campaign_key, campaign_name)

    total_gmv = sum(r["actual_price"] for r in rows)
    member = [r for r in rows if "会员" in r["product_name"]]
    voucher = [r for r in rows if "会员" not in r["product_name"]]
    member_gmv = sum(r["actual_price"] for r in member)
    voucher_gmv = total_gmv - member_gmv
    unique_users = len({r["user_id"] for r in rows if r["user_id"]})
    unique_orgs = len({r["org_id"] for r in rows if r["org_id"]})
    dates = sorted({r["date"] for r in rows})

    daily = defaultdict(lambda: {"gmv": 0, "orders": 0, "users": set(), "member": 0, "voucher": 0})
    for r in rows:
        d = r["date"]
        daily[d]["gmv"] += r["actual_price"]
        daily[d]["orders"] += 1
        daily[d]["users"].add(r["user_id"])
        if "会员" in r["product_name"]:
            daily[d]["member"] += r["actual_price"]
        else:
            daily[d]["voucher"] += r["actual_price"]

    daily_list = [
        {
            "date": d,
            "phase": phase_of(d, campaign_key),
            "gmv": round(daily[d]["gmv"]),
            "orders": daily[d]["orders"],
            "users": len(daily[d]["users"]),
            "member_gmv": round(daily[d]["member"]),
            "voucher_gmv": round(daily[d]["voucher"]),
        }
        for d in sorted(daily)
    ]

    phase_agg = defaultdict(lambda: {"gmv": 0, "orders": 0, "users": set()})
    for r in rows:
        p = phase_of(r["date"], campaign_key)
        phase_agg[p]["gmv"] += r["actual_price"]
        phase_agg[p]["orders"] += 1
        phase_agg[p]["users"].add(r["user_id"])
    phase_dict = {
        p: {"gmv": round(d["gmv"]), "orders": d["orders"], "users": len(d["users"])}
        for p, d in phase_agg.items()
    }

    daily_gmv_sorted = sorted(daily_list, key=lambda x: -x["gmv"])[:2]
    peak_dates = {d["date"] for d in daily_gmv_sorted}
    hourly = defaultdict(lambda: {"gmv": 0, "orders": 0, "member": 0, "voucher": 0})
    for r in rows:
        if r["date"] in peak_dates:
            h = r["hour"]
            hourly[h]["gmv"] += r["actual_price"]
            hourly[h]["orders"] += 1
            if "会员" in r["product_name"]:
                hourly[h]["member"] += r["actual_price"]
            else:
                hourly[h]["voucher"] += r["actual_price"]
    hourly_peak = [{"hour": h, **{k: round(v) if isinstance(v, float) else v for k, v in hourly[h].items()}} for h in range(24)]

    def short_name(name):
        return name.replace("大促活动｜", "").replace("25年双11｜", "").replace("（ios）", " iOS").replace("(ios)", " iOS")

    member_rank_d = defaultdict(lambda: {"gmv": 0, "orders": 0, "price": 0})
    voucher_rank_d = defaultdict(lambda: {"gmv": 0, "orders": 0, "price": 0})
    for r in rows:
        target = member_rank_d if "会员" in r["product_name"] else voucher_rank_d
        s = short_name(r["product_name"])
        target[s]["gmv"] += r["actual_price"]
        target[s]["orders"] += 1
        target[s]["price"] = r["product_price"]

    def rank_items(data, limit=8):
        return sorted(
            [{"name": k, "gmv": round(v["gmv"]), "orders": v["orders"], "price": v["price"]} for k, v in data.items()],
            key=lambda x: -x["gmv"],
        )[:limit]

    def aggregate_by(field, limit=None):
        agg = defaultdict(lambda: {"gmv": 0, "orders": 0, "users": set()})
        for r in rows:
            n = r[field] or "未知"
            agg[n]["gmv"] += r["actual_price"]
            agg[n]["orders"] += 1
            agg[n]["users"].add(r["user_id"])
        items = sorted(
            [{"name": k, "gmv": round(v["gmv"]), "orders": v["orders"], "users": len(v["users"])} for k, v in agg.items()],
            key=lambda x: -x["gmv"],
        )
        return items[:limit] if limit else items

    buy_type_agg = defaultdict(lambda: {"gmv": 0, "orders": 0})
    for r in rows:
        buy_type_agg[r["buy_type_name"]]["gmv"] += r["actual_price"]
        buy_type_agg[r["buy_type_name"]]["orders"] += 1
    buy_type = sorted(
        [{"name": k, "gmv": round(v["gmv"]), "orders": v["orders"]} for k, v in buy_type_agg.items()],
        key=lambda x: -x["gmv"],
    )

    buckets_def = [
        ("¥0-100", 0, 100),
        ("¥100-300", 100, 300),
        ("¥300-500", 300, 500),
        ("¥500-1000", 500, 1000),
        ("¥1000-2000", 1000, 2000),
        ("¥2000+", 2000, float("inf")),
    ]
    buckets = {k: 0 for k, _, _ in buckets_def}
    for r in rows:
        for k, lo, hi in buckets_def:
            if lo <= r["actual_price"] < hi:
                buckets[k] += 1
                break
    price_bucket = [{"range": k, "count": v} for k, v in buckets.items()]

    org_orders = Counter(r["org_id"] for r in rows)
    freq_def = [("仅1单", 1, 1), ("2单", 2, 2), ("3-5单", 3, 5), ("6-10单", 6, 10), ("10+单", 11, float("inf"))]
    freq = {k: 0 for k, _, _ in freq_def}
    for c in org_orders.values():
        for k, lo, hi in freq_def:
            if lo <= c <= hi:
                freq[k] += 1
                break
    org_freq = [{"range": k, "count": v} for k, v in freq.items()]

    ios_gmv = sum(r["actual_price"] for r in rows if "（ios）" in r["product_name"] or "(ios)" in r["product_name"].lower())
    platform = {
        "ios": {"gmv": round(ios_gmv), "ratio": round(ios_gmv / total_gmv * 100, 1) if total_gmv else 0},
        "android_web": {"gmv": round(total_gmv - ios_gmv), "ratio": round((total_gmv - ios_gmv) / total_gmv * 100, 1) if total_gmv else 0},
    }

    return {
        "meta": {
            "campaign": campaign_name,
            "campaign_key": campaign_key,
            "date_range": f"{dates[0]} → {dates[-1]}",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        },
        "core": {
            "total_gmv": round(total_gmv),
            "total_orders": len(rows),
            "unique_users": unique_users,
            "unique_orgs": unique_orgs,
            "aov": round(total_gmv / max(unique_users, 1), 1),
            "member_gmv": round(member_gmv),
            "voucher_gmv": round(voucher_gmv),
            "member_ratio": round(member_gmv / total_gmv * 100, 1) if total_gmv else 0,
            "voucher_ratio": round(voucher_gmv / total_gmv * 100, 1) if total_gmv else 0,
        },
        "daily": daily_list,
        "phase": phase_dict,
        "phase_ranges": phase_ranges(campaign_key),
        "hourly_peak": hourly_peak,
        "member_rank": rank_items(member_rank_d),
        "voucher_rank": rank_items(voucher_rank_d),
        "buy_type": buy_type,
        "channel": aggregate_by("buy_source_type_name"),
        "sub_channel": aggregate_by("buy_source_name", 15),
        "price_bucket": price_bucket,
        "org_freq": org_freq,
        "platform": platform,
    }


def valid_uid(value):
    uid = text(value)
    return uid and uid not in ("0", "None", "null")


def aggregate_events(rows, quality):
    if not rows:
        return {
            "event_total": 0,
            "funnel": {},
            "reserve_count": 0,
            "assist": {},
            "new_user_gift": 0,
            "quality": quality,
        }

    funnel = defaultdict(set)
    reserve_users = set()
    assist_funnel = defaultdict(set)
    new_user_gift = 0
    daily_events = Counter()
    daily_reserve = Counter()
    action_counts = Counter()
    screen_counts = Counter()
    element_counts = Counter()
    channel_counts = Counter()
    user_type_counts = Counter()
    source_counts = Counter()

    for r in rows:
        action = text(r.get("action"))
        screen = text(r.get("screen_name"))
        url = text(r.get("url_path"))
        elem = text(r.get("element_name"))
        uid = text(r.get("user_id"))
        dt = text(r.get("dt"))[:10]
        channel = text(r.get("channel_name")) or text(r.get("source_sid")) or "未知"
        user_type = text(r.get("user_type")) or "未知"
        source = text(r.get("data_source")) or "未知"

        if dt:
            daily_events[dt] += 1
        action_counts[action or "未知"] += 1
        screen_counts[screen or "未知"] += 1
        if elem:
            element_counts[elem] += 1
        channel_counts[channel] += 1
        user_type_counts[user_type] += 1
        source_counts[source] += 1

        if action == "screen_view" and screen in ("open_screen", "home_page"):
            funnel["exposure"].add(uid)
        if action == "module_view" and screen == "home_page":
            funnel["exposure"].add(uid)
        if action == "page_view" or "may-sale/index" in url:
            funnel["visit"].add(uid)
            if valid_uid(uid):
                funnel["login"].add(uid)
        if action == "element_click":
            funnel["click"].add(uid)
        if elem in ("package_card", "package_item", "sku_card"):
            funnel["package_click"].add(uid)
        if elem in ("buy_btn", "pay_confirm"):
            funnel["buy_click"].add(uid)
        if "payment/index" in url:
            funnel["payment_page"].add(uid)
        if "success" in url:
            funnel["paid"].add(uid)

        if elem == "reserve_button" or "reservation-success" in url:
            reserve_users.add(uid)
            if dt:
                daily_reserve[dt] += 1

        if elem in ("invite_friends", "go_share", "help_login", "help_complete_profile", "receive_prize"):
            assist_funnel[elem].add(uid)

        if text(r.get("package_id")) == "20187" and text(r.get("action_detail")) == "completed":
            new_user_gift += 1

    return {
        "event_total": len(rows),
        "event_date_range": f"{min(daily_events)} → {max(daily_events)}" if daily_events else "暂无",
        "funnel": {k: len({u for u in v if valid_uid(u)}) for k, v in funnel.items()},
        "reserve_count": len({u for u in reserve_users if valid_uid(u)}),
        "daily_reserve": [{"date": k, "count": v} for k, v in sorted(daily_reserve.items())],
        "assist": {k: len({u for u in v if valid_uid(u)}) for k, v in assist_funnel.items()},
        "new_user_gift": new_user_gift,
        "action_counts": action_counts.most_common(20),
        "screen_counts": screen_counts.most_common(20),
        "element_counts": element_counts.most_common(20),
        "channel_counts": channel_counts.most_common(20),
        "user_type_counts": user_type_counts.most_common(10),
        "source_counts": source_counts.most_common(10),
        "quality": quality,
    }


def main():
    print(f"[{datetime.now()}] 开始更新看板数据...")
    sid = login()
    orders, order_quality = download_orders(sid)
    events, event_quality = download_events(sid)
    reserve_rows, reserve_quality = download_optional_detail(sid, RESERVE_MODEL_ID)
    invite_rows, invite_quality = download_optional_detail(sid, INVITE_MODEL_ID)

    normalized_orders = [normalize_order(r) for r in orders]
    orders_2025 = [r for r in normalized_orders if r["date"].startswith("2025-")]
    orders_2026 = [r for r in normalized_orders if r["date"].startswith("2026-")]

    y2025 = aggregate_orders(orders_2025, "y2025_d11", "25 年双 11 大促（真实数据，作为 618 同期基线）")
    y2026 = aggregate_orders(orders_2026, "y2026_618", "26 年 618 大促（实时数据）")
    y2026["events"] = aggregate_events(events, event_quality)

    data_quality = {
        "orders": order_quality,
        "events": event_quality,
        "reserve_detail": {**reserve_quality, "rows_returned": len(reserve_rows)},
        "invite_detail": {**invite_quality, "rows_returned": len(invite_rows)},
        "notes": [
            "GitHub Actions 海外 runner 无法访问 Metabase，自动更新由本机 LaunchAgent 推送 dashboard_data.json。",
            "8565 普通 query 接口最多返回 2000 行；如 rows_truncated=2000，事件数据为抽样/截断结果，需要 Metabase 管理员开放下载或提供聚合模型。",
            "8567/8568 当前账号提示 missing-required-permissions，预约/邀请明细暂不能作为完整口径。",
        ],
    }

    result = {
        "meta": {
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "source": "Metabase collection 474",
            "default_dataset": "y2025_d11",
        },
        "datasets": {
            "y2025_d11": y2025,
            "y2026_618": y2026,
        },
        "data_quality": data_quality,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"已写入 {OUTPUT_PATH}")
    print(
        f"2025 基线: ¥{y2025['core']['total_gmv']:,} / {y2025['core']['total_orders']} 单 | "
        f"2026 实时: ¥{y2026['core']['total_gmv']:,} / {y2026['core']['total_orders']} 单 | "
        f"事件 {y2026['events']['event_total']} 行"
    )
    if event_quality.get("rows_truncated"):
        print(f"提示: 8565 事件结果被 Metabase 截断 rows_truncated={event_quality.get('rows_truncated')}")
    if reserve_quality.get("status") != "completed" or invite_quality.get("status") != "completed":
        print("提示: 预约/邀请明细模型权限不足，已写入 data_quality。")


if __name__ == "__main__":
    main()
