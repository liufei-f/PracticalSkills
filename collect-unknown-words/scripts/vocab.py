#!/usr/bin/env python3
"""
vocab.py — 单词记录 & 每日邮件复习

用法:
  python vocab.py add <单词> [-n "备注"]   添加单词
  python vocab.py list                     查看单词列表
  python vocab.py delete <单词>            删除单词
  python vocab.py send                     立即发送复习邮件
  python vocab.py setup                    配置邮件和 API
"""

import json
import sys
import os
import smtplib
import argparse
import getpass
import time
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

VOCAB_FILE = Path.home() / ".vocab_words.json"
CONFIG_FILE = Path.home() / ".vocab_config.json"


# ── 数据读写 ───────────────────────────────────────────────────────

def load_words():
    if VOCAB_FILE.exists():
        with open(VOCAB_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_words(words):
    with open(VOCAB_FILE, "w", encoding="utf-8") as f:
        json.dump(words, f, ensure_ascii=False, indent=2)


def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    os.chmod(CONFIG_FILE, 0o600)


# ── CLI 命令 ───────────────────────────────────────────────────────

def cmd_add(args):
    word = " ".join(args.word).strip()
    note = args.note or ""
    words = load_words()
    if any(w["word"].lower() == word.lower() for w in words):
        print(f"「{word}」已在列表中。")
        return
    words.append({
        "word": word,
        "note": note,
        "added": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    save_words(words)
    suffix = f"  [{note}]" if note else ""
    print(f"✓ 已添加：{word}{suffix}")


def cmd_list(args):
    words = load_words()
    if not words:
        print("列表为空。试试：python vocab.py add hello")
        return
    print(f"\n单词列表（共 {len(words)} 个）：")
    print("─" * 45)
    for i, w in enumerate(words, 1):
        note = f"  [{w['note']}]" if w.get("note") else ""
        print(f"{i:3}. {w['word']:<20}{note}  (添加于 {w['added'][:10]})")


def cmd_delete(args):
    word = " ".join(args.word)
    words = load_words()
    new_words = [w for w in words if w["word"].lower() != word.lower()]
    if len(new_words) == len(words):
        print(f"未找到「{word}」。")
    else:
        save_words(new_words)
        print(f"✓ 已删除：{word}")


def cmd_setup(args):
    print("邮件配置向导")
    print("─" * 45)
    config = load_config()

    print("Gmail 需要使用「应用专用密码」，请前往：")
    print("https://myaccount.google.com/apppasswords")
    print()

    current_email = config.get("email", "")
    prompt_email = f"Gmail 地址 [{current_email}]: " if current_email else "Gmail 地址: "
    email = input(prompt_email).strip()
    if email:
        config["email"] = email

    password = getpass.getpass("Gmail 应用专用密码（不显示输入）: ").strip()
    if password:
        config["password"] = password

    default_to = config.get("to_email", config.get("email", ""))
    to_email = input(f"收件地址 [{default_to}]: ").strip()
    config["to_email"] = to_email or default_to

    current_key = "***已设置***" if config.get("anthropic_key") else "未设置"
    api_key = input(f"Anthropic API Key（用于 AI 讲解，可留空）[{current_key}]: ").strip()
    if api_key and api_key != "***已设置***":
        config["anthropic_key"] = api_key

    save_config(config)
    print("\n✓ 配置已保存。")
    print(f"\n设置每天早上 8 点自动发送，请运行：")
    print(f"  python vocab.py cron")


def cmd_cron(args):
    script = Path(__file__).resolve()
    python = sys.executable
    cron_line = f"0 8 * * * {python} {script} send >> ~/vocab_cron.log 2>&1"

    print("将以下内容添加到 crontab 可实现每天早 8 点自动发送：")
    print()
    print("  运行命令：crontab -e")
    print("  添加这行：")
    print(f"\n  {cron_line}\n")
    print("提示：macOS 上需要在「系统设置 → 隐私与安全 → 完全磁盘访问」")
    print("      中给终端/cron 授权，邮件才能正常发送。")

    choice = input("\n是否自动添加到 crontab？(y/n): ").strip().lower()
    if choice == "y":
        import subprocess
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        existing = result.stdout if result.returncode == 0 else ""
        if cron_line in existing:
            print("✓ crontab 中已有该条目，无需重复添加。")
        else:
            new_crontab = existing.rstrip() + "\n" + cron_line + "\n"
            proc = subprocess.run(["crontab", "-"], input=new_crontab, text=True)
            if proc.returncode == 0:
                print("✓ 已添加到 crontab，每天早 8 点自动发送。")
            else:
                print("✗ 添加失败，请手动运行 crontab -e 添加。")


# ── 单词讲解 ───────────────────────────────────────────────────────

def explain_with_claude(word, note, api_key):
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        note_line = f"\n用户记录的上下文：{note}" if note else ""
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{
                "role": "user",
                "content": (
                    f"请用中文讲解英语单词「{word}」{note_line}。\n"
                    "严格按以下格式输出，每行一项，不要多余内容：\n"
                    "音标: /xxx/\n"
                    "词性: xxx\n"
                    "释义: xxx\n"
                    "例句: xxx（英文）\n"
                    "译文: xxx（中文）\n"
                    "例句2: xxx（英文）\n"
                    "译文2: xxx（中文）\n"
                    "记忆: xxx（记忆技巧）\n"
                    "搭配: xxx（常见搭配）"
                ),
            }],
        )
        return message.content[0].text.strip()
    except Exception as e:
        return explain_with_free_api(word)


def translate_zh(text, retries=2):
    """英译中，用于给免费词典释义/例句配上中文翻译，兜底也用它直接翻单词本身。"""
    for attempt in range(retries):
        try:
            q = urllib.parse.quote(text)
            url = (
                "https://translate.googleapis.com/translate_a/single"
                f"?client=gtx&sl=en&tl=zh-CN&dt=t&q={q}"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            zh = "".join(seg[0] for seg in data[0])
            if zh.strip():
                return zh.strip()
        except Exception:
            if attempt + 1 < retries:
                time.sleep(1)
    return None


def explain_with_free_api(word):
    phonetic = None
    entries = []  # [(pos, definition_en, example_en), ...]
    try:
        url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
        req = urllib.request.Request(url, headers={"User-Agent": "vocab-py/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())[0]

        phonetic = data.get("phonetic") or next(
            (p.get("text") for p in data.get("phonetics", []) if p.get("text")), None
        )
        for meaning in data.get("meanings", [])[:2]:
            pos = meaning.get("partOfSpeech", "")
            for d in meaning.get("definitions", [])[:1]:
                entries.append((pos, d.get("definition", ""), d.get("example", "")))
    except Exception:
        pass  # 词典没收录（生僻词/变形），下面用翻译兜底

    lines = []
    if phonetic:
        lines.append(f"音标: {phonetic}")

    if entries:
        for pos, definition_en, example_en in entries:
            if pos:
                lines.append(f"词性: {pos}")
            definition_zh = translate_zh(definition_en) or definition_en
            lines.append(f"释义: {definition_zh}")
            if example_en:
                lines.append(f"例句: {example_en}")
                example_zh = translate_zh(example_en)
                if example_zh:
                    lines.append(f"译文: {example_zh}")
    else:
        # 词典查不到时，直接把单词本身翻译成中文，保证一定有中文释义
        word_zh = translate_zh(word)
        lines.append(f"释义: {word_zh or word}")

    return "\n".join(lines)


def get_explanation(word, note, api_key):
    if api_key:
        return explain_with_claude(word, note, api_key)
    return explain_with_free_api(word)


# ── 邮件构建 ───────────────────────────────────────────────────────

def build_html(words, explanations):
    today = datetime.now().strftime("%Y年%m月%d日")

    cards = ""
    for entry, exp in zip(words, explanations):
        w = entry["word"]
        note_html = (
            f'<div style="color:#888;font-size:13px;margin-bottom:8px">备注：{entry["note"]}</div>'
            if entry.get("note") else ""
        )
        # 格式化讲解：每行变成一个小行
        exp_lines = ""
        for line in exp.splitlines():
            line = line.strip()
            if not line:
                continue
            if ":" in line or "：" in line:
                sep = ":" if ":" in line else "："
                key, _, val = line.partition(sep)
                exp_lines += (
                    f'<div style="margin:4px 0">'
                    f'<span style="color:#888;min-width:44px;display:inline-block">{key.strip()}：</span>'
                    f'<span>{val.strip()}</span></div>'
                )
            else:
                exp_lines += f'<div style="margin:4px 0">{line}</div>'

        cards += f"""
        <div style="background:#f8faff;border-left:4px solid #4a7fd4;
                    padding:16px 20px;margin:16px 0;border-radius:0 8px 8px 0">
          <div style="font-size:20px;font-weight:bold;color:#1a3a6e;margin-bottom:8px">{w}</div>
          {note_html}
          <div style="font-size:14px;line-height:1.8;color:#333">{exp_lines}</div>
        </div>"""

    return f"""<!DOCTYPE html>
<html><body style="font-family:-apple-system,sans-serif;max-width:620px;
                   margin:0 auto;padding:20px;color:#222">
  <h2 style="color:#4a7fd4;border-bottom:2px solid #4a7fd4;padding-bottom:10px;margin-top:0">
    每日单词复习 &nbsp;·&nbsp; {today}
  </h2>
  <p style="color:#555">今天共 <strong>{len(words)}</strong> 个单词，加油！</p>
  {cards}
  <div style="margin-top:32px;padding-top:16px;border-top:1px solid #eee;
              color:#aaa;font-size:12px;text-align:center">
    由 vocab.py 自动发送 &nbsp;·&nbsp; 如需取消订阅，删除 crontab 中的对应条目
  </div>
</body></html>"""


def cmd_send(args):
    config = load_config()
    if not config.get("email") or not config.get("password"):
        print("请先运行：python vocab.py setup")
        return

    words = load_words()
    if not words:
        print("单词列表为空，请先添加单词。")
        return

    api_key = config.get("anthropic_key")
    print(f"正在获取 {len(words)} 个单词的讲解...")
    explanations = []
    for w in words:
        print(f"  • {w['word']}...", end="", flush=True)
        exp = get_explanation(w["word"], w.get("note", ""), api_key)
        explanations.append(exp)
        print(" ✓")

    html = build_html(words, explanations)
    today = datetime.now().strftime("%Y-%m-%d")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"每日单词复习 {today}（{len(words)} 个单词）"
    msg["From"] = config["email"]
    msg["To"] = config.get("to_email", config["email"])
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(config["email"], config["password"])
            server.send_message(msg)
        print(f"\n✓ 邮件已发送至 {msg['To']}")
    except smtplib.SMTPAuthenticationError:
        print("\n✗ 登录失败：请检查邮箱和应用专用密码")
        print("  应用专用密码获取地址：https://myaccount.google.com/apppasswords")
    except Exception as e:
        print(f"\n✗ 发送失败：{e}")


# ── 入口 ───────────────────────────────────────────────────────────

SUBCOMMANDS = {"add", "list", "delete", "send", "setup", "cron"}


def main():
    # 如果第一个参数不是子命令，默认视为 add
    if len(sys.argv) > 1 and sys.argv[1] not in SUBCOMMANDS and not sys.argv[1].startswith("-"):
        sys.argv.insert(1, "add")

    parser = argparse.ArgumentParser(
        description="单词记录 & 每日邮件复习",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  vocab serendipity                  # 添加单词\n"
            "  vocab ephemeral -n '在文章里看到的' # 添加并备注\n"
            "  vocab list                          # 查看列表\n"
            "  vocab send                          # 发送邮件\n"
        ),
    )
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("add", help="添加单词")
    p.add_argument("word", nargs="+", help="要添加的单词")
    p.add_argument("--note", "-n", help="备注（上下文、场景等）")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("list", help="查看单词列表")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("delete", help="删除单词")
    p.add_argument("word", nargs="+", help="要删除的单词")
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser("send", help="立即发送复习邮件")
    p.set_defaults(func=cmd_send)

    p = sub.add_parser("setup", help="配置邮箱和 API")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("cron", help="设置每天早 8 点自动发送")
    p.set_defaults(func=cmd_cron)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
