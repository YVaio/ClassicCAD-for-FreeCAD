#!/usr/bin/env node

// Simple README issues updater that calls GitHub REST v3 and replaces a marker section
// Usage: node scripts/update-readme-issues.js --owner "YVaio" --repo "ClassicCAD-for-FreeCAD" --readme "README.md" --start-marker "<!-- ISSUES_LIST:START -->" --end-marker "<!-- ISSUES_LIST:END -->" --state "open" --per-page 100 --commit

const fs = require('fs');
const path = require('path');
const child_process = require('child_process');

function parseArgs() {
  const args = process.argv.slice(2);
  const map = {};
  for (let i = 0; i < args.length; i++) {
    if (args[i].startsWith('--')) {
      const key = args[i].slice(2);
      const val = (i+1 < args.length && !args[i+1].startsWith('--')) ? args[++i] : 'true';
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
    return `- [#${i.number}](${i.html_url}) ${i.title} ${labels ? ' — ' + labels : ''}`;
  }).join('\n') + '\n';
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

  const issues = await fetchAllIssues(owner, repo, state, per_page, token);
  const md = buildMarkdownList(issues);

  const readmePath = path.resolve(process.cwd(), readme);
  let content = fs.readFileSync(readmePath, 'utf8');

  const startIdx = content.indexOf(startMarker);
  const endIdx = content.indexOf(endMarker);
  if (startIdx === -1 || endIdx === -1 || endIdx < startIdx) {
    console.error('Start or end marker not found or in wrong order in README');
    process.exit(2);
  }

  const before = content.slice(0, startIdx + startMarker.length);
  const after = content.slice(endIdx);

  const newContent = before + '\n\n' + md + '\n' + after;
  if (newContent === content) {
    console.log('README already up to date — nothing to commit.');
    process.exit(0);
  }

  fs.writeFileSync(readmePath, newContent, 'utf8');
  console.log('README updated.');

  if (doCommit) {
    try {
      child_process.execSync('git config user.email "action@github.com"');
      child_process.execSync('git config user.name "GitHub Actions"');
      child_process.execSync(`git add "${readmePath.replace(/"/g,'\\"')}"`);
      child_process.execSync(`git commit -m "Update README with ${state} issues" || true`);
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