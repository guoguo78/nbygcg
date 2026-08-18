import json
from datetime import datetime, timedelta
import hashlib
import hmac
import base64
from typing import List, Dict
import os
import requests
import urllib.parse
import time

# ========== 调试开关 ==========
DEBUG_MODE = True  # 开启调试，会在日志里打印所有数据

def load_projects(file_path: str = 'opening_projects.json') -> List[Dict]:
    """加载开标项目数据"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('projects', [])
    except FileNotFoundError:
        return []

def load_purchase_bulletins(file_path: str = 'purchase_bulletins.json') -> List[Dict]:
    """加载采购公告列表"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except FileNotFoundError:
        return []

def parse_iso_to_display(dt_str: str) -> str:
    """将 ISO 日期时间字符串转换为 'YYYY-MM-DD HH:MM'"""
    if not dt_str: return ""
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

def filter_recent_bulletins(bulletins: List[Dict]) -> Dict[str, List[Dict]]:
    """筛选近三日新增的采购公告（模糊匹配氢能类型）"""
    target_types = ["氢能相关业务", "氢能", "燃料电池", "氢能源"]
    grouped: Dict[str, List[Dict]] = {pt: [] for pt in target_types}
    
    today = datetime.now()
    three_days_ago = (today - timedelta(days=3)).strftime('%Y-%m-%d')
    
    if DEBUG_MODE:
        print(f"
[DEBUG] === 开始筛选公告 (近3日: {three_days_ago} 至今) ===")
        print(f"[DEBUG] 原始公告总数: {len(bulletins)}")

    for b in bulletins:
        prj_type = str(b.get('prjType', '')).strip()
        pub_date = b.get('publishDate')
        
        # 放宽条件：只要类型包含 氢/燃料/能源 就认为是氢能
        is_hydrogen = any(keyword in prj_type for keyword in ["氢", "燃料", "能源"])
        
        if is_hydrogen and pub_date and pub_date >= three_days_ago:
            # 归类到最匹配的类型下
            for tt in target_types:
                if tt in prj_type:
                    grouped[tt].append(b)
                    break
            
            if DEBUG_MODE:
                print(f"[DEBUG] ✅ 命中氢能公告: {b.get('bulletinTitle')[:30]}... | 日期: {pub_date}")

    return grouped

def filter_tomorrow_projects(projects: List[Dict]) -> Dict[str, List[Dict]]:
    """筛选明日开标项目（模糊匹配氢能类型 + 兼容不同时间字段名）"""
    target_types = ["氢能相关业务", "氢能", "燃料电池", "氢能源"]
    grouped: Dict[str, List[Dict]] = {pt: [] for pt in target_types}
    
    tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    
    if DEBUG_MODE:
        print(f"
[DEBUG] === 开始筛选项目 (目标日期: {tomorrow}) ===")
        print(f"[DEBUG] 原始项目总数: {len(projects)}")

    for project in projects:
        prj_type = str(project.get('prjType', '')).strip()
        # ★ 关键修改：同时尝试 kbDate 和 openDate，防止字段名不对
        kb_date = project.get('kbDate') or project.get('openDate') 
        kb_date_str = str(kb_date)[:10] if kb_date else ""

        is_hydrogen = any(keyword in prj_type for keyword in ["氢", "燃料", "能源"])
        
        if is_hydrogen and kb_date_str == tomorrow:
            for tt in target_types:
                if tt in prj_type:
                    grouped[tt].append(project)
                    break
                    
            if DEBUG_MODE:
                print(f"[DEBUG] ✅ 命中明日开标: {project.get('prjName')[:30]}... | 日期字段: {kb_date_str}")

    return grouped

def generate_push_content(yesterday_bulletins: Dict[str, List[Dict]], tomorrow_projects: Dict[str, List[Dict]]) -> str:
    """生成合并后的推送内容"""
    lines: List[str] = []
    lines.append("## 阳光采购每日摘要（氢能/燃料电池）")

    # 1. 昨日采购公告
    lines.append("
### 📰 近三日新增氢能相关采购公告")
    has_data = False
    for pt, items in yesterday_bulletins.items():
        if items:
            has_data = True
            lines.append(f"#### 类型：{pt}")
            for it in items:
                title = it.get('bulletinTitle') or it.get('title') or '未命名'
                url = it.get('prjUrl')
                if url:
                    # ★ 关键修改：增加发布日期和开标日期的显示
                    pub_date = it.get('publishDate', '未知')
                    kb_display = parse_iso_to_display(it.get('kbDate') or '')
                    
                    date_info = f"(发布：{pub_date}"
                    if kb_display: date_info += f" | 开标：{kb_display.split(' ')[0]}"
                    date_info += ")"
                    
                    lines.append(f"- [{title}]({url}) {date_info}")
                    
                    # 显示采购内容
                    content = (it.get('prjContent') or '').strip()
                    if content:
                        one_line = ' '.join(content.split())[:80]
                        lines.append(f"  > {one_line}...")
            lines.append("")
            
    if not has_data:
        lines.append("- 近三日暂无新增氢能相关采购公告")
        
    # 2. 明日开标项目
    lines.append("
### ⏰ 明日氢能业务开标项目")
    has_data = False
    for pt, items in tomorrow_projects.items():
        if items:
            has_data = True
            lines.append(f"#### 类型：{pt}")
            for project in items:
                title = project.get('prjName', '未命名')
                url = project.get('prjUrl')
                if url:
                    lines.append(f"- [{title}]({url})")
                    # 显示采购内容
                    content = (project.get('prjContent') or '').strip()
                    if content:
                        one_line = ' '.join(content.split())[:80]
                        lines.append(f"  > {one_line}...")
            lines.append("")
            
    if not has_data:
        lines.append("- 明日暂无氢能业务开标项目")
        
    return "
".join(lines)

def generate_sign(timestamp: int, secret: str) -> str:
    string_to_sign = '{}
{}'.format(timestamp, secret)
    secret_enc = secret.encode('utf-8')
    string_to_sign_enc = string_to_sign.encode('utf-8')
    hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
    return urllib.parse.quote_plus(base64.b64encode(hmac_code).decode('utf-8'))

def send_dingtalk_notification(content: str):
    webhook_url = os.getenv('DINGTALK_WEBHOOK_URL')
    access_token = os.getenv('DINGTALK_ACCESS_TOKEN')
    secret = os.getenv('DINGTALK_SECRET')

    if not webhook_url or not access_token:
        print("⚠️ 未找到钉钉配置，跳过推送")
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
                "title": "氢能招标日报",
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
    # 1. 加载数据
    projects = load_projects()
    bulletins = load_purchase_bulletins()

    if DEBUG_MODE:
        print(f"
[DEBUG] 读取 opening_projects.json 成功，共 {len(projects)} 条")
        print(f"[DEBUG] 读取 purchase_bulletins.json 成功，共 {len(bulletins)} 条")
        # 打印第一条数据的字段名，供你核对
        if projects: print(f"[DEBUG] 项目样例字段: {list(projects[0].keys())}")
        if bulletins: print(f"[DEBUG] 公告样例字段: {list(bulletins[0].keys())}")


    # 2. 筛选
    tomorrow_projects = filter_tomorrow_projects(projects)
    recent_bulletins = filter_recent_bulletins(bulletins)

    # 3. 生成内容
    push_content = generate_push_content(recent_bulletins, tomorrow_projects)
    
    # ★ 关键：打印最终要发送的内容，如果这里是空的，钉钉肯定也是空的
    print("
================== [DEBUG] 最终生成的推送内容 ==================
")
    print(push_content)
    print("
============================================================
")

    # 4. 发送
    send_dingtalk_notification(push_content)

if __name__ == "__main__":
    main()
