import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
from openai import OpenAI

# ★ 已移除 dotenv 依赖（GitHub Actions 通过 Secrets 注入环境变量，不需要 .env 文件）

DEFAULT_TIMEOUT = 20
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def read_opening_projects(path: str = "opening_projects.json") -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[WARN] 文件不存在: {path}")
        return None
    except Exception as e:
        print(f"[ERROR] 读取 {path} 失败: {e}")
        return None


def read_purchase_bulletins(path: str = "purchase_bulletins.json") -> Optional[List[Dict[str, Any]]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[WARN] 文件不存在: {path}")
        return None
    except Exception as e:
        print(f"[ERROR] 读取 {path} 失败: {e}")
        return None


def save_json(content: Any, path: str) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=4)
        print(f"[INFO] 已保存: {path}")
    except Exception as e:
        print(f"[ERROR] 保存 {path} 失败: {e}")


# 基础 HTML 清洗
TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_STYLE_RE = re.compile(r"<\s*(script|style)[^>]*>.*?<\s*/\s*\1\s*>", re.I | re.S)
WHITESPACE_RE = re.compile(r"[ \t\r\f\v]+")


def html_to_text(html: str) -> str:
    if not html:
        return ""
    html = SCRIPT_STYLE_RE.sub(" ", html)
    text = TAG_RE.sub(" ", html)
    try:
        import html as html_lib
        text = html_lib.unescape(text)
    except Exception:
        pass
    text = WHITESPACE_RE.sub(" ", text)
    text = re.sub(r"\n+", "\n", text)
    return text.strip()


def fetch_page_text(url: str, timeout: int = DEFAULT_TIMEOUT) -> Optional[str]:
    if not url:
        return None
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or resp.encoding or "utf-8"
        return html_to_text(resp.text)
    except Exception as e:
        print(f"[WARN] 请求失败: {url} -> {e}")
        return None


def fetch_opening_inquire_text(prj_id: str, timeout: int = DEFAULT_TIMEOUT) -> Optional[str]:
    if not prj_id:
        return None
    url = f"https://ygcg.nbcqjy.org:8075/api/Notoken/GetOnlineInquire?PrjId={prj_id}"
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": HEADERS["User-Agent"], "Accept": "*/*"},
            timeout=timeout,
            verify=True,
        )
        resp.raise_for_status()
        try:
            data = resp.json()
            body = data.get("Body") if isinstance(data, dict) else None
            detail = body.get("Data") if isinstance(body, dict) else None
            remark = detail.get("Remark") if isinstance(detail, dict) else None
            if isinstance(remark, str) and remark.strip():
                return html_to_text(remark)
            prj_content = detail.get("PrjContent") if isinstance(detail, dict) else None
            if isinstance(prj_content, str) and prj_content.strip():
                return html_to_text(prj_content)

            text_candidates: List[str] = []

            def walk(v: Any):
                if isinstance(v, dict):
                    for k, vv in v.items():
                        if isinstance(vv, (dict, list)):
                            walk(vv)
                        elif isinstance(vv, str):
                            if any(x in k.lower() for x in ["remark", "prjcontent", "content", "html", "memo", "desc", "inquire", "text"]):
                                text_candidates.append(vv)
                elif isinstance(v, list):
                    for it in v:
                        walk(it)
                elif isinstance(v, str):
                    text_candidates.append(v)

            walk(data)
            merged = "\n".join([t for t in text_candidates if t and isinstance(t, str)])
            merged = merged.strip()
            if merged:
                return html_to_text(merged)
        except ValueError:
            pass
        resp.encoding = resp.apparent_encoding or resp.encoding or "utf-8"
        return html_to_text(resp.text)
    except Exception as e:
        print(f"[WARN] 开标接口请求失败: {url} -> {e}")
        return None


def fetch_bulletin_text(auto_id: str, timeout: int = DEFAULT_TIMEOUT) -> Optional[str]:
    if not auto_id:
        return None
    url = "https://ygcg.nbcqjy.org/api/Portal/GetBulletinContent"
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "User-Agent": HEADERS["User-Agent"],
        "Accept": "application/json, text/plain, */*",
    }
    try:
        resp = requests.post(url, headers=headers, data=json.dumps({"autoID": auto_id}), timeout=timeout)
        resp.raise_for_status()
        try:
            data = resp.json()

            def get_case_insensitive(d: Any, key: str) -> Any:
                if not isinstance(d, dict):
                    return None
                for k, v in d.items():
                    if isinstance(k, str) and k.lower() == key.lower():
                        return v
                return None

            article = None
            root = data
            level = get_case_insensitive(root, "body") or get_case_insensitive(root, "Body")
            if level is not None:
                level = get_case_insensitive(level, "data") or get_case_insensitive(level, "Data")
                if level is not None:
                    article = get_case_insensitive(level, "article") or get_case_insensitive(level, "Article")
            if isinstance(article, dict):
                bc = get_case_insensitive(article, "bulletinContent")
                if isinstance(bc, str) and bc.strip():
                    return html_to_text(bc)

            body_alt = get_case_insensitive(root, "body") or get_case_insensitive(root, "Body")
            data_alt = get_case_insensitive(body_alt, "data") or get_case_insensitive(body_alt, "Data") if isinstance(body_alt, dict) else None
            bc2 = get_case_insensitive(data_alt, "bulletinContent") if isinstance(data_alt, dict) else None
            if isinstance(bc2, str) and bc2.strip():
                return html_to_text(bc2)

            text_candidates: List[str] = []

            def walk(v: Any):
                if isinstance(v, dict):
                    for k, vv in v.items():
                        if isinstance(vv, (dict, list)):
                            walk(vv)
                        elif isinstance(vv, str):
                            if any(x in k.lower() for x in ["bulletincontent", "content", "html", "body", "remark", "desc", "text"]):
                                text_candidates.append(vv)
                elif isinstance(v, list):
                    for it in v:
                        walk(it)
                elif isinstance(v, str):
                    text_candidates.append(v)

            walk(data)
            merged = "\n".join([t for t in text_candidates if t and isinstance(t, str)])
            merged = merged.strip()
            if merged:
                return html_to_text(merged)
        except ValueError:
            pass
        resp.encoding = resp.apparent_encoding or resp.encoding or "utf-8"
        return html_to_text(resp.text)
    except Exception as e:
        print(f"[WARN] 公告接口请求失败: {url} -> {e}")
        return None


# LLM 提取"项目采购内容"
EXTRACT_PROMPT_TEMPLATE = (
    """
你是一名信息化项目采购要点抽取助手。请从下方给出的网页正文文本中，抽取"项目采购内容"的关键信息（例如软硬件清单、设备/系统名称、数量或范围、主要模块、交付内容等）。

要求：
- 只基于给定文本，不要编造
- 用中文，简洁、结构化表达
- 内容控制在 80~200 字以内，能覆盖主要采购点
- 输出 JSON，格式为：{"prjContent": "..."}

网页正文文本（可能包含无关内容，需甄别）：
"""
)


class LLMExtractor:
    def __init__(self) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL")
        model = os.getenv("OPENAI_MODEL", "Qwen/Qwen2.5-72B-Instruct")
        if not api_key:
            raise RuntimeError("未设置 OPENAI_API_KEY 环境变量")
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def extract(self, text: str, title: Optional[str] = None) -> Optional[str]:
        if not text or len(text) < 30:
            return None
        user_content = EXTRACT_PROMPT_TEMPLATE + (f"\n标题：{title}\n" if title else "") + "\n" + text[:8000]
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant designed to output JSON."},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                top_p=0.1,
            )
            raw = resp.choices[0].message.content
            cleaned = (raw or "").strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("`")
                if cleaned.lower().startswith("json\n"):
                    cleaned = cleaned[5:]
            if "{" in cleaned and "}" in cleaned:
                start = cleaned.find("{")
                end = cleaned.rfind("}") + 1
                cleaned = cleaned[start:end]
            try:
                data = json.loads(cleaned)
            except Exception as je:
                preview = (raw or "")[:500]
                print(f"[DEBUG] LLM 原始输出预览: {preview}")
                print(f"[DEBUG] 清洗后待解析: {cleaned[:500]}")
                raise je
            content = data.get("prjContent")
            if isinstance(content, str) and content.strip():
                return content.strip()
            return None
        except Exception as e:
            print(f"[WARN] LLM 抽取失败: {e}")
            return None


# ★★★ 核心修改：去掉 ACCEPT_TYPES 限制，只要 prjContent 为空就处理 ★★★
def need_process(prj_type: Optional[str], prj_content: Any) -> bool:
    """不再限制项目类型，只要 prjContent 为空就提取"""
    if prj_content is None:
        return True
    if isinstance(prj_content, str) and not prj_content.strip():
        return True
    return False


def process_opening_projects(extractor: LLMExtractor, path: str = "opening_projects.json", rate_sleep: float = 1.0) -> Tuple[int, int]:
    data = read_opening_projects(path)
    if not data or not isinstance(data, dict):
        return (0, 0)
    items = data.get("projects") or []
    total, updated = 0, 0
    for item in items:
        prj_type = item.get("prjType")
        if not need_process(prj_type, item.get("prjContent")):
            continue
        prj_id = item.get("prjId")
        title = item.get("prjName") or item.get("prjNo")
        total += 1
        print(f"[OPENING] 抓取(接口): {title} -> prjId={prj_id}")
        text = fetch_opening_inquire_text(prj_id)
        if not text:
            print("[OPENING] 抓取失败，跳过")
            continue
        print(f"[DEBUG][OPENING] 正文预览: {text[:500]}")
        content = extractor.extract(text, title=title)
        if content:
            item["prjContent"] = content
            updated += 1
            print(f"[OPENING] 已更新 prjContent: {content}")
        else:
            print("[OPENING] 未能从正文抽取到有效内容")
        time.sleep(rate_sleep)
    save_json(data, path)
    return (total, updated)


def process_purchase_bulletins(extractor: LLMExtractor, path: str = "purchase_bulletins.json", rate_sleep: float = 1.0) -> Tuple[int, int]:
    data = read_purchase_bulletins(path)
    if not data or not isinstance(data, list):
        return (0, 0)
    total, updated = 0, 0
    for item in data:
        prj_type = item.get("prjType")
        if not need_process(prj_type, item.get("prjContent")):
            continue
        auto_id = item.get("bulletinId")
        title = item.get("bulletinTitle") or item.get("title") or item.get("prjName")
        total += 1
        print(f"[BULLETIN] 抓取(接口): {title} -> autoID={auto_id}")
        text = fetch_bulletin_text(auto_id)
        if not text:
            print("[BULLETIN] 接口抓取失败，尝试从本地字段 bulletinContent 提取")
            html = item.get("bulletinContent")
            text = html_to_text(html) if isinstance(html, str) else None
            if not text:
                print("[BULLETIN] 无可用正文，跳过")
                continue
        print(f"[DEBUG][BULLETIN] 正文预览: {text[:500]}")
        content = extractor.extract(text, title=title)
        if content:
            item["prjContent"] = content
            updated += 1
            print(f"[BULLETIN] 已更新 prjContent(LLM): {content}")
        else:
            print("[BULLETIN] 未能从正文抽取到有效内容")
        time.sleep(rate_sleep)
    save_json(data, path)
    return (total, updated)


def main():
    try:
        extractor = LLMExtractor()
    except Exception as e:
        print(f"[ERROR] 模型初始化失败：{e}")
        return

    o_total, o_updated = process_opening_projects(extractor)
    print(f"[SUMMARY] 开标项目待处理: {o_total}，已更新: {o_updated}")

    b_total, b_updated = process_purchase_bulletins(extractor)
    print(f"[SUMMARY] 采购公告待处理: {b_total}，已更新: {b_updated}")


if __name__ == "__main__":
    main()
