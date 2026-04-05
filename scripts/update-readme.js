#!/usr/bin/env node
/**
 * Usage:
 *  node scripts/update-readme.js --owner OWNER --project-number 1 --readme README.md
 *
 * Requires env GH_TOKEN (use the repository secret PROJECT_TOKEN),
 * or the action can set GH_TOKEN to the workflow token.
 */

const fs = require('fs');
const path = require('path');
const fetch = require('node-fetch');

function argvGet(name, def) {
  const idx = process.argv.indexOf('--' + name);
  if (idx === -1) return def;
  return process.argv[idx + 1];
}

const OWNER = argvGet('owner');
const PROJECT_NUMBER = parseInt(argvGet('project-number'), 10);
const README = argvGet('readme', 'README.md');
const START_MARKER = argvGet('start-marker', '<!-- PROJECT_ISSUES:START -->');
const END_MARKER = argvGet('end-marker', '<!-- PROJECT_ISSUES:END -->');
const ITEMS_FIRST = parseInt(argvGet('items-first', '100'), 10);

if (!OWNER || !PROJECT_NUMBER) {
  console.error('Missing --owner or --project-number');
  process.exit(1);
}

const GH_TOKEN = process.env.GH_TOKEN || process.env.GITHUB_TOKEN;
if (!GH_TOKEN) {
  console.error('Missing GH_TOKEN environment variable. Put a token in PROJECT_TOKEN secret and map to GH_TOKEN in the workflow.');
  process.exit(1);
}

const GRAPHQL = 'https://api.github.com/graphql';

const query = `
query($owner:String!, $projectNumber:Int!, $itemsFirst:Int!) {
  user(login:$owner) {
    projectV2(number:$projectNumber) {
      id
      title
      url
      items(first:$itemsFirst) {
        nodes {
          id
          content {
            __typename
            ... on Issue {
              number
              title
              url
              state
              labels(first:10) {
                nodes { name }
              }
            }
            ... on DraftIssue {
              title
              body
            }
          }
        }
      }
    }
  }
}
`;

async function graphql(variables) {
  const res = await fetch(GRAPHQL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `bearer ${GH_TOKEN}`,
      Accept: 'application/vnd.github.v3+json',
    },
    body: JSON.stringify({ query, variables }),
  });
  const json = await res.json();
  if (json.errors) {
    console.error('GraphQL errors:', JSON.stringify(json.errors, null, 2));
    throw new Error('GraphQL query failed');
  }
  return json.data;
}

function formatItem(node) {
  const c = node.content;
  if (!c) return null;
  if (c.__typename === 'Issue') {
    const labels = (c.labels?.nodes || []).map(l => l.name).join(', ');
    const checkbox = c.state === 'OPEN' ? '- [ ]' : '- [x]';
    const labelPart = labels ? ` — ${labels}` : '';
    return `${checkbox} [#${c.number} ${escapeMarkdown(c.title)}](${c.url})${labelPart}`;
  } else if (c.__typename === 'DraftIssue') {
    // DraftIssues are project-only notes that look like issues
    return `- [ ] ${escapeMarkdown(c.title)}  _(project note)_`;
  } else {
    return `- [ ] ${escapeMarkdown(c.title || '(unknown)')}  (_${c.__typename}_)`;
  }
}

function escapeMarkdown(s) {
  if (!s) return s;
  return s.replace(/\n/g, ' ').replace(/\|/g, '\\|');
}

(async () => {
  try {
    const data = await graphql({ owner: OWNER, projectNumber: PROJECT_NUMBER, itemsFirst: ITEMS_FIRST });
    const project = data?.user?.projectV2;
    if (!project) {
      console.error('Project not found. Verify owner and project number and token permissions.');
      process.exit(2);
    }

    const title = project.title || `Project #${PROJECT_NUMBER}`;
    const generatedAt = new Date().toISOString();
    const header = `### Project: ${escapeMarkdown(title)}\n\nGenerated: ${generatedAt}\n\n`;

    const nodes = project.items?.nodes || [];
    const items = nodes.map(formatItem).filter(Boolean);

    const body = header + (items.length ? items.join('\n') : '_No items found_') + '\n';

    const readmePath = path.resolve(process.cwd(), README);
    let readme = '';
    if (fs.existsSync(readmePath)) {
      readme = fs.readFileSync(readmePath, 'utf8');
    } else {
      console.warn(`README file not found at ${readmePath}, creating a new one.`);
    }

    const start = START_MARKER;
    const end = END_MARKER;

    const newBlock = `${start}\n\n${body}\n${end}`;

    let newReadme;
    if (readme.includes(start) && readme.includes(end)) {
      const before = readme.split(start)[0];
      const after = readme.split(end).slice(1).join(end);
      newReadme = before + newBlock + after;
    } else {
      // append at end if no markers found
      newReadme = readme + '\n\n' + newBlock + '\n';
    }

    if (newReadme === readme) {
      console.log('README unchanged. Nothing to commit.');
      return;
    }

    fs.writeFileSync(readmePath, newReadme, 'utf8');
    console.log(`Updated ${README} with ${items.length} project items.`);
    process.exit(0);
  } catch (err) {
    console.error(err);
    process.exit(99);
  }
})();