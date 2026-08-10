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

TARGET_FEEDS = [
    {"name": "architecturephoto", "url": "https://architecturephoto.net/feed/"},
    {"name": "tecture mag", "url": "https://mag.tecture.jp/feed/"},
    {"name": "新建築.online", "url": "https://shinkenchiku.online/feed/"},
    {"name": "ArchDaily", "url": "https://www.archdaily.com/rss"},
    {"name": "AXIS Web Magazine", "url": "https://www.axismag.jp/feed"},
    {
        "name": "大手分譲マンション新築ニュース",
        "url": "https://news.google.com/rss/search?q=%E5%88%86%E8%AD%B2%E3%83%9E%E3%83%B3%E3%82%B7%E3%83%A7%E3%83%B3+%E6%96%B0%E7%AF%89+%E3%83%87%E3%82%B6%E3%82%A4%E3%83%B3&hl=ja&gl=JP&ceid=JP:ja"
    }
]

# 完全なブラウザ通信を装うヘッダー
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache"
}

def fetch_rss_entries(url):
    """セキュリティ制限を回避しながらRSSを取得する"""
    try:
        response = requests.get(url, headers=HTTP_HEADERS, timeout=15)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
        if feed.entries:
            return feed.entries
    except Exception as e:
        print(f"requests経由の取得失敗 ({url}): {e} -> feedparserで直接再試行します")

    # リトライ：feedparserの直接通信機能を利用
    try:
        feed = feedparser.parse(url)
        return feed.entries
    except Exception as e:
        print(f"RSS Fetch Direct Error ({url}): {e}")
        return []

def get_og_image_url(article_url):
    """記事のWebページにアクセスしてOGP(アイキャッチ)画像URLを直接抽出する"""
    if not article_url:
        return None
    try:
        res = requests.get(article_url, headers=HTTP_HEADERS, timeout=10, allow_redirects=True)
        if res.status_code == 200:
            html = res.text
            # <meta property="og:image" content="..."> または <meta name="og:image" ...> を正規表現で探索
            match = re.search(r'<meta[^>]+(?:property|name)=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
            if not match:
                match = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']og:image["\']', html, re.IGNORECASE)
            
            if match:
                img_url = match.group(1)
                # Google等のプロキシ画像やアイコン類を除外
                if img_url.startswith("http") and not any(x in img_url.lower() for x in ["icon", "avatar", "logo-square"]):
                    return img_url
    except Exception as e:
        print(f" -> OGP Image Extraction Error ({article_url}): {e}")
    return None

def analyze_with_gemini(title, description, link):
    """Gemini APIによる判定と構造化"""
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
        if response.status_code == 429:
            print(" -> Gemini API レート制限検知 (429)。10秒待機します...")
            time.sleep(10)
            return {"is_relevant": False}
            
        response.raise_for_status()
        res_json = response.json()
        raw_text = res_json["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(raw_text)
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return {"is_relevant": False}

def save_to_notion(title, url, summary, features, media_name, image_url=None):
    """Notion APIへのデータ保存"""
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
            "Title": {"title": [{"text": {"content": title[:200]}}]},
            "URL": {"url": url},
            "Media": {"multi_select": [{"name": media_name}]},
            "Design Features": {"rich_text": [{"text": {"content": features[:2000]}}]},
            "Summary": {"rich_text": [{"text": {"content": summary[:2000]}}]},
            "Date": {"date": {"start": date_str}}
        }
    }

    # ページカバー画像（ギャラリー表示用）を設定
    if image_url:
        payload["cover"] = {
            "type": "external",
            "external": {"url": image_url}
        }

    res = requests.post(notion_url, headers=headers, json=payload, timeout=30)
    if res.status_code == 200:
        print(f"Successfully saved to Notion (Cover: {'Yes' if image_url else 'No'}): {title}")
    else:
        print(f"Notion API Error ({res.status_code}): {res.text}")

def main():
    print("Starting Architecture RSS Scraping with OGP Extraction...")
    
    for feed_info in TARGET_FEEDS:
        media_name = feed_info["name"]
        rss_url = feed_info["url"]
        
        entries = fetch_rss_entries(rss_url)
        print(f"\n[{media_name}] Fetched {len(entries)} entries")

        # 各メディア最新3件を読み込み
        for entry in entries[:3]:
            title = entry.get("title", "")
            description = entry.get("summary", "") or entry.get("description", "")
            link = entry.get("link", "")

            print(f"\nAnalyzing: {title}")
            
            # 1. 記事Webページから高画質なOGP(カバー)画像を抽出
            image_url = get_og_image_url(link)
            if image_url:
                print(f" -> Found OGP Image: {image_url}")

            # 2. Gemini APIで解析
            analysis = analyze_with_gemini(title, description, link)
            
            # 3. Notionへ保存
            if analysis.get("is_relevant"):
                print(" -> Relevant architecture info found!")
                save_to_notion(
                    title=title,
                    url=link,
                    summary=analysis.get("summary", ""),
                    features=analysis.get("design_features", ""),
                    media_name=media_name,
                    image_url=image_url
                )
            else:
                print(" -> Skipped (Not relevant)")

            time.sleep(4)

if __name__ == "__main__":
    main()
