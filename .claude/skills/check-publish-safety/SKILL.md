# /check-publish-safety

Check whether the project is safe to publish as open source. Scan for secrets, personal data, and sensitive files that should not be made public.

## Steps

1. List all tracked files:
   - Run `git ls-files` to get every file under version control.
   - Also run `git status` to catch untracked files that may accidentally end up in a release.
   - When checking whether a specific file is tracked, always use `git ls-files --error-unmatch <file>` — plain `git ls-files <file>` exits 0 even when the file is not tracked, making `&& echo "tracked"` a false positive.

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

8. Check for private personal content:
   This step is about content you may not want to share publicly — not secrets, but personal or contextual information that is fine on your own machine but potentially embarrassing or revealing if published.

   a. **Scratchpad and notes files** — look for files like `working-memory.md`, `notes.md`, `TODO.md`, `scratch.*`, `NOTES`, `journal.md`, or any `.md` file in the root that isn't README/CONTRIBUTING/CHANGELOG. Read them and summarise what's in them; flag if they contain personal plans, private context, or internal information.

   b. **Test fixtures with real personal data** — if the repo has fixture files that simulate user data (e.g. `tests/fixtures/**/*.md`, sample journal entries, example task lists), read a sample and check whether the content looks like real personal notes vs. clearly synthetic placeholder data. Real names, real project names, real dates combined with recognisable personal tasks are a red flag.

   c. **Commit messages** — run `git log --all --pretty=format:"%s %b"` and scan for: real names of people or companies, internal project codenames, personal frustration ("fix that stupid bug", "revert John's change"), or references to non-public systems. Flag anything that would be awkward if publicly visible.

   d. **TODO / FIXME / HACK comments** — grep for these in source files. Check whether they reference internal systems, real names, client names, or non-public architecture decisions that you would not want a stranger to read.

   e. **Internal URLs and hostnames** — grep for `http://` and `https://` occurrences outside of README/docs. Flag any that point to internal/private hosts (e.g. `localhost` with specific ports is fine; `https://internal.mycompany.com` is not).

   f. **Personal names in code** — grep for capitalised proper-noun sequences (e.g. two consecutive title-case words) in comments and strings that are not clearly example/placeholder values. This catches things like "Alice reviewed this" or "per Bob's request" that inadvertently reveal real collaborators.

## Output format

State clearly at the top: **Safe to publish** or **Not safe to publish — issues found**.

Then list every finding under one of these headings:

**Blockers** — must be resolved before publishing (real secrets, real credentials, sensitive personal data in tracked files)

**Warnings** — should be reviewed (pattern matches that may be false positives, borderline personal info, files that probably belong in .gitignore)

**Suggestions** — good hygiene improvements that are not strictly blockers (missing .gitignore entries for common patterns, example values that could be replaced with placeholders)

For each finding include the file path, line number where applicable, and a concrete remediation step. End with a one-sentence overall verdict.
