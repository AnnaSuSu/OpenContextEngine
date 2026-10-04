# Publishing OpenContextEngine to npm

Package: `open-context-engine`. Release example: `0.1.2`. License: MIT.
Preparing an archive does not publish it or change GitHub repository visibility.

## Prepare and verify

1. Confirm the version in `package.json`, `package-lock.json`, and the MCP server agrees. Choose a new version if that version is already published.
2. Run `npm ci` and `npm test` from a clean checkout with the Python dependencies installed. MCP integration tests need local loopback sockets; verify they are not skipped.
3. Finalize the release README before packing: use the npm install command and remove pending-release notices. The release packer explicitly selects the English README in package metadata while retaining the Chinese translation; npm can otherwise select the translated file as its homepage. npm displays the README bundled with the release; later GitHub edits do not update it.
4. Build and inspect the archive:

```sh
mkdir -p .pilot-state/npm-release
node scripts/pack-release.mjs .pilot-state/npm-release
npm publish .pilot-state/npm-release/open-context-engine-0.1.2.tgz --dry-run --access public --registry https://registry.npmjs.org/
```

5. Confirm the archive contains `LICENSE` and runtime files, and excludes credentials, `.env`, `.npmrc`, caches, test fixtures, model weights, and evaluation datasets.
6. Install that exact archive into a temporary prefix outside the checkout. Check both CLI names, run `setup` and `doctor` with an isolated `OCE_CONFIG_HOME`, then connect through MCP and search a small fixture using configured model APIs. Do not include keys in the release report.
7. Record the archive's SHA-256 digest. Publish the verified archive, not a newly packed working tree.

## Publish when the release is approved

Confirm the repository is ready for public access separately. Check the intended npm account and current package availability:

```sh
npm login --registry https://registry.npmjs.org/
npm whoami --registry https://registry.npmjs.org/
npm view open-context-engine versions --json --registry https://registry.npmjs.org/
```

An E404 means no public package is visible; it does not reserve the name. Complete npm's authentication and any requested two-factor verification interactively. Never commit npm tokens or put them in the release report.

Only after approval, publish the verified archive:

```sh
npm publish .pilot-state/npm-release/open-context-engine-0.1.2.tgz --access public --registry https://registry.npmjs.org/
npm view open-context-engine@0.1.2 version dist.integrity --registry https://registry.npmjs.org/
```

Compare the registry integrity with the packed artifact, then verify a clean `npm install -g open-context-engine@0.1.2`. Check the README on the npm package page as well; correcting it later requires publishing a new version. Git pushes, repository visibility, and release tags are separate actions.

[Official npm publishing guide](https://docs.npmjs.com/creating-and-publishing-unscoped-public-packages/)
