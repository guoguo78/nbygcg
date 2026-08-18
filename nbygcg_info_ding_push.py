import json
import os
from datetime import datetime, timedelta
from typing import List, Dict

import requests
import hashlib
import hmac
import base64
import urllib.parse
import time


def load_projects(file_path: str = 'opening_projects.json') -> List[Dict]:
    """加载开标项目数据"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('projects', [])
    except Exception as e:
        print(f"❌ 读取 {file_path} 失败: {e}")
        return []


def load_purchase_bulletins(file_path: str = 'purchase_bulletins.json') -> List[Dict]:
    """加载采购公告列表"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception as e:
        print(f"❌ 读取 {file_path} 失败: {e}")
        return []


def parse_iso_to_display(dt_str: str) -> str:
    """将 ISO 日期时间字符串转换为 'YYYY-MM-DD HH:MM'"""
    if not dt_str:
        return ""
    try:
        normalized = dt_str.replace(' ', 'T')
        dt = datetime.fromisoformat(normalized)
        return dt.strftime('%Y-%m-%d %H:%M')
    except Exception:
        try:
            d = datetime.strptime(dt_str[:10], '%Y-%m-%d')
            return d.strftime('%Y-%m-%d 00:00')
        except Exception:
            return ""


def is_hydrogen_related(text: str) -> bool:
    """判断是否为氢能/燃料电池相关业务（模糊匹配）"""
    if not text:
        return False
    keywords = ["氢", "燃料", "能源"]
    return any(kw in text.lower() for kw in keywords)


def filter_recent_bulletins(bulletins: List[Dict], days: int = 3) -> List[Dict]:
    """筛选近 N 天发布的氢能采购公告"""
    today = datetime.now().date()
    start_date = today - timedelta(days=days - 1)

    results = []
    for b in bulletins:
        prj_type = str(b.get('prjType', ''))
        title = str(b.get('bulletinTitle', ''))
        content = str(b.get('prjContent', ''))

        if not (is_hydrogen_related(prj_type) or is_hydrogen_related(title) or is_hydrogen_related(content)):
            continue

        pub_date_str = b.get('publishDate', '')
        if pub_date_str:
            try:
                pub_date = datetime.strptime(pub_date_str[:10], '%Y-%m-%d').date()
                if start_date <= pub_date <= today:
                    results.append(b)
            except (ValueError, TypeError):
                results.append(b)
        else:
            results.append(b)

    return results


def filter_tomorrow_projects(projects: List[Dict]) -> List[Dict]:
    """筛选明天开标的氢能项目"""
    tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    results = []

    for p in projects:
        prj_type = str(p.get('prjType', ''))
        if not is_hydrogen_related(prj_type):
            continue

        kb_date = str(p.get('kbDate') or p.get('openDate') or p.get('bidOpenDate') or '')[:10]
        if kb_date == tomorrow:
            results.append(p)

    return results


def truncate_content(text: str, max_len: int = 80) -> str:
    """压缩空白并截断内容"""
    if not text:
        return ""
    one_line = ' '.join(text.strip().split())
    if len(one_line) > max_len:
        one_line = one_line[:max_len].rstrip() + '……'
    return one_line


def generate_push_content(bulletins: List[Dict], projects: List[Dict]) -> str:
    """生成 Markdown 格式的钉钉推送内容"""
    lines: List[str] = []
    lines.append("## 🔋 阳光采购每日摘要（氢能/燃料电池）")
    lines.append(f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}
")

    # 近三日采购公告
    lines.append("### 📰 近三日新增氢能相关采购公告")
    if not bulletins:
        lines.append("- 近三日暂无新增氢能相关采购公告")
    else:
        for b in bulletins:
            title = b.get('bulletinTitle') or b.get('title') or '未命名项目'
            url = b.get('prjUrl')
            if not url and b.get('bulletinId'):
                url = f"https://www.nbygcg.com/bulletinDetail?id={b.get('bulletinId')}"

            pub_date = b.get('publishDate', '')
            kb_display = parse_iso_to_display(b.get('kbDate') or '')

            if url:
                date_info = f"（发布：{pub_date}"
                if kb_display:
                    date_info += f" | 开标：{kb_display.split(' ')[0]}"
                date_info += "）"
                lines.append(f"- [{title}]({url}) {date_info}")
            else:
                lines.append(f"- {title}（发布：{pub_date}）")

            prj_content = truncate_content(b.get('prjContent') or '')
            if prj_content:
                lines.append(f"  > {prj_content}")
        lines.append("")

    # 明日开标项目
    lines.append("### ⏰ 明日氢能业务开标项目")
    if not projects:
        lines.append("- 明日暂无氢能业务开标项目")
    else:
        for p in projects:
            name = p.get('prjName') or '未命名项目'
            url = p.get('prjUrl')
            if not url and p.get('bulletinId'):
                url = f"https://www.nbygcg.com/bulletinDetail?id={p.get('bulletinId')}"

            kb_display = parse_iso_to_display(p.get('kbDate') or p.get('openDate') or '')

            if url:
                if kb_display:
                    lines.append(f"- [{name}]({url})（开标：{kb_display}）")
                else:
                    lines.append(f"- [{name}]({url})")
            else:
                lines.append(f"- {name}")

            prj_content = truncate_content(p.get('prjContent') or '')
            if prj_content:
                lines.append(f"  > {prj_content}")
        lines.append("")

    return "
".join(lines)


def generate_sign(timestamp: int, secret: str) -> str:
    """生成钉钉签名"""
    string_to_sign = f'{timestamp}
{secret}'
    secret_enc = secret.encode('utf-8')
    string_to_sign_enc = string_to_sign.encode('utf-8')
    hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
    return urllib.parse.quote_plus(base64.b64encode(hmac_code).decode('utf-8'))


def send_dingtalk_notification(content: str):
    """发送钉钉群推送通知"""
    webhook_url = os.getenv('DINGTALK_WEBHOOK_URL')
    access_token = os.getenv('DINGTALK_ACCESS_TOKEN')
    secret = os.getenv('DINGTALK_SECRET')

    if not webhook_url or not access_token:
        print("⚠️ 未找到钉钉配置环境变量，跳过推送")
        return

    try:
        webhook = f"{webhook_url}?access_token={access_token}"
        if secret:
            timestamp = str(round(time.time() * 1000))
            sign = generate_sign(int(timestamp), secret)
            webhook += f'&timestamp={timestamp}&sign={sign}'

        headers = {'Content-Type': 'application/json; charset=utf-8'}
        data = {
            "msgtype": "markdown",
            "markdown": {
                "title": "阳光采购每日摘要（氢能/燃料电池）",
                "text": content
            }
        }
        response = requests.post(webhook, headers=headers, json=data, timeout=10)
        result = response.json()
        if result.get('errcode') == 0:
            print("✅ 钉钉推送成功")
        else:
            print(f"❌ 钉钉推送失败: {result.get('errmsg')}")
    except Exception as e:
        print(f"❌ 钉钉推送异常: {e}")


def main():
    print("
" + "=" * 50)
    print("🚀 开始执行氢能招标推送脚本...")

    projects = load_projects()
    bulletins = load_purchase_bulletins()

    print(f"📂 读取到 {len(bulletins)} 条公告, {len(projects)} 条开标项目")

    recent_bulletins = filter_recent_bulletins(bulletins, days=3)
    tomorrow_projects = filter_tomorrow_projects(projects)

    print(f"🎯 筛选结果: {len(recent_bulletins)} 条近三日氢能公告, {len(tomorrow_projects)} 条明日氢能开标")

    push_content = generate_push_content(recent_bulletins, tomorrow_projects)
    print("
📋 推送内容预览:")
    print(push_content)

    send_dingtalk_notification(push_content)


if __name__ == "__main__":
    main()
