#!/usr/bin/env node
/**
 * scripts/update-readme-issues.js
 *
 * Fetches repo issues and injects a markdown list into README between markers.
 *
 * Usage (example):
 *  node scripts/update-readme-issues.js --owner YVaio --repo my-repo --readme README.md --commit
 *
 * Environment:
 *  - Requires GH_TOKEN or GITHUB_TOKEN in env.
 *
 * Flags:
 *  --owner (required)     : repo owner (user or org)
 *  --repo  (required)     : repo name
 *  --readme               : README path (default README.md)
 *  --start-marker         : start marker (default <!-- ISSUES_LIST:START -->)
 *  --end-marker           : end marker (default <!-- ISSUES_LIST:END -->)
 *  --state                : open|closed|all (default open)
 *  --label                : (optional) label to filter (exact label text)
 *  --per-page             : issues per page (default 100)
 *  --max                  : max issues to fetch (optional)
 *  --commit               : if present, commit & push the updated README (requires token push perms)
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

function argvGet(name, def) {
  const idx = process.argv.indexOf('--' + name);
  if (idx === -1) return def;
  return process.argv[idx + 1];
}

const OWNER = argvGet('owner');
const REPO = argvGet('repo');
const README = argvGet('readme', 'README.md');
const START_MARKER = argvGet('start-marker', '<!-- ISSUES_LIST:START -->');
const END_MARKER = argvGet('end-marker', '<!-- ISSUES_LIST:END -->');
const STATE = argvGet('state', 'open'); // open | closed | all
const LABEL = argvGet('label'); // optional label filter
const PER_PAGE = parseInt(argvGet('per-page', '100'), 10);
const MAX = argvGet('max') ? parseInt(argvGet('max'), 10) : null;
const DO_COMMIT = process.argv.includes('--commit');

if (!OWNER || !REPO) {
  console.error('Missing required --owner or --repo argument.');
  process.exit(1);
}

const GH_TOKEN = process.env.GH_TOKEN || process.env.GITHUB_TOKEN;
if (!GH_TOKEN) {
  console.error('Missing GH_TOKEN or GITHUB_TOKEN in environment. Add PROJECT_TOKEN secret and map to GH_TOKEN if needed.');
  process.exit(1);
}

const API = `https://api.github.com`;

async function fetchJson(url) {
  const res = await globalThis.fetch(url, {
    headers: {
      Authorization: `bearer ${GH_TOKEN}`,
      Accept: 'application/vnd.github.v3+json',
      'User-Agent': 'readme-issues-updater'
    }
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status} ${res.statusText}: ${text}`);
  }
  return res.json();
}

async function fetchAllIssues() {
  let page = 1;
  let all = [];
  while (true) {
    const params = new URLSearchParams();
    params.set('state', STATE);
    params.set('per_page', String(PER_PAGE));
    params.set('page', String(page));
    if (LABEL) params.set('labels', LABEL);

    const url = `${API}/repos/${OWNER}/${REPO}/issues?${params.toString()}`;
    const items = await fetchJson(url);

    // Filter out pull requests (the issues endpoint returns PRs too)
    const issuesOnly = items.filter(i => !i.pull_request);

    all = all.concat(issuesOnly);

    if (MAX && all.length >= MAX) {
      all = all.slice(0, MAX);
      break;
    }

    // Stop if less than per_page returned
    if (items.length < PER_PAGE) break;
    page++;
  }
  return all;
}

function firstLine(text, maxLen = 120) {
  if (!text) return '';
  const first = text.split('\n')[0].trim();
  if (first.length <= maxLen) return first;
  return first.slice(0, maxLen - 1) + '…';
}

function formatIssue(issue) {
  const number = issue.number;
  const title = issue.title || '(no title)';
  const url = issue.html_url;
  const state = issue.state; // open/closed
  const checkbox = state === 'open' ? '- [ ]' : '- [x]';
  const labels = (issue.labels || []).map(l => l.name).join(', ');
  const labelPart = labels ? ` — ${labels}` : '';
  const assignees = (issue.assignees || []).map(a => `@${a.login}`).join(', ');
  const assigneePart = assignees ? ` — ${assignees}` : '';
  const snippet = firstLine(issue.body || '', 140);
  const created = (new Date(issue.created_at)).toISOString().slice(0,10);
  const updated = (new Date(issue.updated_at)).toISOString().slice(0,10);
  return `${checkbox} [#${number} ${escapeMarkdown(title)}](${url}) — ${state}${labelPart}${assigneePart} — opened ${created} — updated ${updated}\n> ${escapeMarkdown(snippet)}`;
}

function escapeMarkdown(s) {
  if (!s) return '';
  return s.replace(/\n/g, ' ').replace(/\|/g, '\\|').replace(/\r/g, '');
}

(async () => {
  try {
    console.log(`Fetching issues for ${OWNER}/${REPO} (state=${STATE}${LABEL ? `, label=${LABEL}` : ''}) ...`);
    const issues = await fetchAllIssues();
    console.log(`Fetched ${issues.length} issues.`);

    const header = `## Issues for ${OWNER}/${REPO}\n\nGenerated: ${new Date().toISOString()}\n\n`;
    const issuesMd = issues.map(formatIssue).join('\n\n') || '_No matching issues found._';
    const block = `${START_MARKER}\n\n${header}${issuesMd}\n\n${END_MARKER}`;

    const readmePath = path.resolve(process.cwd(), README);
    let readme = '';
    if (fs.existsSync(readmePath)) {
      readme = fs.readFileSync(readmePath, 'utf8');
    } else {
      console.warn(`README not found at ${readmePath}. Will create a new README.`);
    }

    let newReadme;
    if (readme.includes(START_MARKER) && readme.includes(END_MARKER)) {
      const before = readme.split(START_MARKER)[0];
      const after = readme.split(END_MARKER).slice(1).join(END_MARKER);
      newReadme = before + block + after;
    } else {
      newReadme = readme + '\n\n' + block + '\n';
    }

    if (newReadme === readme) {
      console.log('No changes to README content. Exiting.');
      process.exit(0);
    }

    fs.writeFileSync(readmePath, newReadme, 'utf8');
    console.log(`Updated ${README} with ${issues.length} issues.`);

    if (DO_COMMIT) {
      try {
        console.log('Committing README changes...');
        execSync('git config user.name "github-actions[bot]"');
        execSync('git config user.email "41898282+github-actions[bot]@users.noreply.github.com"');
        execSync(`git add ${escapeShellArg(README)}`);
        execSync(`git commit -m "ci: sync README issues list (automated)"`);
        const repoFull = process.env.GITHUB_REPOSITORY;
        if (repoFull && GH_TOKEN) {
          const remoteWithToken = `https://x-access-token:${GH_TOKEN}@github.com/${repoFull}.git`;
          execSync(`git remote set-url origin ${remoteWithToken}`);
        }
        execSync('git push --set-upstream origin HEAD');
        console.log('Pushed README update.');
      } catch (err) {
        console.error('Failed to commit/push README:', err && (err.stdout || err.stderr || err.message) || err);
        process.exit(1);
      }
    }

    process.exit(0);
  } catch (err) {
    console.error('Error:', err && (err.stack || err.message || String(err)));
    process.exit(2);
  }
})();

function escapeShellArg(s) {
  if (!s) return "''";
  return `'${String(s).replace(/'/g, "'\\''")}'`;
}