"""
像素芝士大促看板 - 数据更新脚本

功能：
1. 登录 Metabase API
2. 拉取订单数据 (model 8539) + 埋点事件数据 (model 8565)
3. 聚合成看板需要的 dashboard_data.json
4. 写入仓库根目录，触发 GitHub Pages 重新部署

使用：
- 本地手动跑: METABASE_USER=... METABASE_PASS=... python scripts/update_data.py
- GitHub Actions: 通过 secrets 注入凭据，定时触发
"""

import os
import sys
import json
import csv
import io
from datetime import datetime
from collections import defaultdict
import urllib.request
import urllib.parse


METABASE_URL = os.environ.get('METABASE_URL', 'https://metabase.pixcakeai.com')
METABASE_USER = os.environ.get('METABASE_USER')
METABASE_PASS = os.environ.get('METABASE_PASS')

ORDER_MODEL_ID = 8539
EVENT_MODEL_ID = 8565

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), '..', 'dashboard_data.json')


def login():
    if not METABASE_USER or not METABASE_PASS:
        sys.exit('❌ 缺少 METABASE_USER / METABASE_PASS 环境变量')

    req = urllib.request.Request(
        f'{METABASE_URL}/api/session',
        data=json.dumps({'username': METABASE_USER, 'password': METABASE_PASS}).encode(),
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    print(f'✅ 登录成功: {METABASE_USER}')
    return data['id']


def download_orders(session_id):
    """从 model 8539 下载订单 CSV"""
    req = urllib.request.Request(
        f'{METABASE_URL}/api/card/{ORDER_MODEL_ID}/query/csv',
        method='POST',
        headers={'X-Metabase-Session': session_id},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            content = resp.read().decode('utf-8')
        reader = csv.DictReader(io.StringIO(content))
        rows = list(reader)
        print(f'✅ 订单数据: {len(rows)} 行')
        return rows
    except Exception as e:
        print(f'⚠️ 订单数据下载失败（可能权限不够，回退到常规 query 接口）: {e}')
        return download_orders_via_query(session_id)


def download_orders_via_query(session_id):
    req = urllib.request.Request(
        f'{METABASE_URL}/api/card/{ORDER_MODEL_ID}/query',
        method='POST',
        data=b'{}',
        headers={
            'X-Metabase-Session': session_id,
            'Content-Type': 'application/json',
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    if data.get('status') != 'completed':
        sys.exit(f'❌ 订单查询失败: {data.get("error")}')
    cols = [c['name'] for c in data['data']['cols']]
    rows = [dict(zip(cols, r)) for r in data['data']['rows']]
    print(f'✅ 订单数据 (query): {len(rows)} 行')
    return rows


def download_events(session_id):
    """从 model 8565 下载埋点事件数据"""
    req = urllib.request.Request(
        f'{METABASE_URL}/api/card/{EVENT_MODEL_ID}/query',
        method='POST',
        data=b'{}',
        headers={
            'X-Metabase-Session': session_id,
            'Content-Type': 'application/json',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read())
        if data.get('status') != 'completed':
            print(f'⚠️ 事件查询失败: {data.get("error")}')
            return []
        cols = [c['name'] for c in data['data']['cols']]
        rows = [dict(zip(cols, r)) for r in data['data']['rows']]
        print(f'✅ 事件数据: {len(rows)} 行')
        return rows
    except Exception as e:
        print(f'⚠️ 事件下载异常（5/13 前为空属正常）: {e}')
        return []


def phase_of(d):
    """判断日期所属阶段"""
    if '2025-' in d:
        if d <= '2025-10-30': return '预热期'
        if d <= '2025-11-07': return '蓄水期'
        if d <= '2025-11-12': return '正式期'
        return '返场期'
    if d <= '2026-05-17': return '预热期'
    if d <= '2026-05-29': return '正式期'
    if d <= '2026-06-15': return '沉淀期'
    return '返场期'


def aggregate_orders(rows):
    """聚合订单数据为看板 JSON 结构"""
    for r in rows:
        r['actual_price'] = float(r['actual_price'])
        r['product_price'] = float(r['product_price'])
        r['date'] = r['created_at'][:10]
        r['hour'] = int(r['created_at'][11:13])

    if not rows:
        return None

    total_gmv = sum(r['actual_price'] for r in rows)
    member = [r for r in rows if '会员' in r['product_name']]
    voucher = [r for r in rows if '会员' not in r['product_name']]
    member_gmv = sum(r['actual_price'] for r in member)
    voucher_gmv = total_gmv - member_gmv
    unique_users = len(set(r['user_id'] for r in rows))
    unique_orgs = len(set(r['org_id'] for r in rows))

    dates = sorted(r['date'] for r in rows)
    is_2025 = '2025-' in dates[0]
    campaign = '25 年双 11 大促（真实数据，作为 618 同期基线）' if is_2025 else '26 年 618 大促'

    # daily
    daily = defaultdict(lambda: {'gmv': 0, 'orders': 0, 'users': set(), 'member': 0, 'voucher': 0})
    for r in rows:
        d = r['date']
        daily[d]['gmv'] += r['actual_price']
        daily[d]['orders'] += 1
        daily[d]['users'].add(r['user_id'])
        if '会员' in r['product_name']:
            daily[d]['member'] += r['actual_price']
        else:
            daily[d]['voucher'] += r['actual_price']

    daily_list = []
    for d in sorted(daily.keys()):
        if daily[d]['orders'] < 5:
            continue
        daily_list.append({
            'date': d,
            'phase': phase_of(d),
            'gmv': round(daily[d]['gmv']),
            'orders': daily[d]['orders'],
            'users': len(daily[d]['users']),
            'member_gmv': round(daily[d]['member']),
            'voucher_gmv': round(daily[d]['voucher']),
        })

    # phase agg
    phase_agg = defaultdict(lambda: {'gmv': 0, 'orders': 0, 'users': set()})
    for r in rows:
        p = phase_of(r['date'])
        phase_agg[p]['gmv'] += r['actual_price']
        phase_agg[p]['orders'] += 1
        phase_agg[p]['users'].add(r['user_id'])
    phase_dict = {p: {'gmv': round(d['gmv']), 'orders': d['orders'], 'users': len(d['users'])}
                  for p, d in phase_agg.items()}

    # hourly peak (取 GMV 最高两天)
    daily_gmv_sorted = sorted(daily_list, key=lambda x: -x['gmv'])[:2]
    peak_dates = {d['date'] for d in daily_gmv_sorted}
    hourly = defaultdict(lambda: {'gmv': 0, 'orders': 0, 'member': 0, 'voucher': 0})
    for r in rows:
        if r['date'] in peak_dates:
            h = r['hour']
            hourly[h]['gmv'] += r['actual_price']
            hourly[h]['orders'] += 1
            if '会员' in r['product_name']:
                hourly[h]['member'] += r['actual_price']
            else:
                hourly[h]['voucher'] += r['actual_price']
    hourly_peak = [{'hour': h, **{k: round(v) if isinstance(v, float) else v for k, v in hourly[h].items()}}
                   for h in range(24)]

    # product rank
    def short_name(name):
        return name.replace('大促活动｜', '').replace('25年双11｜', '').replace('（ios）', ' iOS')

    member_rank_d = defaultdict(lambda: {'gmv': 0, 'orders': 0, 'price': 0})
    voucher_rank_d = defaultdict(lambda: {'gmv': 0, 'orders': 0, 'price': 0})
    for r in rows:
        s = short_name(r['product_name'])
        if '会员' in r['product_name']:
            member_rank_d[s]['gmv'] += r['actual_price']
            member_rank_d[s]['orders'] += 1
            member_rank_d[s]['price'] = r['product_price']
        else:
            voucher_rank_d[s]['gmv'] += r['actual_price']
            voucher_rank_d[s]['orders'] += 1
            voucher_rank_d[s]['price'] = r['product_price']
    member_rank = sorted([{'name': k, 'gmv': round(v['gmv']), 'orders': v['orders'], 'price': v['price']}
                          for k, v in member_rank_d.items()], key=lambda x: -x['gmv'])[:8]
    voucher_rank = sorted([{'name': k, 'gmv': round(v['gmv']), 'orders': v['orders'], 'price': v['price']}
                           for k, v in voucher_rank_d.items()], key=lambda x: -x['gmv'])[:8]

    # buy_type
    bt_agg = defaultdict(lambda: {'gmv': 0, 'orders': 0})
    for r in rows:
        n = r['buy_type_name']
        bt_agg[n]['gmv'] += r['actual_price']
        bt_agg[n]['orders'] += 1
    buy_type = sorted([{'name': k, 'gmv': round(v['gmv']), 'orders': v['orders']}
                       for k, v in bt_agg.items()], key=lambda x: -x['gmv'])

    # channel
    ch_agg = defaultdict(lambda: {'gmv': 0, 'orders': 0, 'users': set()})
    for r in rows:
        n = r['buy_source_type_name'] or '未知'
        ch_agg[n]['gmv'] += r['actual_price']
        ch_agg[n]['orders'] += 1
        ch_agg[n]['users'].add(r['user_id'])
    channel = sorted([{'name': k, 'gmv': round(v['gmv']), 'orders': v['orders'], 'users': len(v['users'])}
                      for k, v in ch_agg.items()], key=lambda x: -x['gmv'])

    sc_agg = defaultdict(lambda: {'gmv': 0, 'orders': 0, 'users': set()})
    for r in rows:
        n = r['buy_source_name'] or '未知'
        sc_agg[n]['gmv'] += r['actual_price']
        sc_agg[n]['orders'] += 1
        sc_agg[n]['users'].add(r['user_id'])
    sub_channel = sorted([{'name': k, 'gmv': round(v['gmv']), 'orders': v['orders'], 'users': len(v['users'])}
                          for k, v in sc_agg.items()], key=lambda x: -x['gmv'])[:15]

    # price buckets
    buckets_def = [('¥0-100', 0, 100), ('¥100-300', 100, 300), ('¥300-500', 300, 500),
                   ('¥500-1000', 500, 1000), ('¥1000-2000', 1000, 2000), ('¥2000+', 2000, float('inf'))]
    buckets = {k: 0 for k, _, _ in buckets_def}
    for r in rows:
        p = r['actual_price']
        for k, lo, hi in buckets_def:
            if lo <= p < hi:
                buckets[k] += 1
                break
    price_bucket = [{'range': k, 'count': v} for k, v in buckets.items()]

    # org freq
    org_orders = defaultdict(int)
    for r in rows:
        org_orders[r['org_id']] += 1
    freq_def = [('仅1单', 1, 1), ('2单', 2, 2), ('3-5单', 3, 5), ('6-10单', 6, 10), ('10+单', 11, float('inf'))]
    freq = {k: 0 for k, _, _ in freq_def}
    for c in org_orders.values():
        for k, lo, hi in freq_def:
            if lo <= c <= hi:
                freq[k] += 1
                break
    org_freq = [{'range': k, 'count': v} for k, v in freq.items()]

    # platform
    ios_gmv = sum(r['actual_price'] for r in rows if '（ios）' in r['product_name'] or '(ios)' in r['product_name'])
    platform = {
        'ios': {'gmv': round(ios_gmv), 'ratio': round(ios_gmv / total_gmv * 100, 1) if total_gmv else 0},
        'android_web': {'gmv': round(total_gmv - ios_gmv),
                        'ratio': round((total_gmv - ios_gmv) / total_gmv * 100, 1) if total_gmv else 0},
    }

    return {
        'meta': {
            'campaign': campaign,
            'date_range': f'{dates[0]} → {dates[-1]}',
            'updated_at': datetime.now().isoformat(timespec='seconds'),
        },
        'core': {
            'total_gmv': round(total_gmv),
            'total_orders': len(rows),
            'unique_users': unique_users,
            'unique_orgs': unique_orgs,
            'aov': round(total_gmv / max(unique_users, 1), 1),
            'member_gmv': round(member_gmv),
            'voucher_gmv': round(voucher_gmv),
            'member_ratio': round(member_gmv / total_gmv * 100, 1) if total_gmv else 0,
            'voucher_ratio': round(voucher_gmv / total_gmv * 100, 1) if total_gmv else 0,
        },
        'daily': daily_list,
        'phase': phase_dict,
        'hourly_peak': hourly_peak,
        'member_rank': member_rank,
        'voucher_rank': voucher_rank,
        'buy_type': buy_type,
        'channel': channel,
        'sub_channel': sub_channel,
        'price_bucket': price_bucket,
        'org_freq': org_freq,
        'platform': platform,
    }


def aggregate_events(rows):
    """聚合埋点事件 (5/13 后才有数据)"""
    if not rows:
        return {}

    funnel = defaultdict(set)
    reserve_users = set()
    assist_funnel = defaultdict(set)
    new_user_gift = 0

    for r in rows:
        action = r.get('action')
        screen = r.get('screen_name')
        url = r.get('url_path') or ''
        elem = r.get('element_name')
        uid = r.get('user_id')

        # 8 步全链路漏斗
        if action == 'screen_view' and screen in ('open_screen', 'home_page'):
            funnel['exposure'].add(uid)
        if action == 'module_view' and screen == 'home_page':
            funnel['exposure'].add(uid)
        if action == 'page_view' and url == '/':
            funnel['exposure'].add(uid)
        if action == 'element_click' and screen == 'open_screen':
            funnel['click'].add(uid)
        if url == 'pages/promotion/may-sale/index':
            funnel['visit'].add(uid)
            if uid and uid != '0':
                funnel['login'].add(uid)
        if url == 'pages/promotion/may-sale/payment/index':
            funnel['payment_page'].add(uid)
        if url == 'pages/promotion/may-sale/success':
            funnel['paid'].add(uid)

        # 预约
        if action == 'element_click' and elem == 'reserve_button':
            reserve_users.add(uid)

        # 助力 5 步
        if action == 'element_click' and elem in ('invite_friends', 'go_share', 'help_login', 'help_complete_profile', 'receive_prize'):
            assist_funnel[elem].add(uid)

        # 9.9 礼包
        if r.get('package_id') == 20187 and r.get('action_detail') == 'completed':
            new_user_gift += 1

    return {
        'funnel': {k: len(v) for k, v in funnel.items()},
        'reserve_count': len(reserve_users),
        'assist': {k: len(v) for k, v in assist_funnel.items()},
        'new_user_gift': new_user_gift,
    }


def main():
    print(f'[{datetime.now()}] 开始更新看板数据...')
    sid = login()
    orders = download_orders(sid)
    events = download_events(sid)

    result = aggregate_orders(orders)
    if result is None:
        sys.exit('❌ 订单数据为空，看板无法生成')

    if events:
        result['events'] = aggregate_events(events)

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f'✅ 已写入 {OUTPUT_PATH}')
    print(f'   GMV: ¥{result["core"]["total_gmv"]:,} | 订单 {result["core"]["total_orders"]} | 用户 {result["core"]["unique_users"]}')


if __name__ == '__main__':
    main()
