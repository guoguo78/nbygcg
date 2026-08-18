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

# ========== 配置区域 ==========
# 调试模式：开启后会打印更多日志，方便排查数据问题
DEBUG_MODE = True

def load_projects(file_path: str = 'opening_projects.json') -> List[Dict]:
    """加载开标项目数据"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    full_path = os.path.join(current_dir, file_path)
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('projects', [])
    except FileNotFoundError:
        print(f"❌ 错误: 找不到文件 {file_path}")
        return []

def load_purchase_bulletins(file_path: str = 'purchase_bulletins.json') -> List[Dict]:
    """加载采购公告列表"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    full_path = os.path.join(current_dir, file_path)
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return []
    except FileNotFoundError:
        print(f"❌ 错误: 找不到文件 {file_path}")
        return []

def truncate_content(text: str, max_len: int = 80) -> str:
    """截断长文本，避免推送消息过长"""
    if not text:
        return ""
    # 压缩空白字符
    one_line = ' '.join(str(text).split())
    if len(one_line) > max_len:
        return one_line[:max_len].rstrip() + '……'
    return one_line

def parse_iso_to_display(dt_str: str) -> str:
    """将 ISO 日期时间字符串转换为 'YYYY-MM-DD HH:MM'，失败返回空串"""
    if not dt_str:
        return ""
    try:
        # 兼容 'YYYY-MM-DDTHH:MM:SS' 或 'YYYY-MM-DD HH:MM:SS'
        normalized = dt_str.replace(' ', 'T')
        dt = datetime.fromisoformat(normalized)
        return dt.strftime('%Y-%m-%d %H:%M')
    except Exception:
        # 若仅有日期
        try:
            d = datetime.strptime(dt_str[:10], '%Y-%m-%d')
            return d.strftime('%Y-%m-%d 00:00')
        except Exception:
            return ""

def filter_recent_bulletins(bulletins: List[Dict], days: int = 3) -> List[Dict]:
    """
    筛选近 N 日新增的氢能相关采购公告
    逻辑：只要标题或类型包含'氢'、'燃料'、'能源'等关键词，且日期在近 N 天内
    """
    target_keywords = ["氢", "燃料", "能源", "燃料电池", "氢能"]
    
    # 计算日期范围
    today = datetime.now()
    start_date = today - timedelta(days=days-1)
    start_date_str = start_date.strftime('%Y-%m-%d')
    
    filtered = []
    for b in bulletins:
        pub_date = b.get('publishDate')
        if not pub_date:
            continue
            
        # 1. 日期筛选 (兼容 '2026-08-18' 和 '2026-08-18 00:00:00')
        pub_date_only = pub_date[:10]
        if pub_date_only < start_date_str:
            continue
            
        # 2. 关键词筛选 (标题、类型)
        title = str(b.get('bulletinTitle') or b.get('title') or '')
        prj_type = str(b.get('prjType') or '')
        
        is_hydrogen = False
        for kw in target_keywords:
            if kw in title or kw in prj_type:
                is_hydrogen = True
                break
                
        if is_hydrogen:
            filtered.append(b)
            
    return filtered

def filter_tomorrow_projects(projects: List[Dict]) -> List[Dict]:
    """筛选开标时间为明天的氢能项目"""
    target_keywords = ["氢", "燃料", "能源", "燃料电池", "氢能"]
    tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    
    filtered = []
    for p in projects:
        kb_date = p.get('kbDate') or p.get('openDate')
        if not kb_date:
            continue
            
        # 只比较日期部分
        if kb_date[:10] != tomorrow:
            continue
            
        # 检查是否包含氢能关键词
        prj_name = str(p.get('prjName') or '')
        prj_type = str(p.get('prjType') or '')
        
        is_hydrogen = False
        for kw in target_keywords:
            if kw in prj_name or kw in prj_type:
                is_hydrogen = True
                break
                
        if is_hydrogen:
            filtered.append(p)
            
    return filtered

def generate_push_content(recent_bulletins: List[Dict], tomorrow_projects: List[Dict]) -> str:
    """生成合并后的 Markdown 推送内容"""
    lines: List[str] = []
    
    # 标题
    lines.append("## 📊 阳光采购每日摘要（氢能/燃料电池）")
    
    # 1. 近三日新增氢能采购公告
    lines.append("
### 🆕 近三日新增氢能相关采购公告")
    
    if not recent_bulletin:
        lines.append("- 近三日无新增氢能相关采购公告")
    else:
        for b in recent_bulletins:
            title = b.get('bulletinTitle') or b.get('title') or '未命名项目'
            url = b.get('prjUrl')
            
            # 如果没有 URL，尝试用 bulletinId 拼凑（备用逻辑）
            if not url and b.get('bulletinId'):
                url = f"https://www.nbygcg.com/bulletinDetail?id={b.get('bulletinId')}"
                
            publish_date = parse_iso_to_display(b.get('publishDate') or '')
            
            if url:
                if publish_date:
                    lines.append(f"- [{title}]({url})（发布：{publish_date}）")
                else:
                    lines.append(f"- [{title}]({url})")
            else:
                lines.append(f"- {title}")
                
            # 追加摘要
            content = truncate_content(b.get('prjContent') or '', 60)
            if content:
                lines.append(f"  > {content}")
        lines.append("")

    # 2. 明日开标项目
    lines.append("
### ⏰ 明日氢能业务开标项目")
    
    if not tomorrow_projects:
        lines.append("- 明日暂无氢能业务开标项目")
    else:
        for p in tomorrow_projects:
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
                
            # 追加摘要
            content = truncate_content(p.get('prjContent') or '', 60)
            if content:
                lines.append(f"  > {content}")
        lines.append("")

    # 添加底部生成时间
    lines.append(f"
> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
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
    print("
" + "=" * 50)
    print("🚀 开始执行氢能招标推送脚本...")

    # 1. 加载数据
    projects = load_projects()
    bulletins = load_purchase_bulletins()
    
    print(f"📂 读取到 {len(bulletins)} 条公告, {len(projects)} 条开标项目")

    # 2. 筛选
    recent_bulletins = filter_recent_bulletins(bulletins, days=3)
    tomorrow_projects = filter_tomorrow_projects(projects)
    
    print(f"🎯 筛选结果: {len(recent_bulletins)} 条近三日氢能公告, {len(tomorrow_projects)} 条明日氢能开标")

    # 3. 生成内容
    push_content = generate_push_content(recent_bulletins, tomorrow_projects)
    print("
📋 推送内容预览:")
    print(push_content)

    # 4. 发送
    send_dingtalk_notification(push_content)

if __name__ == "__main__":
    main()
