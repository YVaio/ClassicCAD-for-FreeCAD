#!/usr/bin/env node
/**
 * scripts/update-readme.js
 *
 * Fetches Project (v2) items and injects a markdown list into a README between markers.
 *
 * Usage examples:
 *  node scripts/update-readme.js --owner YVaio --project-number 1 --readme README.md
 *  node scripts/update-readme.js --owner my-org --project-number 2 --readme README.md --repo-name my-repo
 *  node scripts/update-readme.js --owner YVaio --project-number 1 --readme README.md --commit
 *
 * Environment:
 *  - Requires GH_TOKEN (or GITHUB_TOKEN) to be present in the environment.
 *    For repo-scoped projects the built-in GITHUB_TOKEN is usually sufficient.
 *    For user/org projects you'll likely need a PAT stored as a repo secret (PROJECT_TOKEN) and passed in as GH_TOKEN.
 *
 * Notes:
 *  - No external Node packages required (uses global fetch available in Node 18+).
 *  - By default writes README but does NOT commit. Add --commit to attempt a git commit & push.
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
const PROJECT_NUMBER = parseInt(argvGet('project-number'), 10);
const REPO_NAME = argvGet('repo-name'); // optional: when the project is a repository project
const README = argvGet('readme', 'README.md');
const START_MARKER = argvGet('start-marker', '<!-- PROJECT_ISSUES:START -->');
const END_MARKER = argvGet('end-marker', '<!-- PROJECT_ISSUES:END -->');
const PER_PAGE = parseInt(argvGet('per-page', '100'), 10);
const DO_COMMIT = process.argv.includes('--commit');

if (!OWNER || !PROJECT_NUMBER) {
  console.error('Missing required --owner or --project-number argument.');
  process.exit(1);
}

const GH_TOKEN = process.env.GH_TOKEN || process.env.GITHUB_TOKEN;
if (!GH_TOKEN) {
  console.error('Missing GH_TOKEN or GITHUB_TOKEN environment variable. Set a repo secret PROJECT_TOKEN and map it to GH_TOKEN in the workflow if needed.');
  process.exit(1);
}

const GRAPHQL = 'https://api.github.com/graphql';

// Build GraphQL query depending on whether --repo-name is provided (repository project) or not
function buildQuery(forRepo) {
  const itemsFragment = `
    items(first:$perPage, after:$after) {
      nodes {
        id
        content {
          __typename
          ... on Issue {
            number
            title
            url
            state
            labels(first:10) { nodes { name } }
          }
          ... on DraftIssue {
            title
            body
          }
        }
      }
      pageInfo { hasNextPage endCursor }
    }
  `;

  if (forRepo) {
    return `
      query($owner:String!, $repoName:String!, $projectNumber:Int!, $perPage:Int!, $after:String) {
        repository(owner:$owner, name:$repoName) {
          projectV2(number:$projectNumber) {
            id title url ${itemsFragment}
          }
        }
      }
    `;
  } else {
    return `
      query($owner:String!, $projectNumber:Int!, $perPage:Int!, $after:String) {
        user(login:$owner) {
          projectV2(number:$projectNumber) { id title url ${itemsFragment} }
        }
        organization(login:$owner) {
          projectV2(number:$projectNumber) { id title url ${itemsFragment} }
        }
      }
    `;
  }
}

async function graphqlFetch(query, variables) {
  const res = await globalThis.fetch(GRAPHQL, {
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
    throw new Error(`GraphQL HTTP error ${res.status}: ${text}`);
  }
  const json = await res.json();
  if (json.errors) {
    throw new Error('GraphQL errors: ' + JSON.stringify(json.errors, null, 2));
  }
  return json.data;
}

async function fetchAllItems() {
  const forRepo = !!REPO_NAME;
  const query = buildQuery(forRepo);

  let allNodes = [];
  let after = null;
  let page = 0;

  while (true) {
    page++;
    const variables = forRepo
      ? { owner: OWNER, repoName: REPO_NAME, projectNumber: PROJECT_NUMBER, perPage: PER_PAGE, after }
      : { owner: OWNER, projectNumber: PROJECT_NUMBER, perPage: PER_PAGE, after };

    const data = await graphqlFetch(query, variables);

    let project = null;
    if (forRepo) {
      project = data?.repository?.projectV2;
    } else {
      project = data?.user?.projectV2 || data?.organization?.projectV2;
    }

    if (!project) {
      throw new Error(`Project not found. Verify owner="${OWNER}"${forRepo ? ` repoName="${REPO_NAME}"` : ''} and project number=${PROJECT_NUMBER}, and token permissions.`);
    }

    const items = project.items?.nodes || [];
    allNodes = allNodes.concat(items);

    const pageInfo = project.items?.pageInfo;
    if (pageInfo && pageInfo.hasNextPage) {
      after = pageInfo.endCursor;
      // loop again
    } else {
      break;
    }
  }

  return { nodes: allNodes, title: (REPO_NAME ? `${OWNER}/${REPO_NAME} project` : projectTitleFromNodes(allNodes)) };
}

function projectTitleFromNodes(nodes) {
  // fallback title
  return `Project ${PROJECT_NUMBER}`;
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
    console.log('Fetching project items...');
    const forRepo = !!REPO_NAME;
    const query = buildQuery(forRepo);

    // We'll fetch project metadata + pages ourselves (we use the same query in the loop)
    let allNodes = [];
    let after = null;
    let projectTitle = null;
    while (true) {
      const variables = forRepo
        ? { owner: OWNER, repoName: REPO_NAME, projectNumber: PROJECT_NUMBER, perPage: PER_PAGE, after }
        : { owner: OWNER, projectNumber: PROJECT_NUMBER, perPage: PER_PAGE, after };

      const data = await graphqlFetch(query, variables);
      let project = null;
      if (forRepo) {
        project = data?.repository?.projectV2;
      } else {
        project = data?.user?.projectV2 || data?.organization?.projectV2;
      }

      if (!project) {
        throw new Error(`Project not found. Verify owner="${OWNER}"${forRepo ? ` repoName="${REPO_NAME}"` : ''} and project number=${PROJECT_NUMBER}, and token permissions.`);
      }

      projectTitle = project.title || projectTitle || `Project ${PROJECT_NUMBER}`;

      const items = project.items?.nodes || [];
      allNodes = allNodes.concat(items);

      const pageInfo = project.items?.pageInfo;
      if (pageInfo && pageInfo.hasNextPage) {
        after = pageInfo.endCursor;
      } else {
        break;
      }
    }

    console.log(`Fetched ${allNodes.length} items from project "${projectTitle}". Generating markdown...`);

    const header = `### Project: ${escapeMarkdown(projectTitle)}\n\nGenerated: ${new Date().toISOString()}\n\n`;
    const itemsMd = allNodes.map(formatItem).filter(Boolean);
    const body = header + (itemsMd.length ? itemsMd.join('\n') : '_No items found_') + '\n';

    const readmePath = path.resolve(process.cwd(), README);
    let readme = '';
    if (fs.existsSync(readmePath)) {
      readme = fs.readFileSync(readmePath, 'utf8');
    } else {
      console.warn(`README file not found at ${readmePath}, creating a new one.`);
    }

    const newBlock = `${START_MARKER}\n\n${body}\n${END_MARKER}`;

    let newReadme;
    if (readme.includes(START_MARKER) && readme.includes(END_MARKER)) {
      const before = readme.split(START_MARKER)[0];
      const after = readme.split(END_MARKER).slice(1).join(END_MARKER);
      newReadme = before + newBlock + after;
    } else {
      // append if no markers
      newReadme = readme + '\n\n' + newBlock + '\n';
    }

    if (newReadme === readme) {
      console.log('README unchanged. Nothing to commit.');
      process.exit(0);
    }

    fs.writeFileSync(readmePath, newReadme, 'utf8');
    console.log(`Updated ${README} with ${itemsMd.length} project items.`);

    if (DO_COMMIT) {
      try {
        console.log('Committing changes...');
        // configure git user
        execSync('git config user.name "github-actions[bot]"');
        execSync('git config user.email "41898282+github-actions[bot]@users.noreply.github.com"');

        // Stage and commit
        execSync(`git add ${escapeShellArg(README)}`);
        execSync(`git commit -m "ci: update README with Project items (automated)"`);

        // Push using token if available and GITHUB_REPOSITORY is set
        const repoFull = process.env.GITHUB_REPOSITORY; // e.g., owner/repo
        if (repoFull && GH_TOKEN) {
          const remoteWithToken = `https://x-access-token:${GH_TOKEN}@github.com/${repoFull}.git`;
          execSync(`git remote set-url origin ${remoteWithToken}`);
          // Push current branch
          execSync('git push --set-upstream origin HEAD');
          console.log('Pushed commit to origin.');
        } else {
          // fallback: attempt a normal push
          execSync('git push');
          console.log('Pushed commit to origin (default auth).');
        }
      } catch (err) {
        console.error('Git commit/push failed:', err && (err.stdout || err.stderr || err.message) || err);
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