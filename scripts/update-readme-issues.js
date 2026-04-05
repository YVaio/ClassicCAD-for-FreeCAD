#!/usr/bin/env node
/**
 * scripts/label-project-items.js
 *
 * Fetches items from a Projects (v2) project and adds a label to issues
 * that are currently in one of the project columns (single-select field)
 * you specify.
 *
 * Usage:
 *  GH_TOKEN=ghp_... node scripts/label-project-items.js \
 *    --owner YVaio --project-number 1 \
 *    --columns "In review,Ready" \
 *    --label "in-review" \
 *    --dry-run
 *
 * Or run without --dry-run to actually add labels.
 *
 * Notes:
 * - GH_TOKEN must have repo scope (to add labels to issues) and read access to Projects v2.
 * - Script uses GraphQL to read project items and REST to add labels to issues.
 */

const fetch = globalThis.fetch;
const { execSync } = require('child_process');

function argvGet(name, def) {
  const idx = process.argv.indexOf('--' + name);
  if (idx === -1) return def;
  return process.argv[idx + 1];
}

const OWNER = argvGet('owner');
const PROJECT_NUMBER = parseInt(argvGet('project-number'), 10);
const COLUMNS_ARG = argvGet('columns', '');
const ADD_LABEL = argvGet('label');
const PER_PAGE = parseInt(argvGet('per-page', '100'), 10);
const DRY = process.argv.includes('--dry-run');

if (!OWNER || !PROJECT_NUMBER || !COLUMNS_ARG || !ADD_LABEL) {
  console.error('Usage: --owner <owner> --project-number <n> --columns "In review,Ready" --label "in-review" [--dry-run]');
  process.exit(1);
}

const GH_TOKEN = process.env.GH_TOKEN || process.env.GITHUB_TOKEN;
if (!GH_TOKEN) {
  console.error('Set GH_TOKEN (PAT) in environment with repo scope.');
  process.exit(1);
}

const COLUMNS = COLUMNS_ARG.split(',').map(s => s.trim()).filter(Boolean);
const GRAPHQL = 'https://api.github.com/graphql';
const REST = 'https://api.github.com';

const query = `
query($owner:String!, $projectNumber:Int!, $itemsFirst:Int!, $after:String) {
  user(login:$owner) {
    projectV2(number:$projectNumber) {
      id
      title
      items(first:$itemsFirst, after:$after) {
        nodes {
          id
          content {
            __typename
            ... on Issue {
              number
              url
              repository { name owner { login } }
            }
          }
          fieldValues(first:20) {
            nodes {
              __typename
              ... on ProjectV2ItemFieldSingleSelectValue {
                name
                field { name }
              }
              ... on ProjectV2FieldCommon {
                name
              }
            }
          }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
  organization(login:$owner) {
    projectV2(number:$projectNumber) {
      id
      title
      items(first:$itemsFirst, after:$after) {
        nodes {
          id
          content {
            __typename
            ... on Issue {
              number
              url
              repository { name owner { login } }
            }
          }
          fieldValues(first:20) {
            nodes {
              __typename
              ... on ProjectV2ItemFieldSingleSelectValue {
                name
                field { name }
              }
              ... on ProjectV2FieldCommon {
                name
              }
            }
          }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
`;

async function graphqlFetch(variables) {
  const res = await fetch(GRAPHQL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `bearer ${GH_TOKEN}`,
      Accept: 'application/vnd.github.v3+json',
    },
    body: JSON.stringify({ query, variables }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`GraphQL HTTP ${res.status}: ${text}`);
  }
  const json = await res.json();
  if (json.errors) throw new Error('GraphQL errors: ' + JSON.stringify(json.errors));
  return json.data;
}

async function addLabelToIssue(owner, repo, number, label) {
  const url = `${REST}/repos/${owner}/${repo}/issues/${number}/labels`;
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      Authorization: `bearer ${GH_TOKEN}`,
      'Content-Type': 'application/json',
      Accept: 'application/vnd.github.v3+json',
    },
    body: JSON.stringify([label]),
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`Failed to add label ${label} to ${owner}/${repo}#${number}: ${res.status} ${txt}`);
  }
  return res.json();
}

(async () => {
  try {
    let after = null;
    const matches = [];

    while (true) {
      const data = await graphqlFetch({ owner: OWNER, projectNumber: PROJECT_NUMBER, itemsFirst: PER_PAGE, after });
      const userProject = data?.user?.projectV2;
      const orgProject = data?.organization?.projectV2;
      const project = userProject || orgProject;
      if (!project) {
        throw new Error('Project not found: check owner and project number, and token permissions.');
      }

      const nodes = project.items.nodes;
      for (const node of nodes) {
        const fv = node.fieldValues?.nodes || [];
        // find single-select field values' names
        const singleSelectNames = fv
          .filter(n => n.__typename === 'ProjectV2ItemFieldSingleSelectValue' && n.name)
          .map(n => n.name);

        // if any of the field values matches one of COLUMNS, we consider this a match
        const matched = singleSelectNames.some(name => COLUMNS.includes(name));
        if (matched && node.content && node.content.__typename === 'Issue') {
          const issue = node.content;
          const repoOwner = issue.repository.owner.login;
          const repoName = issue.repository.name;
          matches.push({ owner: repoOwner, repo: repoName, number: issue.number, url: issue.url, columnValues: singleSelectNames });
        }
      }

      const pageInfo = project.items.pageInfo;
      if (pageInfo.hasNextPage) {
        after = pageInfo.endCursor;
      } else {
        break;
      }
    }

    console.log(`Found ${matches.length} issue(s) in columns: ${COLUMNS.join(', ')}`);
    for (const m of matches) {
      console.log(`- ${m.owner}/${m.repo}#${m.number} (columns: ${m.columnValues.join(', ')})`);
    }

    if (DRY) {
      console.log('Dry run mode - no labels will be applied.');
      process.exit(0);
    }

    for (const m of matches) {
      try {
        console.log(`Adding label '${ADD_LABEL}' to ${m.owner}/${m.repo}#${m.number}...`);
        await addLabelToIssue(m.owner, m.repo, m.number, ADD_LABEL);
        console.log('  OK');
      } catch (err) {
        console.error('  ERROR:', err.message || err);
      }
    }

    console.log('Done.');
    process.exit(0);
  } catch (err) {
    console.error('Fatal error:', err && (err.stack || err.message || String(err)));
    process.exit(2);
  }
})();