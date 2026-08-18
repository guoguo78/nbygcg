import requests
import json
import os
import argparse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def fetch_opening_projects(date_range):
    """抓取开标项目，只保留近三日开标的"""
    url = "https://ygcg.nbcqjy.org/api/Portal/GetOpenList"

    payload = json.dumps({"pageIndex": 1, "pageSize": 200})
    headers = {
        'Content-Type': 'application/json;charset-utf-8'
    }

    response = requests.post(url, headers=headers, data=payload)
    response_data = response.json()

    # 北京时区
    beijing_tz = ZoneInfo("Asia/Shanghai")

    # 近三日的日期集合（用于快速判断）
    date_set = set(date_range)

    # 提取符合条件的项目
    filtered_projects = []
    for project in response_data["body"]["data"]["projectList"]:
        kb_raw = project["kbDate"]
        dt = datetime.fromisoformat(kb_raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=beijing_tz)
        else:
            dt = dt.astimezone(beijing_tz)
        kb_date = dt.date().strftime("%Y-%m-%d")

        # ✅ 核心改动：只保留近三日开标的项目
        if kb_date in date_set:
            filtered_projects.append({
                "kbDate": dt.strftime("%Y-%m-%d"),
                "prjName": project["prjName"],
                "bulletinId": project["bulletinId"],
                "prjId": project.get("prjId"),
                "prjNo": project.get("prjNo"),
                "prjUrl": (
                    f"https://ygcg.nbcqjy.org/detail?type=1&prjId={project.get('prjId')}" if project.get("prjId")
                    else f"https://ygcg.nbcqjy.org/detail?bulletinId={project.get('bulletinId')}"
                ),
                "prjType": "其他项目",
                "prjContent": None
            })

    # 按开标日期升序排序
    filtered_projects.sort(key=lambda x: x["kbDate"])

    return {
        "date_range": date_range,
        "projects": filtered_projects
    }


def save_to_json(data, savepath="opening_projects.json"):
    save_dir = os.path.dirname(savepath)
    if save_dir and not os.path.exists(save_dir):
        os.makedirs(save_dir)
    with open(savepath, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=4)


def main():
    # 解析传入的日期参数（从 GitHub Actions 的 --date 参数来）
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', type=str, default=datetime.now().strftime('%Y-%m-%d'),
                        help='The current date in YYYY-MM-DD format')
    args = parser.parse_args()

    try:
        base_date = datetime.strptime(args.date, '%Y-%m-%d')
    except ValueError:
        base_date = datetime.now()

    # 计算近三日
    date_range = []
    for i in range(3):
        day = base_date - timedelta(days=i)
        date_range.append(day.strftime('%Y-%m-%d'))

    print(f"🔍 近三日日期范围: {', '.join(date_range)}")

    # ✅ 把 date_range 传给抓取函数
    data = fetch_opening_projects(date_range)

    # 保存
    save_to_json(data)
    print(f"✅ 数据已保存到 opening_projects.json")
    print(f"📊 近三日开标项目共 {len(data['projects'])} 个")
    for p in data['projects']:
        print(f"  - [{p['kbDate']}] {p['prjName']}")


if __name__ == "__main__":
    main()
