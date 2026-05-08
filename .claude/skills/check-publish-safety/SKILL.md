# /check-publish-safety

Check whether the project is safe to publish as open source. Scan for secrets, personal data, and sensitive files that should not be made public.

## Steps

1. List all tracked files:
   - Run `git ls-files` to get every file under version control.
   - Also run `git status` to catch untracked files that may accidentally end up in a release.

2. Scan source files for hardcoded secrets:
   - Search for patterns like: `api_key`, `secret`, `password`, `token`, `auth`, `private_key`, `access_key` (case-insensitive) assigned to string literals.
   - Flag any matches that look like real values (not placeholders like `YOUR_KEY_HERE` or environment variable reads like `os.environ`).

3. Check for personal information:
   - Scan for email addresses (regex: `\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b`).
   - Scan for home directory paths that embed a real username (e.g. `/home/alice/`, `/Users/bob/`).
   - Flag real names in comments or config if they appear alongside contact details.

4. Check for sensitive file types:
   - Look for files matching: `*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.crt`, `*.cer`, `*.env`, `*.env.*`, `*_rsa`, `*_dsa`, `id_rsa`, `id_ed25519`, `.netrc`, `.htpasswd`, `credentials`, `secrets.*`.
   - Report any found, even if gitignored (they may still be present on disk).

5. Audit `.gitignore`:
   - Verify that common sensitive file patterns are covered: `.env`, `*.pem`, `*.key`, `*.p12`, private key files, backup files (`*.bak`), editor swap files.
   - Flag sensitive file types that are tracked by git but should be ignored.

6. Scan commit history for secrets:
   - Run `git log --all --oneline` and note the total commit count.
   - Run `git log -p --all -- '*.env' '*.key' '*.pem' '*.secret'` to check if any sensitive files were ever committed and later removed.
   - If suspicious filenames appear in history, flag them — removal from the working tree does not remove them from git history.

7. Check configuration and documentation files:
   - Read README, any docs, and config files for hardcoded endpoints, internal hostnames, or credentials used as examples.

## Output format

State clearly at the top: **Safe to publish** or **Not safe to publish — issues found**.

Then list every finding under one of these headings:

**Blockers** — must be resolved before publishing (real secrets, real credentials, sensitive personal data in tracked files)

**Warnings** — should be reviewed (pattern matches that may be false positives, borderline personal info, files that probably belong in .gitignore)

**Suggestions** — good hygiene improvements that are not strictly blockers (missing .gitignore entries for common patterns, example values that could be replaced with placeholders)

For each finding include the file path, line number where applicable, and a concrete remediation step. End with a one-sentence overall verdict.
