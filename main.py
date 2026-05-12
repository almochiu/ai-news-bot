import os
import json
import smtplib
import time
import urllib.request
from datetime import datetime
import pytz
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import anthropic

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

TAIPEI_TZ = pytz.timezone("Asia/Taipei")


def fetch_raw_news():
    cutoff = int(time.time()) - (48 * 3600)  # 48 小時內
    urls = [
        f"https://hn.algolia.com/api/v1/search?query=OpenAI+Google+DeepMind+Meta+Microsoft+NVIDIA+Anthropic&tags=story&hitsPerPage=30&numericFilters=created_at_i%3E{cutoff}",
        f"https://hn.algolia.com/api/v1/search?query=xAI+Apple+AI+Amazon+AI+LLM&tags=story&hitsPerPage=20&numericFilters=created_at_i%3E{cutoff}",
        f"https://hn.algolia.com/api/v1/search?query=artificial+intelligence+machine+learning&tags=story&hitsPerPage=20&numericFilters=created_at_i%3E{cutoff}",
    ]
    all_hits = []
    for url in urls:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            all_hits.extend(data.get("hits", []))

    seen = set()
    unique = []
    for hit in sorted(all_hits, key=lambda x: x.get("points", 0), reverse=True):
        title = hit.get("title", "")
        if title and title not in seen:
            seen.add(title)
            unique.append(hit)

    return unique[:30]


def format_with_claude(hits):
    today = datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d")

    news_list = []
    for i, hit in enumerate(hits):
        title = hit.get("title", "")
        url = hit.get("url", "")
        points = hit.get("points", 0)
        created = (hit.get("created_at") or "")[:10]
        news_list.append(f"{i+1}. {title} ({points} pts, {created})\n   {url}")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2500,
        messages=[
            {
                "role": "user",
                "content": f"""以下是今天從 Hacker News 收集的 AI 科技新聞。請從中選出最重要的 10 則，以繁體中文整理摘要，格式如下：

🤖 AI 科技產業動態 - {today}

1. [新聞標題（繁體中文）]
   ▸ [重點摘要 2-3 句，繁體中文]
   📰 Hacker News | [日期]

（依此格式列出全部 10 則，不要其他說明文字）

優先選取與 OpenAI、Google DeepMind、Anthropic、Microsoft、Meta AI、Apple、NVIDIA、xAI 等 AI 科技巨頭相關的新聞。
如果沒有足夠的科技巨頭新聞，請從列表中選取最相關的 AI 技術動態補足 10 則。
無論新聞品質如何，都必須輸出完整的 10 則，不可以拒絕或說明無法完成。

新聞列表：
{chr(10).join(news_list)}""",
            }
        ],
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

    hits = fetch_raw_news()
    print(f"Fetched {len(hits)} items")

    formatted = format_with_claude(hits)
    print("Formatted with Claude")

    today = now.strftime("%Y-%m-%d")
    send_telegram(formatted)
    send_gmail(f"🤖 AI 科技產業動態 - {today}", formatted)

    print(f"[{now}] Done.")
