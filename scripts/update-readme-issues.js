#!/usr/bin/env node

// README issues updater for GitHub Actions
// - Automatically inserts the start/end markers if they are missing or in the wrong order
// - Replaces the content between the markers with the current issues list
// Usage example:
// node scripts/update-readme-issues.js --owner "YVaio" --repo "ClassicCAD-for-FreeCAD" --readme "README.md" --start-marker "<!-- ISSUES_LIST:START -->" --end-marker "<!-- ISSUES_LIST:END -->" --state "open" --per-page 100 --commit

const fs = require('fs');
const path = require('path');
const child_process = require('child_process');

function parseArgs() {
  const args = process.argv.slice(2);
  const map = {};
  for (let i = 0; i < args.length; i++) {
    if (args[i].startsWith('--')) {
      const key = args[i].slice(2);
      const val = (i + 1 < args.length && !args[i + 1].startsWith('--')) ? args[++i] : 'true';
      map[key] = val;
    }
  }
  return map;
}

async function fetchAllIssues(owner, repo, state, per_page, token) {
  per_page = Number(per_page) || 100;
  let page = 1;
  const issues = [];
  while (true) {
    const url = `https://api.github.com/repos/${owner}/${repo}/issues?state=${state}&per_page=${per_page}&page=${page}`;
    const res = await fetch(url, {
      headers: {
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'update-readme-issues-script',
        'Authorization': `token ${token}`
      }
    });
    if (!res.ok) {
      throw new Error(`GitHub API error: ${res.status} ${res.statusText}`);
    }
    const data = await res.json();
    // exclude pull requests
    const pageIssues = data.filter(i => !i.pull_request);
    issues.push(...pageIssues);
    if (data.length < per_page) break;
    page++;
  }
  return issues;
}

function buildMarkdownList(issues) {
  if (!issues.length) return '*No open issues.*\n';
  return issues.map(i => {
    const labels = (i.labels || []).map(l => `\`${l.name}\``).join(' ');
    return `- [#${i.number}](${i.html_url}) ${i.title}${labels ? ' — ' + labels : ''}`;
  }).join('\n') + '\n';
}

function insertMarkersIfMissing(content, startMarker, endMarker) {
  let startIdx = content.indexOf(startMarker);
  let endIdx = content.indexOf(endMarker);

  // If both present and in correct order, nothing to do.
  if (startIdx !== -1 && endIdx !== -1 && endIdx > startIdx) {
    return { content, startIdx, endIdx };
  }

  // Remove any stray markers to avoid duplication (handles reversed order too)
  let cleaned = content.split(startMarker).join('');
  cleaned = cleaned.split(endMarker).join('');

  // Choose an insertion point: after a top-level H2 (## ) if present, otherwise append
  const h2match = cleaned.match(/^##\s+/m);
  const insertPos = h2match ? cleaned.indexOf(h2match[0]) : cleaned.length;

  const markersBlock = `\n\n${startMarker}\n\n${endMarker}\n\n`;
  const newContent = cleaned.slice(0, insertPos) + markersBlock + cleaned.slice(insertPos);

  const newStartIdx = newContent.indexOf(startMarker);
  const newEndIdx = newContent.indexOf(endMarker);

  return { content: newContent, startIdx: newStartIdx, endIdx: newEndIdx };
}

async function main() {
  const opts = parseArgs();
  const owner = opts.owner;
  const repo = opts.repo;
  const readme = opts.readme || 'README.md';
  const startMarker = opts['start-marker'] || '<!-- ISSUES_LIST:START -->';
  const endMarker = opts['end-marker'] || '<!-- ISSUES_LIST:END -->';
  const state = opts.state || 'open';
  const per_page = opts['per-page'] || 100;
  const doCommit = opts.commit === 'true' || opts.commit === '1' || opts.commit === true;
  const token = process.env.GH_TOKEN || process.env.GITHUB_TOKEN;

  if (!owner || !repo) {
    console.error('Missing --owner or --repo');
    process.exit(2);
  }
  if (!token) {
    console.error('Missing GH_TOKEN or GITHUB_TOKEN environment variable');
    process.exit(2);
  }

  console.log(`Fetching ${state} issues for ${owner}/${repo}...`);
  const issues = await fetchAllIssues(owner, repo, state, per_page, token);
  const md = buildMarkdownList(issues);

  const readmePath = path.resolve(process.cwd(), readme);
  if (!fs.existsSync(readmePath)) {
    console.error(`README file not found at path: ${readmePath}`);
    process.exit(2);
  }

  let content = fs.readFileSync(readmePath, 'utf8');

  // Ensure markers exist and are in the correct order; insert them if needed.
  const inserted = insertMarkersIfMissing(content, startMarker, endMarker);
  content = inserted.content;
  let startIdx = inserted.startIdx;
  let endIdx = inserted.endIdx;

  if (startIdx === -1 || endIdx === -1 || endIdx < startIdx) {
    // Defensive check; should not happen because insertMarkersIfMissing ensures markers
    console.error('Failed to ensure start/end markers in README.');
    process.exit(2);
  }

  console.log(`Start marker index: ${startIdx}, End marker index: ${endIdx}`);

  const before = content.slice(0, startIdx + startMarker.length);
  const after = content.slice(endIdx); // include the endMarker and the rest

  const newContent = before + '\n\n' + md + '\n' + after;

  if (newContent === content) {
    console.log('README already up to date — nothing to commit.');
    process.exit(0);
  }

  fs.writeFileSync(readmePath, newContent, 'utf8');
  console.log('README updated on disk.');

  if (doCommit) {
    try {
      const relativePath = path.relative(process.cwd(), readmePath) || readme;
      child_process.execSync('git config user.email "action@github.com"');
      child_process.execSync('git config user.name "GitHub Actions"');
      child_process.execSync(`git add "${relativePath.replace(/"/g, '\\"')}"`);
      // commit may fail if there are no staged changes; don't crash on that
      try {
        child_process.execSync(`git commit -m "Update README with ${state} issues"`);
      } catch (e) {
        console.log('No changes to commit or git commit failed (this is ok).');
      }
      // Push will use the checked-out repository credentials (GITHUB_TOKEN)
      child_process.execSync('git push');
      console.log('Changes pushed.');
    } catch (err) {
      console.error('Git push failed:', err.message);
      process.exit(1);
    }
  }
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});