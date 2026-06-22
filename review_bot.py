#!/usr/bin/env python3
"""
OpenCode Review Bot — Automated code review powered by OpenCode AI.

Flow:
  1. Clone/fetch a git repo & checkout a branch
  2. Get the diff against the base branch
  3. Send diff to OpenCode for structured review
  4. Generate a beautiful HTML report

Usage:
  python review_bot.py --repo https://github.com/user/repo.git --branch feature-x
  python review_bot.py --repo /path/to/local/repo --branch feature-y --base main

The key differentiator: this runs entirely headless via `opencode run`.
No interactive terminal needed — perfect for CI/CD, webhooks, Slack bots.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

# ─── Git helpers ──────────────────────────────────────────────────────────

def clone_repo(repo_url: str, target_dir: str, branch: str | None = None) -> str:
    """Clone a repo (or use existing local path)."""
    if os.path.isdir(repo_url):
        # Local repo — just copy .git or use in place
        print(f"📁 Using local repo: {repo_url}")
        # Fetch latest
        subprocess.run(["git", "-C", repo_url, "fetch", "--all"],
                       capture_output=True, check=False)
        subprocess.run(["git", "-C", repo_url, "checkout", branch],
                       capture_output=True, check=True)
        return repo_url

    print(f"📥 Cloning {repo_url} …")
    cmd = ["git", "clone", "--depth=50", repo_url, target_dir]
    if branch:
        cmd = ["git", "clone", "--depth=50", "--branch", branch, repo_url, target_dir]
    subprocess.run(cmd, check=True, capture_output=True)
    return target_dir


def _resolve_branch(repo_path: str, branch: str) -> str:
    """Resolve a branch name — tries origin/<branch>, then local <branch>."""
    for candidate in [f"origin/{branch}", branch]:
        result = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "--verify", candidate],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            return candidate
    return branch  # fallback


def get_diff(repo_path: str, base_branch: str, target_branch: str) -> dict:
    """Get diff between base and target branch."""
    # Fetch base for comparison (works for remote repos, no-op for local)
    subprocess.run(
        ["git", "-C", repo_path, "fetch", "origin", base_branch],
        capture_output=True, check=False
    )

    base_ref = _resolve_branch(repo_path, base_branch)
    target_ref = _resolve_branch(repo_path, target_branch)
    print(f"   Base ref: {base_ref} | Target ref: {target_ref}")

    # Get the diff
    result = subprocess.run(
        ["git", "-C", repo_path, "diff", f"{base_ref}...{target_ref}"],
        capture_output=True, text=True, check=True
    )
    diff_text = result.stdout

    # Get changed files
    result = subprocess.run(
        ["git", "-C", repo_path, "diff", "--name-only", f"{base_ref}...{target_ref}"],
        capture_output=True, text=True, check=True
    )
    changed_files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]

    # Get commit messages
    result = subprocess.run(
        ["git", "-C", repo_path, "log", "--oneline", f"{base_ref}..{target_ref}"],
        capture_output=True, text=True, check=True
    )
    commits = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]

    # Get diff stats
    result = subprocess.run(
        ["git", "-C", repo_path, "diff", "--stat", f"{base_ref}...{target_ref}"],
        capture_output=True, text=True, check=True
    )
    diff_stat = result.stdout.strip()

    return {
        "diff": diff_text,
        "changed_files": changed_files,
        "commits": commits,
        "diff_stat": diff_stat,
    }


def get_repo_info(repo_path: str) -> dict:
    """Get repo metadata."""
    def git(*args):
        r = subprocess.run(["git", "-C", repo_path, *args],
                           capture_output=True, text=True)
        return r.stdout.strip()

    return {
        "name": os.path.basename(git("rev-parse", "--show-toplevel") or repo_path),
        "url": git("config", "--get", "remote.origin.url") or "local",
        "current_branch": git("rev-parse", "--abbrev-ref", "HEAD") or "unknown",
        "last_commit": git("log", "-1", "--format=%H"),
        "last_commit_msg": git("log", "-1", "--format=%s"),
        "author": git("log", "-1", "--format=%an"),
    }


# ─── OpenCode review ──────────────────────────────────────────────────────

REVIEW_PROMPT = """\
You are a senior code reviewer. Review the following git diff thoroughly.

For EACH issue found, output a JSON object on its own line (one JSON per line, no array wrapper).

Each JSON object must have this exact shape:
{{
  "file": "path/to/file.ext",
  "line": <line_number_or_range_string>,
  "severity": "<critical|warning|suggestion|praise>",
  "category": "<security|performance|bug|style|maintainability|test|documentation>",
  "title": "Short one-line summary of the issue",
  "description": "Detailed explanation of the problem and why it matters",
  "suggestion": "Concrete code suggestion or fix"
}}

Rules:
- severity "critical": bugs, security vulnerabilities, data loss risks
- severity "warning": code smells, potential bugs, performance issues
- severity "suggestion": improvements, best practices, readability
- severity "praise": well-written code worth highlighting
- Be specific — reference actual line numbers from the diff
- If the code is clean, say so explicitly with a praise entry
- Output ONLY JSON lines, no markdown fences, no explanations outside JSON

DIFF TO REVIEW:
```diff
{diff}
```

Changed files: {files}

Output your review as JSON lines now:"""


def run_review(diff_data: dict, model: str | None = None) -> list[dict]:
    """
    Send diff to OpenCode for review via `opencode run`.

    This is the key differentiator — running headless, programmatically.
    With Claude Code this would require an API key (pay-per-token).
    Here we can use any provider OpenCode supports.
    """
    prompt = REVIEW_PROMPT.format(
        diff=diff_data["diff"][:50000],  # Cap to avoid token limits
        files=", ".join(diff_data["changed_files"]),
    )

    # Default to OpenRouter model if not specified
    effective_model = model or "openrouter/anthropic/claude-sonnet-4"

    cmd = ["opencode", "run", "--model", effective_model, prompt]

    print(f"🤖 Sending review to OpenCode…")
    print(f"   Model: {effective_model}")

    # Pass through env vars (for API keys like OPENROUTER_API_KEY)
    env = os.environ.copy()

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=300,  # 5-minute timeout
        env=env,
        stdin=subprocess.DEVNULL,  # Prevent hanging on stdin
    )

    if result.returncode != 0:
        print(f"⚠️  OpenCode returned non-zero exit: {result.returncode}")
        print(f"   stderr: {result.stderr[:500]}")
        # Try to use whatever output we got

    # Parse JSON lines from output
    findings = []
    raw_output = result.stdout.strip()

    # Try to extract JSON objects even from noisy output
    json_pattern = re.compile(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', re.DOTALL)

    for line in raw_output.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Skip non-JSON lines
        if not line.startswith("{"):
            # Try to find JSON embedded in the line
            matches = json_pattern.findall(line)
            if not matches:
                continue
            for match in matches:
                try:
                    finding = json.loads(match)
                    if "severity" in finding:
                        findings.append(finding)
                except json.JSONDecodeError:
                    continue
        else:
            try:
                finding = json.loads(line)
                if "severity" in finding:
                    findings.append(finding)
            except json.JSONDecodeError:
                continue

    # Fallback: scan entire output for JSON objects
    if not findings:
        for match in json_pattern.findall(raw_output):
            try:
                finding = json.loads(match)
                if "severity" in finding:
                    findings.append(finding)
            except json.JSONDecodeError:
                continue

    print(f"✅ Found {len(findings)} review findings")
    return findings


# ─── HTML report generation ───────────────────────────────────────────────

SEVERITY_CONFIG = {
    "critical": {"emoji": "🔴", "color": "#dc2626", "label": "Critical"},
    "warning":  {"emoji": "🟡", "color": "#d97706", "label": "Warning"},
    "suggestion": {"emoji": "🔵", "color": "#2563eb", "label": "Suggestion"},
    "praise":   {"emoji": "🟢", "color": "#16a34a", "label": "Good Practice"},
}

def generate_html_report(
    findings: list[dict],
    diff_data: dict,
    repo_info: dict,
    base_branch: str,
    target_branch: str,
    output_path: str,
    model: str | None = None,
) -> str:
    """Generate a beautiful self-contained HTML report."""

    # Organize findings
    by_severity = {"critical": [], "warning": [], "suggestion": [], "praise": []}
    for f in findings:
        sev = f.get("severity", "suggestion").lower()
        if sev in by_severity:
            by_severity[sev].append(f)
        else:
            by_severity["suggestion"].append(f)

    by_file = {}
    for f in findings:
        fname = f.get("file", "unknown")
        if fname not in by_file:
            by_file[fname] = []
        by_file[fname].append(f)

    # Sort files by severity weight
    sev_weight = {"critical": 4, "warning": 3, "suggestion": 2, "praise": 1}
    for fname in by_file:
        by_file[fname].sort(key=lambda x: sev_weight.get(x.get("severity", ""), 0), reverse=True)

    # Compute health score (0-100)
    total_weight = (
        len(by_severity["critical"]) * 25 +
        len(by_severity["warning"]) * 10 +
        len(by_severity["suggestion"]) * 2
    )
    health_score = max(0, 100 - total_weight)

    if health_score >= 80:
        health_label = "Healthy ✅"
        health_color = "#16a34a"
    elif health_score >= 60:
        health_label = "Needs Attention ⚠️"
        health_color = "#d97706"
    else:
        health_label = "At Risk 🔴"
        health_color = "#dc2626"

    template_dir = Path(__file__).parent
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)

    template = env.get_template("report_template.html")
    html = template.render(
        repo_info=repo_info,
        base_branch=base_branch,
        target_branch=target_branch,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        findings=findings,
        by_severity=by_severity,
        by_file=by_file,
        changed_files=diff_data["changed_files"],
        commits=diff_data["commits"],
        diff_stat=diff_data["diff_stat"],
        health_score=health_score,
        health_label=health_label,
        health_color=health_color,
        severity_config=SEVERITY_CONFIG,
        model=model or "openrouter/anthropic/claude-sonnet-4",
        total_findings=len(findings),
    )

    Path(output_path).write_text(html, encoding="utf-8")
    print(f"📊 Report saved to: {output_path}")
    return output_path


# ─── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="🤖 OpenCode Review Bot — AI-powered code review with HTML report"
    )
    parser.add_argument("--repo", required=True, help="Git repo URL or local path")
    parser.add_argument("--branch", required=True, help="Branch to review")
    parser.add_argument("--base", default="main", help="Base branch to diff against (default: main)")
    parser.add_argument("--model", default=None, help="OpenCode model override (e.g. openrouter/anthropic/claude-sonnet-4)")
    parser.add_argument("--output", default="review-report.html", help="Output HTML report path")
    parser.add_argument("--workdir", default=None, help="Working directory for clone (default: temp)")
    args = parser.parse_args()

    print("═" * 60)
    print("  🤖 OpenCode Review Bot")
    print("═" * 60)

    # Step 1: Get the code
    tmpdir = None
    repo_path = args.repo
    if not os.path.isdir(args.repo):
        tmpdir = tempfile.mkdtemp(prefix="review-bot-")
        repo_path = clone_repo(args.repo, tmpdir, args.branch)
    else:
        subprocess.run(["git", "-C", repo_path, "checkout", args.branch],
                       capture_output=True, check=False)

    # Step 2: Get repo info
    print("\n📋 Collecting repo metadata…")
    repo_info = get_repo_info(repo_path)
    print(f"   Repo: {repo_info['name']}")
    print(f"   Branch: {args.branch}")
    print(f"   Base: {args.base}")

    # Step 3: Get diff
    print("\n🔍 Computing diff…")
    diff_data = get_diff(repo_path, args.base, args.branch)

    if not diff_data["changed_files"]:
        print("\n⚠️  No changes found between branches. Nothing to review.")
        sys.exit(0)

    print(f"   Changed files: {len(diff_data['changed_files'])}")
    print(f"   Commits: {len(diff_data['commits'])}")
    print(f"   Diff size: {len(diff_data['diff']):,} chars")

    # Step 4: Run AI review
    print("\n" + "─" * 60)
    findings = run_review(diff_data, model=args.model)

    # Step 5: Generate report
    print("\n" + "─" * 60)
    output_path = generate_html_report(
        findings=findings,
        diff_data=diff_data,
        repo_info=repo_info,
        base_branch=args.base,
        target_branch=args.branch,
        output_path=args.output,
        model=args.model,
    )

    print("\n" "═" * 60)
    print(f"  ✅ Review complete!")
    print(f"  📊 Report: {output_path}")
    print(f"  📁 Findings: {len(findings)} total")
    print("═" * 60)


if __name__ == "__main__":
    main()
