#!/usr/bin/env node
/**
 * scripts/update-readme-issues-hierarchy.js
 *
 * Fetches repo issues and injects a hierarchical markdown list into README between markers.
 *
 * Usage:
 *  node scripts/update-readme-issues-hierarchy.js --owner OWNER --repo REPO --readme README.md --state open --commit
 *
 * Environment:
 *  - GH_TOKEN or GITHUB_TOKEN must be in env for API calls and optional commit.
 *
 * Hierarchy detection:
 *  - Looks for "Parent: #123" (case-insensitive) in the issue body or title.
 *  - Supports multi-level nesting if children also reference parents.
 *
 * No external libs required (uses Node's global fetch on Node >= 18).
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
      'User-Agent': 'readme-issues-hierarchy-updater'
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

    if (items.length < PER_PAGE) break;
    page++;
  }
  return all;
}

// parent detection: look for "parent" followed by '#' and digits, e.g. "Parent: #123"
function detectParentNumber(issue) {
  const checks = [];
  if (issue.title) checks.push(issue.title);
  if (issue.body) checks.push(issue.body);
  const text = checks.join('\n');
  // common patterns:
  // Parent: #123
  // parent issue #123
  // parent #123
  // (parent #123) in title
  const re = /parent(?:\s+issue)?\s*[:\-]?\s*#?(\d+)/i;
  const m = text.match(re);
  if (m && m[1]) return parseInt(m[1], 10);
  return null;
}

function firstLine(text, maxLen = 120) {
  if (!text) return '';
  const first = text.split('\n')[0].trim();
  if (first.length <= maxLen) return first;
  return first.slice(0, maxLen - 1) + '…';
}

function escapeMarkdown(s) {
  if (!s) return '';
  return s.replace(/\n/g, ' ').replace(/\|/g, '\\|').replace(/\r/g, '');
}

function formatLine(issue, indentLevel = 0) {
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

  const indent = '  '.repeat(indentLevel); // two spaces per level
  const line = `${indent}${checkbox} [#${number} ${escapeMarkdown(title)}](${url}) — ${state}${labelPart}${assigneePart} — opened ${created} — updated ${updated}`;
  const blockquote = snippet ? `\n${indent}> ${escapeMarkdown(snippet)}` : '';
  return line + blockquote;
}

// Build tree from list of issues using parent references
function buildIssueTree(issues) {
  const map = new Map();
  issues.forEach(i => map.set(i.number, { issue: i, children: [], parent: null }));

  const roots = [];

  for (const node of map.values()) {
    const parentNum = detectParentNumber(node.issue);
    if (parentNum && map.has(parentNum)) {
      const parentNode = map.get(parentNum);
      node.parent = parentNode;
      parentNode.children.push(node);
    } else {
      roots.push(node);
    }
  }

  // Optionally sort children (by number or created_at). We'll keep the original order.
  return { map, roots };
}

function renderTreeNodes(nodes, out = [], indent = 0) {
  // nodes is an array of {issue, children}
  // We'll print each node then its children recursively
  for (const node of nodes) {
    out.push(formatLine(node.issue, indent));
    if (node.children && node.children.length) {
      // recursively render children
      renderTreeNodes(node.children, out, indent + 1);
    }
  }
  return out;
}

(async () => {
  try {
    console.log(`Fetching issues for ${OWNER}/${REPO} (state=${STATE}${LABEL ? `, label=${LABEL}` : ''}) ...`);
    const issues = await fetchAllIssues();
    console.log(`Fetched ${issues.length} issues.`);

    // Build hierarchy
    const { roots } = buildIssueTree(issues);
    // Render
    const header = `## Issues for ${OWNER}/${REPO}\n\nGenerated: ${new Date().toISOString()}\n\n`;
    const rendered = renderTreeNodes(roots, [], 0).join('\n\n') || '_No matching issues found._';
    const block = `${START_MARKER}\n\n${header}${rendered}\n\n${END_MARKER}`;

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
    console.log(`Updated ${README} with ${issues.length} issues (${roots.length} top-level roots).`);

    if (DO_COMMIT) {
      try {
        console.log('Committing README changes...');
        execSync('git config user.name "github-actions[bot]"');
        execSync('git config user.email "41898282+github-actions[bot]@users.noreply.github.com"');
        execSync(`git add ${escapeShellArg(README)}`);
        execSync(`git commit -m "ci: sync README issues list (hierarchical, automated)"`);
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