import os
import json
import smtplib
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import pytz
import anthropic

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

TAIPEI_TZ = pytz.timezone("Asia/Taipei")
UTC = pytz.utc

RSS_FEEDS = [
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ("VentureBeat AI", "https://venturebeat.com/category/ai/feed/"),
    ("Wired AI", "https://www.wired.com/feed/category/artificial-intelligence/latest/rss"),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/technology-lab"),
    ("MIT Tech Review AI", "https://www.technologyreview.com/feed/"),
]


def parse_date(date_str):
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str.strip()).astimezone(UTC)
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(date_str.strip().replace("Z", "+00:00"))
        return dt.astimezone(UTC)
    except Exception:
        return None


def fetch_rss_news():
    cutoff = datetime.now(UTC) - timedelta(hours=48)
    all_articles = []

    for source_name, feed_url in RSS_FEEDS:
        try:
            req = urllib.request.Request(
                feed_url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                content = resp.read()

            root = ET.fromstring(content)
            ATOM = "http://www.w3.org/2005/Atom"

            items = root.findall(".//item") or root.findall(f".//{{{ATOM}}}entry")

            count = 0
            for item in items:
                # Title
                title = (
                    item.findtext("title")
                    or item.findtext(f"{{{ATOM}}}title")
                    or ""
                ).strip()
                if not title:
                    continue

                # Link
                link_el = item.find("link")
                if link_el is not None:
                    link = (link_el.text or link_el.get("href", "")).strip()
                else:
                    link_el = item.find(f"{{{ATOM}}}link")
                    link = (link_el.get("href", "") if link_el is not None else "").strip()

                # Date
                pub_date = (
                    item.findtext("pubDate")
                    or item.findtext(f"{{{ATOM}}}published")
                    or item.findtext(f"{{{ATOM}}}updated")
                    or ""
                )
                pub_dt = parse_date(pub_date)

                if pub_dt and pub_dt >= cutoff:
                    all_articles.append({
                        "title": title,
                        "url": link,
                        "source": source_name,
                        "date": pub_dt.strftime("%Y-%m-%d"),
                        "timestamp": pub_dt.timestamp(),
                    })
                    count += 1

            print(f"{source_name}: {count} articles in past 48h")
        except Exception as e:
            print(f"Error fetching {source_name}: {e}")

    # Sort by newest first and deduplicate
    all_articles.sort(key=lambda x: x["timestamp"], reverse=True)
    seen, unique = set(), []
    for a in all_articles:
        key = a["title"][:60].lower()
        if key not in seen:
            seen.add(key)
            unique.append(a)

    print(f"Total unique articles: {len(unique)}")
    return unique[:35]


def format_with_claude(articles):
    today = datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d")

    if not articles:
        return f"🤖 AI 科技產業動態 - {today}\n\n今日暫無最新動態，請明日再查看。"

    news_list = "\n".join(
        f"{i+1}. [{a['source']}] {a['title']} ({a['date']})\n   {a['url']}"
        for i, a in enumerate(articles)
    )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2500,
        messages=[{
            "role": "user",
            "content": f"""以下是過去 48 小時內從各大科技媒體收集的 AI 相關新聞。請從中選出最重要的 10 則，以繁體中文整理摘要。

輸出格式（嚴格按此格式，不要任何前言或後記）：

🤖 AI 科技產業動態 - {today}

1. [新聞標題（繁體中文）]
   ▸ [重點摘要 2-3 句，繁體中文]
   📰 [來源媒體] | [日期]
   🔗 [該則新聞的完整 URL]

（依此格式列出全部 10 則）

選取原則：優先選 OpenAI、Google、Anthropic、Microsoft、Meta、Apple、NVIDIA、xAI 等科技巨頭相關動態；若不足 10 則，從其他 AI 技術新聞補足。必須輸出 10 則，不可少於 10 則。

新聞列表：
{news_list}""",
        }],
    )
    return message.content[0].text


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    lines = text.split("\n")
    chunks, current, current_len = [], [], 0
    for line in lines:
        if current_len + len(line) + 1 > 4000:
            chunks.append("\n".join(current))
            current, current_len = [line], len(line)
        else:
            current.append(line)
            current_len += len(line) + 1
    if current:
        chunks.append("\n".join(current))

    for chunk in chunks:
        if not chunk.strip():
            continue
        payload = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": chunk}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            print(f"Telegram: {result.get('ok')}")


def send_gmail(subject, body):
    msg = MIMEMultipart()
    msg["From"] = GMAIL_USER
    msg["To"] = GMAIL_USER
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.send_message(msg)
    print("Gmail: OK")


if __name__ == "__main__":
    now = datetime.now(TAIPEI_TZ)
    print(f"[{now}] Starting AI news digest...")

    articles = fetch_rss_news()
    formatted = format_with_claude(articles)
    print("Formatted with Claude")

    today = now.strftime("%Y-%m-%d")
    send_telegram(formatted)
    send_gmail(f"🤖 AI 科技產業動態 - {today}", formatted)

    print(f"[{now}] Done.")
