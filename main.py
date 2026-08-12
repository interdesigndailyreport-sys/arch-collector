import os
import json
import time
import re
from datetime import datetime, timezone, timedelta
import feedparser
import requests

# 環境変数の読み込み
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
NOTION_API_KEY = os.environ.get("NOTION_API_KEY")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")

# 事前判定用キーワード（この言葉が含まれる記事のみGeminiへ送信してAPI消費を削減）
KEYWORDS = ["建築", "マンション", "デザイン", "設計", "リノベーション", "ファサード", "住宅", "インテリア", "構造", "住戸"]

TARGET_FEEDS = [
    {"name": "architecturephoto", "url": "https://architecturephoto.net/feed/"},
    {"name": "ArchDaily", "url": "https://www.archdaily.com/rss"},
    {"name": "AXIS Web Magazine", "url": "https://www.axismag.jp/feed"},
    {
        "name": "tecture mag (Google経由)",
        "url": "https://news.google.com/rss/search?q=site:mag.tecture.jp&hl=ja&gl=JP&ceid=JP:ja"
    },
    {
        "name": "新建築 (Google経由)",
        "url": "https://news.google.com/rss/search?q=site:shinkenchiku.online&hl=ja&gl=JP&ceid=JP:ja"
    },
    {
        "name": "大手分譲マンション新築ニュース",
        "url": "https://news.google.com/rss/search?q=%E5%88%86%E8%AD%B2%E3%83%9E%E3%83%B3%E3%82%B7%E3%83%A7%E3%83%B3+%E6%96%B0%E7%AF%89+%E3%83%87%E3%82%B6%E3%82%A4%E3%83%B3&hl=ja&gl=JP&ceid=JP:ja"
    }
]

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
}

def fetch_rss_entries(url):
    try:
        response = requests.get(url, headers=HTTP_HEADERS, timeout=10)
        if response.status_code == 200:
            feed = feedparser.parse(response.content)
            return feed.entries
    except Exception:
        pass
    try:
        return feedparser.parse(url).entries
    except Exception:
        return []

def is_pre_filtered(title, description):
    """Python側で一次フィルタリング（API消費を削減）"""
    text = f"{title} {description}".lower()
    return any(kw.lower() in text for kw in KEYWORDS)

def get_og_image_url(article_url):
    if not article_url:
        return None
    try:
        res = requests.get(article_url, headers=HTTP_HEADERS, timeout=5, allow_redirects=True)
        if res.status_code == 200:
            match = re.search(r'<meta[^>]+(?:property|name)=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', res.text, re.IGNORECASE)
            if match and match.group(1).startswith("http"):
                return match.group(1)
    except Exception:
        pass
    return None

def analyze_with_gemini(title, description, link):
    # 無料枠制限が1日500回（RPD 500）と非常に広い gemini-3.5-flash-lite モデルを使用
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent?key={GEMINI_API_KEY}"
    
    prompt = f"""
あなたは建築専門アナリストです。以下の記事を分析しJSONのみで回答してください。
タイトル: {title}
概要: {description}

【条件】
1. 求人情報や不適切な記事は is_relevant: false にしてください。
2. 建築・デザイン・住宅に関連する場合は is_relevant: true とし、意匠的特徴(design_features)と要約(summary)を抽出してください。

【出力形式 (JSON)】
{{
  "is_relevant": true,
  "design_features": "・特徴1\\n・特徴2",
  "summary": "100字程度の要約"
}}
"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"}
    }

    try:
        response = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=15)
        if response.status_code == 200:
            res_json = response.json()
            raw_text = res_json["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(raw_text)
        elif response.status_code == 429:
            print(" -> Gemini APIの上限に達しています。時間を置いて実行してください。", flush=True)
    except Exception as e:
        print(f" -> Gemini Error: {e}", flush=True)

    return {"is_relevant": False}

def save_to_notion(title, url, summary, features, media_name, image_url=None):
    notion_url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            "Title": {"title": [{"text": {"content": title[:200]}}]},
            "URL": {"url": url},
            "Media": {"multi_select": [{"name": media_name}]},
            "Design Features": {"rich_text": [{"text": {"content": features[:2000]}}]},
            "Summary": {"rich_text": [{"text": {"content": summary[:2000]}}]},
            "Date": {"date": {"start": datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")}}
        }
    }

    if image_url:
        payload["cover"] = {"type": "external", "external": {"url": image_url}}

    res = requests.post(notion_url, headers=headers, json=payload, timeout=15)
    if res.status_code == 200:
        print(f" Successfully Saved to Notion: {title}", flush=True)

def main():
    print("Starting Architecture Collector...", flush=True)
    
    for feed_info in TARGET_FEEDS:
        media_name = feed_info["name"]
        entries = fetch_rss_entries(feed_info["url"])
        print(f"\n[{media_name}] {len(entries)} entries fetched", flush=True)

        for entry in entries[:3]:
            title = entry.get("title", "")
            description = entry.get("summary", "") or entry.get("description", "")
            link = entry.get("link", "")

            # 1. 事前キーワードチェック（API消費を大幅削減）
            if not is_pre_filtered(title, description):
                print(f" Skipped by Keyword Filter: {title}", flush=True)
                continue

            print(f" Analyzing: {title}", flush=True)
            image_url = get_og_image_url(link)
            analysis = analyze_with_gemini(title, description, link)
            
            if analysis.get("is_relevant"):
                save_to_notion(title, link, analysis.get("summary", ""), analysis.get("design_features", ""), media_name, image_url)

            time.sleep(2)

if __name__ == "__main__":
    main()
