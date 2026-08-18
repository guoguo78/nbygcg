import json
from datetime import datetime, timedelta
import hashlib
import hmac
import base64
from typing import List, Dict, Optional
import os
import requests
import urllib.parse
import time

# ========== 配置区域 ==========
# 调试模式：开启后会打印详细筛选日志，方便排查无数据问题
DEBUG_MODE = True
# 氢能关键词（可根据实际需求增减）
HYDROGEN_KEYWORDS = ["氢", "掺氢", "燃料电池", "氢能", "SOFC"]
# 近N日公告（含今天）
RECENT_DAYS = 3

def load_projects(file_path: str = 'opening_projects.json') -> List[Dict]:
    """加载开标项目数据（兼容GitHub Actions运行环境）"""
    try:
        # GitHub Actions运行时工作目录为仓库根目录，无需拼接路径
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            projects = data.get('projects', [])
            if DEBUG_MODE:
                print(f"[DEBUG] 成功加载 {len(projects)} 条开标项目")
                if projects:
                    print(f"[DEBUG] 开标项目字段示例: {list(projects[0].keys())}")
            return projects
    except FileNotFoundError:
        print(f"❌ 错误: 找不到文件 {file_path}，请确认fetch_opening_projects.py已成功运行")
        return []
    except Exception as e:
        print(f"❌ 加载开标项目失败: {e}")
        return []

def load_purchase_bulletins(file_path: str = 'purchase_bulletins.json') -> List[Dict]:
    """加载采购公告列表（兼容GitHub Actions运行环境）"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            bulletins = data if isinstance(data, list) else []
            if DEBUG_MODE:
                print(f"[DEBUG] 成功加载 {len(bulletins)} 条采购公告")
                if bulletins:
                    print(f"[DEBUG] 采购公告字段示例: {list(bulletins[0].keys())}")
            return bulletins
    except FileNotFoundError:
        print(f"❌ 错误: 找不到文件 {file_path}，请确认fetch_purchase_bulletins.py已成功运行")
        return []
    except Exception as e:
        print(f"❌ 加载采购公告失败: {e}")
        return []

def truncate_content(text: str, max_len: int = 80) -> str:
    """截断长文本，避免推送消息过长"""
    if not text:
        return ""
    # 压缩空白字符，兼容非字符串类型
    one_line = ' '.join(str(text).split())
    if len(one_line) > max_len:
        return one_line[:max_len].rstrip() + '……'
    return one_line

def parse_iso_to_display(dt_str: Optional[str]) -> str:
    """将日期时间字符串转换为 'YYYY-MM-DD HH:MM'，失败返回空串"""
    if not dt_str or not isinstance(dt_str, str):
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

def _is_hydrogen(text: str) -> bool:
    """判断文本是否包含氢能相关关键词"""
    if not text:
        return False
    text = str(text).lower()
    return any(kw in text for kw in HYDROGEN_KEYWORDS)

def filter_recent_bulletins(bulletins: List[Dict]) -> List[Dict]:
    """
    筛选近N日新增的氢能相关采购公告
    逻辑：标题/类型包含氢能关键词 + 发布日期在近N天内
    """
    today = datetime.now()
    start_date = today - timedelta(days=RECENT_DAYS - 1)  # 包含今天
    filtered = []

    for b in bulletins:
        title = str(b.get('bulletinTitle', '') or b.get('title', ''))
        prj_type = str(b.get('prjType', ''))
        pub_date_str = b.get('publishDate')

        # 1. 关键词筛选
        is_hydrogen_match = _is_hydrogen(title) or _is_hydrogen(prj_type)
        # 2. 日期筛选（仅当发布日期存在时校验）
        is_date_match = False
        if pub_date_str and isinstance(pub_date_str, str):
            try:
                pub_date = datetime.strptime(pub_date_str[:10], '%Y-%m-%d')
                is_date_match = start_date <= pub_date <= today
            except ValueError:
                # 日期格式异常时默认保留，避免漏推
                is_date_match = True
                if DEBUG_MODE:
                    print(f"[DEBUG] 公告日期格式异常: {pub_date_str}，默认保留")

        # 调试输出
        if DEBUG_MODE:
            status = []
            if not is_hydrogen_match:
                status.append("未匹配氢能关键词")
            if pub_date_str and not is_date_match:
                status.append(f"发布日期不在近{RECENT_DAYS}天内")
            if is_hydrogen_match and is_date_match:
                status.append("✅ 符合条件，保留")
            print(f"[DEBUG] 公告: {title[:30]}... | {' | '.join(status)}")

        if is_hydrogen_match and is_date_match:
            filtered.append(b)

    return filtered

def filter_tomorrow_projects(projects: List[Dict]) -> List[Dict]:
    """筛选开标时间为明天的氢能项目"""
    tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    filtered = []

    for p in projects:
        prj_name = str(p.get('prjName', ''))
        prj_type = str(p.get('prjType', ''))
        kb_date = p.get('kbDate') or p.get('openDate')  # 兼容不同字段名

        # 1. 关键词筛选
        is_hydrogen_match = _is_hydrogen(prj_name) or _is_hydrogen(prj_type)
        # 2. 日期筛选（仅当开标日期存在且为字符串时校验）
        is_date_match = False
        if kb_date and isinstance(kb_date, str):
            is_date_match = kb_date[:10] == tomorrow

        # 调试输出
        if DEBUG_MODE:
            status = []
            if not is_hydrogen_match:
                status.append("未匹配氢能关键词")
            if kb_date and not is_date_match:
                status.append(f"开标日期不是明天（实际: {kb_date[:10]}）")
            if is_hydrogen_match and is_date_match:
                status.append("✅ 符合条件，保留")
            print(f"[DEBUG] 项目: {prj_name[:30]}... | {' | '.join(status)}")

        if is_hydrogen_match and is_date_match:
            filtered.append(p)

    return filtered

def generate_push_content(recent_bulletins: List[Dict], tomorrow_projects: List[Dict]) -> str:
    """生成合并后的Markdown推送内容"""
    lines: List[str] = []

    # 标题
    lines.append("## 📊 阳光采购每日摘要（氢能/燃料电池）")
    lines.append(f"> 统计周期：近{RECENT_DAYS}天公告 | 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

    # 1. 近三日新增氢能采购公告
    lines.append(f"### 🆕 近{RECENT_DAYS}日新增氢能相关采购公告")
    # 🔴 修复：原代码变量名错误（recent_bulletin → recent_bulletins）
    if not recent_bulletins:
        lines.append("- 近三日无新增氢能相关采购公告")
    else:
        for b in recent_bulletins:
            title = b.get('bulletinTitle') or b.get('title') or '未命名项目'
            url = b.get('prjUrl')

            # 如果没有URL，尝试用bulletinId拼凑（宁波阳光采购通用格式）
            if not url and b.get('bulletinId'):
                url = f"https://www.nbygcg.com/bulletinDetail?id={b.get('bulletinId')}"

            publish_date = parse_iso_to_display(b.get('publishDate'))
            kb_date = parse_iso_to_display(b.get('kbDate'))

            # 拼接展示文本
            date_info = []
            if publish_date:
                date_info.append(f"发布：{publish_date}")
            if kb_date:
                date_info.append(f"开标：{kb_date}")

            if url:
                lines.append(f"- [{title}]({url})（{' | '.join(date_info)}）")
            else:
                lines.append(f"- {title}（{' | '.join(date_info)}）")

            # 追加内容摘要
            content = truncate_content(b.get('prjContent', ''), 60)
            if content:
                lines.append(f"  > {content}")
        lines.append("")  # 空行分隔

    # 2. 明日开标项目
    lines.append("### ⏰ 明日氢能业务开标项目")
    if not tomorrow_projects:
        lines.append("- 明日暂无氢能业务开标项目")
    else:
        for p in tomorrow_projects:
            name = p.get('prjName') or '未命名项目'
            url = p.get('prjUrl')

            if not url and p.get('bulletinId'):
                url = f"https://www.nbygcg.com/bulletinDetail?id={p.get('bulletinId')}"

            kb_display = parse_iso_to_display(p.get('kbDate') or p.get('openDate'))

            if url:
                if kb_display:
                    lines.append(f"- [{name}]({url})（开标：{kb_display}）")
                else:
                    lines.append(f"- [{name}]({url})")
            else:
                lines.append(f"- {name}")

            # 追加内容摘要
            content = truncate_content(p.get('prjContent', ''), 60)
            if content:
                lines.append(f"  > {content}")
        lines.append("")  # 空行分隔

    return "\n".join(lines)

def generate_sign(timestamp: int, secret: str) -> str:
    """生成钉钉签名"""
    string_to_sign = f'{timestamp}\n{secret}'
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
        print("⚠️ 未找到钉钉配置环境变量，请检查GitHub Secrets配置")
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
                "title": f"氢能招标日报 {datetime.now().strftime('%Y-%m-%d')}",
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
    print("\n" + "=" * 50)
    print("🚀 开始执行氢能招标推送脚本...")

    # 1. 加载数据
    projects = load_projects()
    bulletins = load_purchase_bulletins()

    # 2. 筛选数据
    recent_bulletins = filter_recent_bulletins(bulletins)
    tomorrow_projects = filter_tomorrow_projects(projects)

    print(f"\n🎯 最终筛选结果:")
    print(f"  近{RECENT_DAYS}日氢能公告: {len(recent_bulletins)} 条")
    print(f"  明日氢能开标项目: {len(tomorrow_projects)} 条")

    # 3. 生成推送内容
    push_content = generate_push_content(recent_bulletins, tomorrow_projects)
    print("\n📋 推送内容预览:")
    print(push_content)

    # 4. 发送推送
    send_dingtalk_notification(push_content)

if __name__ == "__main__":
    main()
