---
name: collect-unknown-words
description: 把用户明确表示不认识、想收藏或复习的英语单词和短语加入本地 vocab 词库，并按需查看、删除或发送复习邮件。普通的单词释义提问若没有收藏意图，不自动入库。
---

# 收集不认识的英语单词

这项 Skill 的主要动作是**记录生词**。当前机器使用 `/Users/theeeight/vocab.py`，词库在 `~/.vocab_words.json`。若该程序不存在，可使用随 Skill 附带的 [scripts/vocab.py](scripts/vocab.py)；不要把用户的词库、邮箱配置或密码复制进仓库。

## 收词

- 用户说“不认识/记住/收藏/collect 这个词”等，直接调用 `python3 /Users/theeeight/vocab.py add <词或短语>`。有原句、学科语境或用户给的解释时，用 `-n <简短备注>`保留上下文；没有就留空，不猜测来源。
- 保留用户给出的原词或短语，不擅自替换成词根、单数、同义词，也不把原句中的其他词一起入库。多个词依次添加；程序会按大小写不敏感的方式跳过重复项。
- 添加后简短确认记录结果。若用户同时想知道意思，可另给简短释义；收词本身无需联网查释义，邮件复习时程序会生成讲解。

## 管理和复习

| 用户意图 | 命令 |
| --- | --- |
| 查看已收集的词 | `python3 /Users/theeeight/vocab.py list` |
| 删除明确指定的词 | `python3 /Users/theeeight/vocab.py delete <词或短语>` |
| 立即发送复习邮件 | `python3 /Users/theeeight/vocab.py send` |
| 配置邮件和讲解服务 | `python3 /Users/theeeight/vocab.py setup` |
| 设置每日 08:00 发送 | `python3 /Users/theeeight/vocab.py cron` |

只在用户要求发信或设置定时复习、且已有相应授权时运行 `send` 或安装定时任务。单纯“收集这个词”只添加词条。删除只针对用户明确指定的词；不要为整理词形而批量改动旧词库。

## 程序约定

- `~/.vocab_words.json` 存词、备注和添加时间；`~/.vocab_config.json` 存 Gmail SMTP 凭据、收件地址及可选 Anthropic Key。查看配置时只检查键名或是否已设置，不打印密钥。配置文件应保持 `0600` 权限。
- 有 Anthropic Key 时，邮件使用模型生成中文讲解；没有时使用免费词典和翻译接口。外部服务可能失败，应检查实际输出，不把失败时的兜底文本说成已核实的释义。
- `cron` 子命令会展示计划任务并询问是否写入。不要因为运行了 `cron` 就假定安装成功；核对执行结果。macOS 上自动发送还取决于机器运行状态及 cron 的文件访问权限。
- 对程序本身作修改时，在临时 `HOME` 下测试添加、去重、列出和删除，避免测试污染用户真实词库；发信流程只在获准时验证。
