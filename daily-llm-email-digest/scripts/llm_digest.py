#!/usr/bin/env python3
"""每天收集 LLM 进展，生成中文简报并沿用 vocab.py 的邮件配置。"""

import argparse
import email.utils
import html
import json
import os
import re
import smtplib
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

HOME = Path.home()
MAIL_CONFIG = HOME / ".vocab_config.json"
DIGEST_CONFIG = HOME / ".llm_digest_config.json"
STATE_FILE = HOME / ".llm_digest_state.json"
TZ = ZoneInfo(os.environ.get("LLM_DIGEST_TIMEZONE", "Asia/Singapore"))
UA = "LLMDailyDigest/1.0 (personal research digest)"
FEEDS = [
    ("OpenAI", "https://openai.com/news/rss.xml"),
    ("Google AI", "https://blog.google/technology/ai/rss/"),
    ("Google News", "https://news.google.com/rss/search?" + urllib.parse.urlencode({
        "q": '("large language model" OR LLM OR "AI model" OR "AI agent") when:2d',
        "hl": "en-US", "gl": "US", "ceid": "US:en",
    })),
    ("arXiv", "https://export.arxiv.org/api/query?" + urllib.parse.urlencode({
        "search_query": 'all:"large language model" OR all:"language model"',
        "start": 0, "max_results": 80,
        "sortBy": "submittedDate", "sortOrder": "descending",
    })),
]
KEYWORDS = re.compile(
    r"\b(llm|language model|gpt|claude|gemini|reasoning model|agentic|ai agent|"
    r"multimodal|transformer|inference|fine.tun|context window|retrieval.augmented|rag)\b",
    re.I,
)
GLOSSARY = {
    "agent": ("AI Agent（智能体）", "让模型根据目标调用工具、执行步骤并检查结果的系统。"),
    "reasoning": ("推理模型", "在回答前分配更多计算步骤，适合复杂问题，但通常更慢、更贵。"),
    "multimodal": ("多模态", "同一个模型能处理文字以外的图片、语音或视频。"),
    "inference": ("推理成本", "模型训练完后，每次实际生成答案所需的算力与费用。"),
    "context": ("上下文窗口", "模型一次能读入和参考的信息量。窗口大不等于能准确记住全部内容。"),
    "rag": ("RAG（检索增强生成）", "先检索外部资料，再让模型根据查到的内容回答。"),
    "fine-tun": ("微调", "用特定数据继续训练已有模型，使其更适合某类任务。"),
    "distill": ("蒸馏", "用较强模型的输出训练较小模型，以降低运行成本。"),
}
NEWS_SOURCES = ("Reuters", "The Verge", "TechCrunch", "Ars Technica", "MIT Technology Review",
                "The Decoder", "VentureBeat", "Wired", "Bloomberg", "Financial Times",
                "Nature", "Hugging Face")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as response:
        return response.read(3_000_000)


def clean(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value or ""))).strip()


def parse_date(value):
    if not value:
        return None
    try:
        return email.utils.parsedate_to_datetime(value).astimezone(timezone.utc)
    except (ValueError, TypeError):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return None


def parse_feed(source, raw):
    root = ET.fromstring(raw)
    items = []
    if root.tag.endswith("feed"):
        ns = "{http://www.w3.org/2005/Atom}"
        for entry in root.findall(f"{ns}entry"):
            link = next((x.get("href", "") for x in entry.findall(f"{ns}link") if x.get("rel", "alternate") == "alternate"), "")
            items.append({
                "source": source, "title": clean(entry.findtext(f"{ns}title")),
                "url": link or entry.findtext(f"{ns}id", ""),
                "summary": clean(entry.findtext(f"{ns}summary")),
                "date": parse_date(entry.findtext(f"{ns}published")),
            })
    else:
        for entry in root.findall("./channel/item"):
            items.append({
                "source": source, "title": clean(entry.findtext("title")),
                "url": entry.findtext("link", "").strip(),
                "summary": clean(entry.findtext("description")),
                "date": parse_date(entry.findtext("pubDate")),
            })
    return items


def collect(now, seen):
    cutoff = now - timedelta(hours=48)
    items, errors = [], []
    successes = 0
    for source, url in FEEDS:
        try:
            entries = parse_feed(source, fetch(url))
            successes += 1
            for item in entries:
                if not item["date"] or item["date"] < cutoff or item["date"] > now + timedelta(hours=2):
                    continue
                if item["url"] in seen or not KEYWORDS.search(item["title"] + " " + item["summary"]):
                    continue
                if source == "Google News":
                    outlet = item["title"].rsplit(" - ", 1)[-1]
                    if outlet not in NEWS_SOURCES:
                        continue
                    if not re.search(r"\b(llm|language model|gpt|claude|gemini|reasoning model|AI agent)\b",
                                     item["title"], re.I):
                        continue
                items.append(item)
        except Exception as exc:
            errors.append(f"{source}: {exc}")
    if not successes:
        raise RuntimeError("全部信息源获取失败：" + "; ".join(errors))
    # 按类型分配名额，避免新闻聚合源把论文和官方发布挤掉。
    items.sort(key=lambda x: x["date"], reverse=True)
    unique, titles = [], set()
    limits = {"OpenAI": 2, "Google AI": 2, "arXiv": 4, "Google News": 2}
    counts = {source: 0 for source in limits}
    for item in items:
        key = re.sub(r"[^a-z0-9]+", "", item["title"].lower())[:100]
        if key not in titles and counts[item["source"]] < limits[item["source"]]:
            titles.add(key)
            unique.append(item)
            counts[item["source"]] += 1
    return unique[:8], errors


class ArticleText(HTMLParser):
    """提取网页正文段落，跳过脚本、导航和页脚。"""
    SKIP = {"script", "style", "nav", "footer", "header", "aside", "noscript", "form"}

    def __init__(self):
        super().__init__()
        self.depth, self.in_p, self.parts, self.buf = 0, False, [], []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1
        elif tag in ("p", "li", "h2", "h3") and not self.depth:
            self.in_p, self.buf = True, []

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1
        elif tag in ("p", "li", "h2", "h3") and self.in_p:
            text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
            if len(text) > 40:
                self.parts.append(text)
            self.in_p = False

    def handle_data(self, data):
        if self.in_p and not self.depth:
            self.buf.append(data)


def read_article(item, limit=6000):
    """抓取原文正文；arXiv 优先读 HTML 全文，抓不到时退回 RSS 摘要。"""
    url = item["url"]
    match = re.search(r"arxiv\.org/abs/([\w.]+?)(v\d+)?$", url)
    candidates = [f"https://arxiv.org/html/{match.group(1)}"] if match else []
    if "news.google.com" not in url:
        candidates.append(url)
    for candidate in candidates:
        try:
            parser = ArticleText()
            parser.feed(fetch(candidate).decode("utf-8", "replace"))
            text = " ".join(parser.parts)
            if len(text) > 300:
                return text[:limit], True
        except Exception:
            continue
    return item["summary"][:limit], False


def call_model(prompt, key, model, retries=3):
    body = json.dumps({"model": model, "input": prompt, "max_output_tokens": 4000,
                       "reasoning": {"effort": "low"},
                       "text": {"format": {"type": "json_object"}}}).encode()
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request("https://api.openai.com/v1/responses", data=body,
                                         headers={"Authorization": f"Bearer {key}",
                                                  "Content-Type": "application/json", "User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as response:
                data = json.load(response)
            output = "".join(part.get("text", "") for block in data.get("output", [])
                             for part in block.get("content", []) if part.get("type") == "output_text")
            return json.loads(output)
        except Exception as exc:
            last = exc
            time.sleep(2 * (attempt + 1))
    raise last


def explain_one(i, item, key, model):
    text, full = read_article(item)
    material = {"source": item["source"], "title": item["title"],
                "text_type": "原文正文" if full else "RSS 摘要", "text": text}
    prompt = (
        "你是谨慎的中文 LLM 研究简报编辑。阅读下面的材料，只根据材料写作，不补充未证实的事实。"
        "输出一个 JSON 对象，键为 summary、evidence、concept。summary 是 3 至 5 句通俗中文总结："
        "讲清做了什么、关键方法或发现、为什么值得关注。evidence 是一句话的信息限度或待验证点"
        "（如预印本未经同行评审、仅有公司自述、只读到摘要）。concept 是材料中实际出现、读者可能不熟悉的"
        "一个技术概念（不选产品、公司或模型名称），格式为 {\"name\": 中文名（英文）, \"explanation\": 一两句解释}；没有合适概念则为 null。"
        "不要把论文预印本写成已验证结论，不许编造数字、发布日期或外部链接。\n材料："
        + json.dumps(material, ensure_ascii=False)
    )
    result = call_model(prompt, key, model)
    if not isinstance(result.get("summary"), str) or not re.search(r"[一-鿿]", result["summary"]):
        raise ValueError("AI 返回缺少中文总结")
    concept = result.get("concept")
    if isinstance(concept, dict) and concept.get("name"):
        concept["item_id"] = i
    else:
        concept = None
    return {"id": i, "explanation": result["summary"], "evidence": str(result.get("evidence", ""))}, concept


def ai_explain(items, key, model):
    """逐条阅读原文并生成中文总结；单条失败只回退该条，不影响其他条目。"""
    if not key or not items:
        return None
    fallback = fallback_explain(items)
    updates, concepts = list(fallback["updates"]), []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(explain_one, i, item, key, model): i for i, item in enumerate(items)}
        for future in as_completed(futures):
            i = futures[future]
            try:
                updates[i], concept = future.result()
                if concept:
                    concepts.append(concept)
            except Exception as exc:
                print(f"第 {i} 条 AI 总结失败，使用原文摘要：{exc}", file=sys.stderr)
    concepts.sort(key=lambda c: c["item_id"])
    return {"updates": updates, "concepts": concepts[:3] or fallback["concepts"]}


def fallback_explain(items):
    updates = []
    for i, item in enumerate(items):
        detail = item["summary"][:220].rstrip(" .")
        updates.append({"id": i, "explanation": f"原文摘要：{detail}" if detail else "请阅读原文了解详情。",
                        "evidence": "此条尚未生成中文解读，请以原文为准。"})
    text = " ".join(x["title"] + " " + x["summary"] for x in items).lower()
    concepts = [{"name": name, "explanation": explanation, "item_id": 0}
                for term, (name, explanation) in GLOSSARY.items() if term in text][:3]
    return {"updates": updates, "concepts": concepts}


def render(items, digest, now, errors):
    today = now.astimezone(TZ).strftime("%Y-%m-%d")
    by_id = {row.get("id"): row for row in digest["updates"] if isinstance(row, dict)}
    blocks = []
    for i, item in enumerate(items):
        explanation = by_id.get(i, {})
        title = html.escape(item["title"])
        url = html.escape(item["url"], quote=True)
        when = item["date"].astimezone(TZ).strftime("%m-%d %H:%M")
        blocks.append(f'<article><h3><a href="{url}">{title}</a></h3>'
                      f'<p class="meta">{html.escape(item["source"])} · {when}（新加坡时间）</p>'
                      f'<p>{html.escape(str(explanation.get("explanation", "请阅读原文了解详情。")))}</p>'
                      f'<p class="note">{html.escape(str(explanation.get("evidence", "")))}</p></article>')
    if not blocks:
        blocks.append("<p>过去 48 小时内没有检索到符合条件、且尚未发送的 LLM 进展。</p>")
    concept_blocks = []
    for concept in digest["concepts"][:3]:
        if isinstance(concept, dict):
            concept_blocks.append(f'<li><b>{html.escape(str(concept.get("name", "")))}</b>：'
                                  f'{html.escape(str(concept.get("explanation", "")))}</li>')
    notes = f'<p class="note">部分信息源暂不可用：{html.escape("; ".join(errors))}</p>' if errors else ""
    body = f'''<!doctype html><html lang="zh"><head><meta charset="utf-8"><style>
body{{font:16px/1.65 -apple-system,BlinkMacSystemFont,"Helvetica Neue",Arial,sans-serif;color:#202631;background:#f5f7fa;margin:0;padding:24px}}
main{{max-width:720px;margin:auto;background:white;padding:28px;border-radius:12px}}
h1{{font-size:24px;margin:0 0 4px}}h2{{font-size:19px;margin-top:28px}}h3{{font-size:17px;margin:0 0 6px}}
article{{border-top:1px solid #e5e9ef;padding:18px 0}}a{{color:#165bb8;text-decoration:none}}a:hover{{text-decoration:underline}}
.meta,.note,footer{{color:#667085;font-size:13px}}ul{{padding-left:22px}}li{{margin:8px 0}}
</style></head><body><main><h1>LLM 每日进展</h1><p class="meta">{today} · 最近 48 小时 · {len(items)} 条新进展</p>
<h2>最新动态</h2>{''.join(blocks)}
<h2>概念速懂</h2>{'<ul>'+''.join(concept_blocks)+'</ul>' if concept_blocks else '<p>今天没有适合单独讲解的新概念。</p>'}
{notes}<footer>来源：官方新闻、Google News 与 arXiv。论文为预印本；链接指向原文。由 llm_digest.py 自动发送。</footer>
</main></body></html>'''
    plain = "LLM 每日进展 " + today + "\n\n" + "\n\n".join(
        f'{x["title"]} ({x["source"]})\n{x["url"]}\n{by_id.get(i, {}).get("explanation", "")}'
        for i, x in enumerate(items))
    return plain, body


def save_state(seen):
    temp = STATE_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps({"seen": sorted(seen)[-1000:]}, ensure_ascii=False), encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(STATE_FILE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["preview", "send"])
    parser.add_argument("--model", default="gpt-5-mini")
    args = parser.parse_args()
    config = json.loads(MAIL_CONFIG.read_text(encoding="utf-8")) if MAIL_CONFIG.exists() else {}
    if args.command == "send" and (not config.get("email") or not config.get("password")):
        parser.error("缺少 vocab 邮件配置，请先运行 python vocab.py setup")
    now = datetime.now(timezone.utc)
    seen = set(json.loads(STATE_FILE.read_text(encoding="utf-8")).get("seen", [])) if STATE_FILE.exists() else set()
    items, errors = collect(now, seen)
    digest_config = json.loads(DIGEST_CONFIG.read_text(encoding="utf-8")) if DIGEST_CONFIG.exists() else {}
    key = os.environ.get("OPENAI_API_KEY") or digest_config.get("openai_key")
    try:
        digest = ai_explain(items, key, args.model) or fallback_explain(items)
    except Exception as exc:
        print(f"AI 解读失败，使用原文摘要：{exc}", file=sys.stderr)
        digest = fallback_explain(items)
    plain, body = render(items, digest, now, errors)
    if args.command == "preview":
        print(plain)
        print(f"\n信息源错误：{'; '.join(errors) if errors else '无'}")
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"LLM 每日进展 {now.astimezone(TZ):%Y-%m-%d}（{len(items)} 条）"
    msg["From"] = config["email"]
    msg["To"] = config.get("to_email") or config["email"]
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(body, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(config["email"], config["password"])
        smtp.send_message(msg)
    seen.update(x["url"] for x in items)
    save_state(seen)
    print(f"已发送 {len(items)} 条进展到 {msg['To']}")


if __name__ == "__main__":
    main()
