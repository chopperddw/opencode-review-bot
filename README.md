# 🤖 OpenCode Review Bot

Automated AI code review bot powered by **OpenCode** — the open-source, provider-agnostic coding agent.

## What It Does

```
Git Repo + Branch → OpenCode AI Review → Beautiful HTML Report
```

1. **Clones** a repo and checks out the target branch
2. **Diffs** against the base branch (main)
3. **Sends** the diff to OpenCode for structured code review
4. **Generates** a professional HTML report with severity levels, health score, and actionable suggestions

## Why This Matters (vs Claude Code)

This bot is the **killer demo** for OpenCode over Claude Code:

| | Claude Code | OpenCode |
|---|---|---|
| **Headless automation** | Limited (`-p` print mode) | Full programmatic control |
| **Provider** | Anthropic only | Any provider (Claude, GPT, Gemini, local) |
| **Subscription** | Interactive CLI only | API keys work everywhere |
| **Cost control** | Fixed per-provider | Route by task complexity |
| **Privacy** | Data sent to vendor | Zero data storage |

**Key point:** Claude Code subscriptions (Pro/Max) can't be used in automation/CI.
OpenCode with any API key = full programmatic access.

## Quick Start

```bash
# Install dependencies
uv init && uv add jinja2

# Run a review
export OPENROUTER_API_KEY=sk-or-...
python review_bot.py \
  --repo https://github.com/user/repo.git \
  --branch feature/new-api \
  --base main \
  --output review.html

# Open the report
open review.html  # macOS | xdg-open review.html  # Linux
```

## Options

```bash
python review_bot.py --help
```

| Flag | Description | Default |
|------|-------------|---------|
| `--repo` | Git repo URL or local path | *(required)* |
| `--branch` | Branch to review | *(required)* |
| `--base` | Base branch to diff against | `main` |
| `--model` | OpenCode model (e.g. `openrouter/openai/gpt-5.5`) | `openrouter/anthropic/claude-sonnet-4` |
| `--output` | Output HTML path | `review-report.html` |

## Try Different Models

```bash
# Review with Claude Sonnet
python review_bot.py --repo ... --model openrouter/anthropic/claude-sonnet-4

# Review with GPT
python review_bot.py --repo ... --model openrouter/openai/gpt-5.5

# Review with Gemini
python review_bot.py --repo ... --model openrouter/google/gemini-2.5-pro
```

## Integration Ideas

- **CI/CD Pipeline**: Run on every PR, post report as comment
- **Slack Bot**: Webhook triggers review on PR open
- **Scheduled**: Review all merged PRs weekly
- **Multi-model**: Run same review through different models, compare results

## Demo Repo

A test repo with intentional security issues is available:

```bash
python review_bot.py \
  --repo /tmp/demo-codebase \
  --branch feature/user-auth \
  --base main \
  --output demo-report.html
```

Expect ~24 findings including SQL injection, plaintext passwords, hardcoded credentials, debug mode in production, and more.
