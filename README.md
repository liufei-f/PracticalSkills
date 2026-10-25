# PracticalSkills

个人使用的 Codex Skills。每个目录都有一份 `SKILL.md` 和所需的示例脚本。

## Skills

| Skill | 用途 |
| --- | --- |
| [collect-unknown-words](collect-unknown-words/SKILL.md) | 把明确想收藏的陌生英语单词或短语加入本地 vocab 词库；按需查看、删除及邮件复习。 |
| [daily-llm-email-digest](daily-llm-email-digest/SKILL.md) | 创建每天检索 LLM 进展、解释概念并发送邮件的本地程序。 |
| [pptx-speaker-notes](pptx-speaker-notes/SKILL.md) | 为已有 PPT 首次撰写逐页讲稿，或按用户更新的版本修订 Notes；核对内容、衔接、页面与动画。 |

## 使用

将需要的 Skill 目录放到 `~/.codex/skills/`（若设置了 `CODEX_HOME`，则放到 `$CODEX_HOME/skills/`），或在任务中明确提供对应 `SKILL.md` 的路径。仅把文件放在本仓库不会自动启用 Skill。

例如，可以请 Codex“用 `collect-unknown-words` 收藏 *serendipity*，备注是在论文里看到的”、“用 `daily-llm-email-digest` 建立每日 LLM 简报”，或“用 `pptx-speaker-notes` 给这份 PPT 首次写讲稿 / 按我改过页序的 PPT 调整讲稿”。各 Skill 的具体流程和边界写在对应的 `SKILL.md` 中。

## 本地数据与凭据

仓库中的脚本不包含邮箱地址、邮件应用专用密码、API Key 或已收藏的单词。运行时，vocab 程序从 `~/.vocab_words.json` 和 `~/.vocab_config.json` 读取本地数据；LLM 简报还可从 `~/.llm_digest_config.json` 读取 AI Key。这些私有文件不要提交到仓库。
