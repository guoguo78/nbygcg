import json
import os
import hmac
import hashlib
import base64
import time
import urllib.parse
from datetime import datetime, timedelta
from typing import List, Dict

import requests


# ========== 数据加载 ==========

def load_projects(file_path: str) -> List[Dict]:
    """加载开标项目数据"""
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        return data.get('projects', [])


def load_purchase_bulletins(file_path: str = 'purchase_bulletins.json') -> List[Dict]:
    """加载采购公告列表"""
    if not os.path.exists(file_path):
        return []
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        return data if isinstance(data, list) else []


# ========== 类型匹配（模糊匹配，不再依赖精确名称）==========

def is_hydrogen_related(prj_type: str) -> bool:
    """判断是否为氢能/燃料电池相关业务（模糊匹配）"""
    if not prj_type:
        return False
    keywords = ["氢", "燃料", "能源", "fcev", "fuel cell"]
    return any(kw in prj_type.lower() for kw in keywords)


# ========== 日期过滤 ==========

def filter_tomorrow_projects(projects: List[Dict]) -> Dict[str, List[Dict]]:
    """筛选明天开标的氢能项目"""
    tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    grouped: Dict[str, List[Dict]] = {"氢能相关业务": []}
    for project in projects:
        prj_type = project.get('prjType', '')
        if not is_hydrogen_related(prj_type):
            continue
        kb_date = project.get('kbDate') or ''
        # ★ 修复：kbDate 是 ISO 格式，只取前10位比较
        kb_date_short = kb_date[:10] if len(kb_date) >= 10 else kb_date
        if kb_date_short == tomorrow:
            grouped["氢能相关业务"].append(project)
    return grouped


def filter_recent_bulletins(bulletins: List[Dict], days: int = 3) -> Dict[str, List[Dict]]:
    """
    筛选近 N 天发布的氢能采购公告。
    days=3 表示：今天、昨天、前天
    """
    today = datetime.now().date()
    start_date = today - timedelta(days=days - 1)  # days-1 因为包含今天

    grouped: Dict[str, List[Dict]] = {"氢能相关业务": []}
    for b in bulletins:
        prj_type = b.get('prjType', '')
        if not is_hydrogen_related(prj_type):
            continue
        pub_date = b.get('publishDate') or ''
        if not pub_date:
            continue
        try:
            d = datetime.strptime(pub_date[:10], '%Y-%m-%d').date()
            if start_date <= d <= today:
                grouped["氢能相关业务"].append(b)
        except (ValueError, TypeError):
            continue
    return grouped


# ========== 内容生成 ==========

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


def truncate_content(text: str, max_len: int = 500) -> str:
    """压缩空白并截断内容"""
    if not text:
        return ""
    one_line = ' '.join(text.strip().split())
    if len(one_line) > max_len:
        one_line = one_line[:max_len].rstrip() + '……'
    return one_line


def generate_push_content(recent_bulletins: Dict[str, List[Dict]], tomorrow_projects: Dict[str, List[Dict]]) -> str:
    """生成推送内容"""
    lines: List[str] = []
    lines.append("## 🔋 阳光采购每日摘要（氢能/燃料电池）")

    # ---- 近三日新增采购公告 ----
    lines.append("\n### 📋 近三日新增氢能相关采购公告")
    bulletin_items = recent_bulletins.get("氢能相关业务", [])
    if not bulletin_items:
        lines.append("- 近三日无新增采购公告")
    else:
        for it in bulletin_items:
            title = it.get('bulletinTitle') or it.get('title') or '未命名项目'
            pub_date = it.get('publishDate', '')
            url = it.get('prjUrl')
            if not url:
                continue
            kb_display = parse_iso_to_display(it.get('kbDate') or '')
            if kb_display:
                lines.append(f"- [{title}]({url})（发布：{pub_date} | 开标：{kb_display}）")
            else:
                lines.append(f"- [{title}]({url})（发布：{pub_date}）")
            # 采购内容摘要
            prj_content = truncate_content(it.get('prjContent') or '')
            if prj_content:
                lines.append(f"  > {prj_content}")
        lines.append("")

    # ---- 明日开标项目 ----
    lines.append("\n### ⏰ 明日氢能业务开标项目")
    project_items = tomorrow_projects.get("氢能相关业务", [])
    if not project_items:
        lines.append("- 明日无开标项目")
    else:
        for project in project_items:
            project_url = project.get('prjUrl')
            if not project_url:
                continue
            prj_name = project.get('prjName') or '未命名项目'
            kb_display = parse_iso_to_display(project.get('kbDate') or '')
            if kb_display:
                lines.append(f"- [{prj_name}]({project_url})（开标：{kb_display}）")
            else:
                lines.append(f"- [{prj_name}]({project_url})")
            prj_content = truncate_content(project.get('prjContent') or '')
            if prj_content:
                lines.append(f"  > {prj_content}")
        lines.append("")

    return "\n".join(lines)


# ========== 钉钉推送 ==========

def generate_sign(timestamp: int, secret: str) -> str:
    string_to_sign = f'{timestamp}\n{secret}'
    secret_enc = secret.encode('utf-8')
    string_to_sign_enc = string_to_sign.encode('utf-8')
    hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
    return urllib.parse.quote_plus(base64.b64encode(hmac_code).decode('utf-8'))


def send_dingtalk_notification(content: str):
    """发送钉钉群推送通知（从环境变量读取配置，不再依赖 .env 文件）"""
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


# ========== 主函数 ==========

def main():
    # 加载数据
    projects = load_projects('opening_projects.json')
    bulletins = load_purchase_bulletins('purchase_bulletins.json')

    # 筛选
    tomorrow_projects = filter_tomorrow_projects(projects)
    recent_bulletins = filter_recent_bulletins(bulletins, days=3)

    # 统计日志
    b_count = len(recent_bulletins.get("氢能相关业务", []))
    p_count = len(tomorrow_projects.get("氢能相关业务", []))
    print(f"📊 近三日公告: {b_count} 条 | 明日开标: {p_count} 条")

    # 生成并推送
    push_content = generate_push_content(recent_bulletins, tomorrow_projects)
    print(push_content)
    send_dingtalk_notification(push_content)


if __name__ == "__main__":
    main()
