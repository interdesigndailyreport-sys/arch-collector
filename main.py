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

# 日本語 ＋ 英語の建築・AIキーワード
KEYWORDS = [
    # 建築・空間デザイン系
    "建築", "マンション", "デザイン", "設計", "リノベーション", "ファサード", "住宅", "インテリア", "構造", "住戸", "空間", "施設", "美術館", "店舗",
    "architecture", "house", "building", "design", "residence", "project", "interior", "renovation", "structure", "facade", "museum", "office",
    # AI・テクノロジー系
    "ai", "人工知能", "生成ai", "画像生成", "動画生成", "llm", "chatgpt", "gemini", "claude", "copilot", "プロンプト", "自動化", "3d"
]

TARGET_FEEDS = [
    # --- 建築・デザイン専門メディア ---
    {"name": "architecturephoto", "url": "https://architecturephoto.net/feed/", "bypass_filter": True},
    {"name": "ArchDaily", "url": "https://www.archdaily.com/rss", "bypass_filter": True},
    {"name": "AXIS Web Magazine", "url": "https://www.axismag.jp/feed/", "bypass_filter": False},
    {
        "name": "tecture mag (Google経由)",
        "url": "https://news.google.com/rss/search?q=site:mag.tecture.jp&hl=ja&gl=JP&ceid=JP:ja",
        "bypass_filter": True
    },
    {
        "name": "新建築 (Google経由)",
        "url": "https://news.google.com/rss/search?q=site:shinkenchiku.online&hl=ja&gl=JP&ceid=JP:ja",
        "bypass_filter": True
    },
    {
        "name": "大手分譲マンション新築ニュース",
        "url": "https://news.google.com/rss/search?q=%E5%88%86%E8%AD%B2%E3%83%9E%E3%83%B3%E3%82%B7%E3%83%A7%E3%83%B3+%E6%96%B0%E7%AF%89+%E3%83%87%E3%82%B6%E3%82%A4%E3%83%B3&hl=ja&gl=JP&ceid=JP:ja",
        "bypass_filter": False
    },
    # --- AI・生成AI最新情報メディア ---
    {"name": "ITmedia AI+", "url": "https://rss.itmedia.co.jp/rss/2.0/aiplus.xml", "bypass_filter": True},
    {"name": "Ledge.ai (AI専門)", "url": "https://ledge.ai/feed/", "bypass_filter": True},
    {
        "name": "生成AI最新トレンド",
        "url": "https://news.google.com/rss/search?q=%E7%94%9F%E6%88%90AI+%E6%9C%80%E6%96%B0%E6%8A%80%E8%A1%93&hl=ja&gl=JP&ceid=JP:ja",
        "bypass_filter": False
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
    """タイトルまたは概要に対象キーワードが含まれるか判定"""
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
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent?key={GEMINI_API_KEY}"
    
    prompt = f"""
あなたは建築・空間デザインおよび最新AI技術トレンドの専門アナリストです。
以下のWebニュース記事情報を分析し、JSONフォーマットのみで結果を出力してください。

【記事情報】
タイトル: {title}
概要: {description}
URL: {link}

【判定・処理条件】
1. この記事が以下のいずれかに関連するか判定してください：
   - 「建築・インテリア・住宅・都市空間のデザインや開発」
   - 「生成AI、画像/動画生成、LLM、業務効率化AI、クリエイティブ向け最新ツール」
   ※単なる求人広告、投資金融のみのニュース、関係のない一般記事は除外(is_relevant: false)としてください。
2. 関連する場合(is_relevant: true)：
   - 建築記事の場合：デザインの意匠的特徴（素材・空間構成・構造等）を2〜3つの箇条書き形式で抽出
   - AI記事の場合：主な機能・技術的特徴・活用メリットを2〜3つの箇条書き形式で抽出
3. 記事の概要を100〜150字程度で簡潔に要約してください。

【出力形式 (JSONのみ・Markdown装飾不要)】
{{
  "is_relevant": true または false,
  "design_features": "・特徴1\\n・特徴2",
  "summary": "要約テキスト"
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
    print("Starting Multi-Domain Collector (Architecture & AI)...", flush=True)
    
    for feed_info in TARGET_FEEDS:
        media_name = feed_info["name"]
        bypass = feed_info.get("bypass_filter", False)
        entries = fetch_rss_entries(feed_info["url"])
        print(f"\n[{media_name}] {len(entries)} entries fetched", flush=True)

        for entry in entries[:3]:
            title = entry.get("title", "")
            description = entry.get("summary", "") or entry.get("description", "")
            link = entry.get("link", "")

            if not bypass and not is_pre_filtered(title, description):
                print(f" Skipped by Keyword Filter: {title}", flush=True)
                continue

            print(f" Analyzing: {title}", flush=True)
            image_url = get_og_image_url(link)
            analysis = analyze_with_gemini(title, description, link)
            
            if analysis.get("is_relevant"):
                save_to_notion(title, link, analysis.get("summary", ""), analysis.get("design_features", ""), media_name, image_url)
            else:
                print(f" Skipped by Gemini Judgment: {title}", flush=True)

            time.sleep(2)

if __name__ == "__main__":
    main()
