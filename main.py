import os
import json
from datetime import datetime, timedelta
import tweepy
from openai import OpenAI
import markdown2
from weasyprint import HTML
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import pandas as pd

# ================== CONFIG FROM GITHUB SECRETS ==================
BEARER_TOKEN = os.getenv("X_BEARER_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_RECIPIENTS = os.getenv("EMAIL_RECIPIENTS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

client = OpenAI(api_key=OPENAI_API_KEY)

# Reputable US brokers & keywords (same as before)
FIRMS = ["J.P. Morgan", "JPMorgan", "Goldman Sachs", "Morgan Stanley", "Bank of America", "BofA", "Citi", "Citigroup", "Wells Fargo", "UBS", "Jefferies", "Evercore", "Lazard", "RBC Capital", "Barclays", "Credit Suisse", "Wedbush", "Oppenheimer", "Stifel"]
KEYWORDS = ["research note", "equity research", "upgrade", "downgrade", "price target", "PT:", "initiate", "reiterate"]

def build_query():
    firm_or = " OR ".join([f'"{f}"' for f in FIRMS])
    kw_or = " OR ".join([f'"{k}"' for k in KEYWORDS])
    return f'({kw_or}) ({firm_or}) lang:en -is:retweet -is:reply filter:safe'

# Capture latest 24h research notes
def capture_research():
    print("🔍 Capturing research notes from X...")
    client_tweepy = tweepy.Client(bearer_token=BEARER_TOKEN, wait_on_rate_limit=True)
    query = build_query()
    start_time = (datetime.utcnow() - timedelta(days=1)).isoformat() + "Z"

    response = client_tweepy.search_recent_tweets(
        query=query,
        start_time=start_time,
        max_results=100,
        tweet_fields=["created_at", "author_id", "entities", "attachments", "public_metrics"],
        expansions=["author_id"],
        user_fields=["username", "name"]
    )

    if not response.data:
        print("No new notes today.")
        return []

    users = {u.id: u for u in response.includes.get("users", [])}
    notes = []
    for tweet in response.data:
        author = users.get(tweet.author_id)
        links = [url["expanded_url"] for url in tweet.entities.get("urls", [])] if tweet.entities else []
        note = {
            "tweet_id": str(tweet.id),
            "created_at": tweet.created_at.isoformat(),
            "author_username": author.username if author else "N/A",
            "author_name": author.name if author else "N/A",
            "text": tweet.text,
            "url": f"https://x.com/{author.username}/status/{tweet.id}" if author else "",
            "links": links,
            "firm_mentions": [f for f in FIRMS if f.lower() in tweet.text.lower()]
        }
        notes.append(note)
    return notes

# Generate LLM summary
def generate_summary(notes, date_str):
    if not notes:
        return "# Daily Equity Research Summary – " + date_str + "\n\nNo research notes found today."

    system_prompt = "You are a senior equity research strategist at Quantmatix..."
    user_message = f"""INPUT DATA (JSON):
```json
{json.dumps(notes, indent=2)}
