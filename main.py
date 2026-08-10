import os
import json
import time
from datetime import datetime, timezone, timedelta
import feedparser
import requests

# 環境変数の読み込み
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
NOTION_API_KEY = os.environ.get("NOTION_API_KEY")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")

# 監視対象のRSSリスト（複数のメディアを登録可能）
TARGET_FEEDS = [
    {
        "name": "PR TIMES (不動産)",
        "url": "https://prtimes.jp/main/html/rd/rss/sub_kind/3.xml"
    },
    {
        "name": "JDN (デザイン・建築)",
        "url": "https://www.japandesign.ne.jp/feed/"
    }
]

def fetch_rss_entries(url):
    """User-Agentを設定してアクセス拒否を回避しRSSを取得する"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
        return feed.entries
    except Exception as e:
        print(f"RSS Fetch Error ({url}): {e}")
        return []

def analyze_with_gemini(title, description, link):
    """Gemini APIを使って建築・デザイン事例としての関連性を判定し要約・特徴抽出"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    prompt = f"""
あなたは建築・インテリア・住宅デザインの専門アナリストです。
以下のWebニュース記事情報を分析し、JSONフォーマットのみで結果を出力してください。

【記事情報】
タイトル: {title}
概要: {description}
URL: {link}

【処理条件】
1. この記事が「建築デザイン」「新築・リノベーションマンション」「住宅の空間設計」「意匠・ファサード・建築トレンド」に関連するか判定してください。関係のない一般的ニュースは除外対象(is_relevant: false)とします。
2. 関連する(is_relevant: true)場合、建築デザインの意匠的特徴（素材、構造、空間構成、スタイル等）を2〜3つの箇条書き形式で抽出してください。
3. 記事の概要を150字程度で簡潔に要約してください。

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
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        res_json = response.json()
        raw_text = res_json["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(raw_text)
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return {"is_relevant": False}

def save_to_notion(title, url, summary, features, media_name):
    """Notion APIを使用してデータベースへ登録"""
    notion_url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    date_str = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")

    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            "Title": {
                "title": [{"text": {"content": title[:200]}}]
            },
            "URL": {
                "url": url
            },
            "Media": {
                "select": {"name": media_name}
            },
            "Design Features": {
                "rich_text": [{"text": {"content": features[:2000]}}]
            },
            "Summary": {
                "rich_text": [{"text": {"content": summary[:2000]}}]
            },
            "Date": {
                "date": {"start": date_str}
            }
        }
    }

    res = requests.post(notion_url, headers=headers, json=payload, timeout=30)
    if res.status_code == 200:
        print(f"Successfully saved to Notion: {title}")
    else:
        print(f"Notion API Error ({res.status_code}): {res.text}")

def main():
    print("Starting Architecture RSS Scraping...")
    
    for feed_info in TARGET_FEEDS:
        media_name = feed_info["name"]
        rss_url = feed_info["url"]
        
        entries = fetch_rss_entries(rss_url)
        print(f"[{media_name}] Fetched {len(entries)} entries")

        for entry in entries[:5]:
            title = entry.get("title", "")
            description = entry.get("summary", "") or entry.get("description", "")
            link = entry.get("link", "")

            print(f"\nAnalyzing: {title}")
            analysis = analyze_with_gemini(title, description, link)
            
            if analysis.get("is_relevant"):
                print(" -> Relevant architecture info found!")
                save_to_notion(
                    title=title,
                    url=link,
                    summary=analysis.get("summary", ""),
                    features=analysis.get("design_features", ""),
                    media_name=media_name
                )
            else:
                print(" -> Skipped (Not relevant)")

            time.sleep(2)

if __name__ == "__main__":
    main()
