#!/usr/bin/env node
/**
 * scripts/update-readme-issues.js
 *
 * Fetches open/closed/all issues for a repository and replaces the block between
 * provided markers in the README with a generated list of issues.
 *
 * Usage (as used by the workflow):
 *   GH_TOKEN=... node scripts/update-readme-issues.js \
 *     --owner "YVaio" \
 *     --repo "ClassicCAD-for-FreeCAD" \
 *     --readme "README.md" \
 *     --start-marker "<!-- ISSUES_LIST:START -->" \
 *     --end-marker "<!-- ISSUES_LIST:END -->" \
 *     --state "open" \
 *     --per-page 100 \
 *     --commit
 *
 * Notes:
 * - No external dependencies (works with Node 20+ because it uses global fetch).
 * - If --commit is passed, the script will git add, commit and push the updated README.
 *   The workflow checks out with persist-credentials: true, so the push should work with
 *   the provided GITHUB_TOKEN.
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

function argvGet(name, def) {
  const idx = process.argv.indexOf('--' + name);
  if (idx === -1) return def;
  // boolean flags like --commit are handled separately (presence check).
  return process.argv[idx + 1];
}

function usageAndExit() {
  console.error(`Usage: --owner <owner> --repo <repo> --readme <file> --start-marker "<start>" --end-marker "<end>" [--state open|closed|all] [--per-page 100] [--commit]`);
  process.exit(1);
}

const OWNER = argvGet('owner');
const REPO = argvGet('repo');
const README = argvGet('readme');
const START_MARKER = argvGet('start-marker');
const END_MARKER = argvGet('end-marker');
const STATE = argvGet('state', 'open'); // open | closed | all
const PER_PAGE = Math.max(1, Math.min(100, parseInt(argvGet('per-page', '100'), 10)));
const COMMIT = process.argv.includes('--commit');

if (!OWNER || !REPO || !README || !START_MARKER || !END_MARKER) {
  usageAndExit();
}

const GH_TOKEN = process.env.GH_TOKEN || process.env.GITHUB_TOKEN;
if (!GH_TOKEN) {
  console.error('Set GH_TOKEN or GITHUB_TOKEN in environment (needs repo read access).');
  process.exit(1);
}

const REST = 'https://api.github.com';

async function fetchAllIssues() {
  const all = [];
  let page = 1;
  while (true) {
    const url = `${REST}/repos/${OWNER}/${REPO}/issues?state=${encodeURIComponent(STATE)}&per_page=${PER_PAGE}&page=${page}`;
    const res = await fetch(url, {
      headers: {
        Authorization: `bearer ${GH_TOKEN}`,
        Accept: 'application/vnd.github.v3+json',
        'User-Agent': 'update-readme-issues-script',
      },
    });
    if (!res.ok) {
      const txt = await res.text();
      throw new Error(`Failed to fetch issues: HTTP ${res.status}: ${txt}`);
    }
    const data = await res.json();
    // The issues endpoint returns both issues and PRs; filter out PRs
    const issuesOnly = data.filter(i => !i.pull_request);
    all.push(...issuesOnly);

    if (data.length < PER_PAGE) break;
    page += 1;
  }
  return all;
}

function formatIssueLine(issue) {
  // Example line: "- [#123] Issue title ([user](https://github.com/user)) - labels"
  const number = issue.number;
  const title = (issue.title || '').replace(/\r?\n/g, ' ').trim();
  const html_url = issue.html_url;
  const user = issue.user && issue.user.login ? issue.user.login : 'unknown';
  const labels = (issue.labels || []).map(l => (typeof l === 'string' ? l : l.name)).filter(Boolean);
  const labelPart = labels.length ? ` [${labels.join(', ')}]` : '';
  return `- [#${number}](${html_url}) ${title} — @${user}${labelPart}`;
}

function replaceBetweenMarkers(content, startMarker, endMarker, replacementBody) {
  const startIdx = content.indexOf(startMarker);
  if (startIdx === -1) throw new Error(`Start marker not found: ${startMarker}`);
  const afterStart = startIdx + startMarker.length;
  const endIdx = content.indexOf(endMarker, afterStart);
  if (endIdx === -1) throw new Error(`End marker not found: ${endMarker}`);
  const before = content.slice(0, afterStart);
  const after = content.slice(endIdx);
  return before + '\n\n' + replacementBody + '\n\n' + after;
}

(async () => {
  try {
    console.log(`Fetching issues for ${OWNER}/${REPO} (state=${STATE})...`);
    const issues = await fetchAllIssues();
    console.log(`Fetched ${issues.length} issue(s).`);

    // Sort by number ascending for stable output (optional)
    issues.sort((a, b) => a.number - b.number);

    const lines = issues.map(formatIssueLine);
    const body = lines.length ? lines.join('\n') : '_No issues found._';

    const readmePath = path.resolve(process.cwd(), README);
    if (!fs.existsSync(readmePath)) {
      throw new Error(`README file not found at path: ${readmePath}`);
    }

    const orig = fs.readFileSync(readmePath, 'utf8');
    const newContent = replaceBetweenMarkers(orig, START_MARKER, END_MARKER, body);

    if (newContent === orig) {
      console.log('No changes to README content between markers.');
      process.exit(0);
    }

    fs.writeFileSync(readmePath, newContent, 'utf8');
    console.log(`Updated ${README} with ${issues.length} issue(s).`);

    if (COMMIT) {
      try {
        // Configure git user if not configured
        try {
          execSync('git config user.name', { stdio: 'ignore' });
        } catch {
          execSync('git config user.name "github-actions[bot]"');
          execSync('git config user.email "github-actions[bot]@users.noreply.github.com"');
        }

        execSync(`git add "${README}"`, { stdio: 'inherit' });
        // commit only if there are staged changes
        const commitMsg = `chore: update README issues (${issues.length} issues)`;
        // git commit will exit with 1 and print "nothing to commit" if there are no changes;
        // we guard by checking git diff-index
        try {
          execSync('git diff --staged --quiet'); // throws if there are staged changes
          // if it didn't throw, there is no staged change (unexpected)
        } catch {
          // There are staged changes -> commit
          execSync(`git commit -m "${commitMsg}"`, { stdio: 'inherit' });
          // Push the current branch to origin
          execSync('git push', { stdio: 'inherit' });
          console.log('Committed and pushed changes.');
        }
      } catch (err) {
        console.error('Failed to commit/push changes:', err && (err.message || err));
        process.exit(2);
      }
    } else {
      console.log('Not committing (run with --commit to commit and push the README update).');
    }

    process.exit(0);
  } catch (err) {
    console.error('Fatal error:', err && (err.stack || err.message || String(err)));
    process.exit(2);
  }
})();