import os
import json
import requests
import argparse
from datetime import datetime, timedelta
import re
from zoneinfo import ZoneInfo

def fetch_purchase_bulletins():
    url = "https://ygcg.nbcqjy.org/api/Portal/GetBulletinList"
    # ★ 去掉 classID 限制，拉全量公告；pageSize 加大到 200
    payload = json.dumps({
        "pageIndex": 1,
        "pageSize": 200
    })
    headers = {
        'Content-Type': 'application/json;charset=utf-8',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Origin': 'https://ygcg.nbcqjy.org',
        'Referer': 'https://ygcg.nbcqjy.org/'
    }

    resp = requests.post(url, headers=headers, data=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def save_json(content, savepath="purchase_bulletins.json"):
    save_dir = os.path.dirname(savepath)
    if save_dir and not os.path.exists(save_dir):
        os.makedirs(save_dir)
    with open(savepath, "w", encoding="utf-8") as f:
        json.dump(content, f, ensure_ascii=False, indent=2)


def extract_items(data):
    """从原始返回中尽量稳妥地取出公告列表数组。"""
    if isinstance(data, dict):
        body = data.get("body") or {}
        inner = body.get("data") if isinstance(body, dict) else {}
        if isinstance(inner, dict):
            for key in ["list", "bulletinList", "items", "rows", "data"]:
                items = inner.get(key)
                if isinstance(items, list):
                    return items
        for key in ["list", "bulletinList", "items", "rows"]:
            items = body.get(key) if isinstance(body, dict) else None
            if isinstance(items, list):
                return items
    return []


def parse_date_to_ymd(value):
    """将日期字符串解析为 YYYY-MM-DD 格式。失败则返回 None。"""
    if not value:
        return None
    try:
        core = str(value)[:10]
        dt = datetime.fromisoformat(core)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    m = re.search(r"(?:^|[^\d])(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[^\d]|$)", str(value))
    if m:
        try:
            year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return f"{year:04d}-{month:02d}-{day:02d}"
        except Exception:
            return None
    return None


def parse_to_iso_datetime(value):
    if not value:
        return None
    s = str(value).strip()
    m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})(?:[ T](\d{1,2})(?::(\d{1,2}))?(?::(\d{1,2}))?)?", s)
    if m:
        try:
            y = int(m.group(1))
            mo = int(m.group(2))
            d = int(m.group(3))
            hh = int(m.group(4)) if m.group(4) is not None else 0
            mm_ = int(m.group(5)) if m.group(5) is not None else 0
            ss = int(m.group(6)) if m.group(6) is not None else 0
            return f"{y:04d}-{mo:02d}-{d:02d}T{hh:02d}:{mm_:02d}:{ss:02d}"
        except Exception:
            pass
    try:
        normalized = s.replace('/', '-').replace(' ', 'T')
        dt = datetime.fromisoformat(normalized)
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        return None


def process_bulletins(raw_data):
    """将原始公告数据清洗为需要的字段结构。"""
    items = extract_items(raw_data)
    processed = []
    for it in items:
        if not isinstance(it, dict):
            continue
        prj_type_id = it.get("prjTypeId") or it.get("projectTypeId") or it.get("typeId")
        publish_date_raw = it.get("publishDate") or it.get("fbDate") or it.get("pubDate")
        publish_date_ymd = parse_date_to_ymd(publish_date_raw)
        raw_bid = it.get("autoId") if it.get("autoId") is not None else (it.get("id") if it.get("id") is not None else it.get("bulletinId"))
        bulletin_id = str(raw_bid) if raw_bid is not None else None
        prj_id = it.get("prjId") or it.get("projectId") or it.get("prjid") or it.get("PrjId")
        prj_url = f"https://ygcg.nbcqjy.org/detail?bulletinId={bulletin_id}" if bulletin_id else None
        processed.append({
            "prjTypeId": prj_type_id,
            "publishDate": publish_date_ymd,
            "bulletinTitle": it.get("bulletinTitle") or it.get("title") or "",
            "bulletinContent": it.get("bulletinContent") or it.get("content") or "",
            "endDate": parse_to_iso_datetime(it.get("endDate") or it.get("bjEndDate") or it.get("deadline")),
            "prjNo": it.get("prjNo") or it.get("projectNo") or it.get("code"),
            "kbDate": parse_to_iso_datetime(it.get("kbDate") or it.get("openDate") or it.get("bidOpenDate")),
            "bulletinId": bulletin_id,
            "prjId": prj_id,
            "prjUrl": prj_url,
            "prjType": "其他项目",
            "prjContent": None
        })
    return processed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', type=str, default="", help='Base date YYYY-MM-DD (from GitHub Actions)')
    args = parser.parse_args()

    # 确定基准日期
    if args.date:
        try:
            base_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            base_date = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    else:
        base_date = datetime.now(ZoneInfo("Asia/Shanghai")).date()

    three_days_ago = base_date - timedelta(days=2)
    today = base_date

    print(f"🔍 基准日期：{base_date.strftime('%Y-%m-%d')}")
    print(f"📅 近三日范围：{three_days_ago} ~ {today}")

    try:
        # 1. 抓取
        data = fetch_purchase_bulletins()
        print("✅ 接口请求成功")

        # ★ 调试：打印原始返回前 1500 字符，确认接口是否返回了真实数据
        print("=== 🐛 原始接口返回（前1500字符）===")
        print(json.dumps(data, ensure_ascii=False)[:1500])
        print("=====================================")

        # 2. 清洗
        processed = process_bulletins(data)
        print(f"📦 清洗后公告总数：{len(processed)}")

        if not processed:
            print("⚠️ 清洗后0条数据！接口可能被反爬或返回结构有变。")
            save_json([], "purchase_bulletins.json")
            return

        # 3. 逐条打印发布时间，排查时差/字段问题
        print("📋 前10条公告的发布时间：")
        for b in processed[:10]:
            print(f"   [{b.get('publishDate')}] {b.get('bulletinTitle', '')[:30]}")

        # 4. 近三日过滤
        filtered = []
        for b in processed:
            pd = b.get("publishDate")
            if not pd:
                continue
            try:
                d = datetime.strptime(pd, "%Y-%m-%d").date()
                if three_days_ago <= d <= today:
                    filtered.append(b)
            except Exception:
                continue

        if filtered:
            dates = sorted(set(b.get('publishDate') for b in filtered if b.get('publishDate')))
            print(f"📊 匹配到的日期：{dates}")
        print(f"✅ 近三日公告数：{len(filtered)}")

        save_json(filtered, "purchase_bulletins.json")
        print("💾 已保存到 purchase_bulletins.json")

    except Exception as e:
        print(f"❌ 抓取失败: {e}")
        raise


if __name__ == "__main__":
    main()
