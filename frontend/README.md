# Frontend Source

The authoritative Node.js manifest, lockfile, Vite configuration, and npm scripts live in the project root.

Use **Node 24.22.0 and npm 11.19.1**, the npm bundled with that Node release.

The root `.nvmrc` and `.node-version` contain the same exact Node pin as
`package.json`. Select it with your version manager (for example, `nvm install`
then `nvm use`), or add an official extracted Node distribution to the current
shell's PATH. Windows nvm users can run `nvm install 24.22.0` and
`nvm use 24.22.0`. Do not upgrade npm independently or use a floating `lts/*`
version for verification. A mismatched environment fails before install/build.

Run frontend commands from the project root:

```bash
node frontend/scripts/check-toolchain.mjs
npm ci --ignore-scripts --no-audit --no-fund
npm run verify:frontend
```

`verify:frontend` runs toolchain fixtures, architecture/API/layer/cycle checks,
all frontend unit tests, isolated E2E (including its production build), and a
production build. E2E needs the project's Python dependencies plus pytest and
Playwright Chromium. Install the browser with `npx playwright install chromium`;
Linux CI uses `--with-deps`. CI reads `.nvmrc` and runs the same commands on
Windows and Linux; it never uses a production database.

For individual development checks:

```bash
npm run test:unit
npm run test:e2e
npm run build
```

Do not create a second `package.json`, lockfile, or Vite configuration under this directory.

`engine-strict=true` and npm's `devEngines` also protect `npm ci --ignore-scripts`.
The dependency-free checker validates the pins, lockfile root engines and the
actual Node/npm binaries; it is invoked by build/test and shell release entries.
Use it before any dependency installation in external pipelines. Do not use
`--force`, disable engine checks or skip the checker to work around a mismatch.

Production frontend builders must select this same toolchain before running
`deploy.sh`, `scripts/build.sh` or `scripts/publish-frontend.sh`. A code-only
backend release does not require Node and does not publish frontend resources.
This toolchain change itself does not authorize a production release or change
the deployment allowlists, write fences, backup or rollback process.

To change the pinned release, update both version files, `engines`,
`packageManager`, `devEngines` and only the root `engines` in the lockfile;
repeat clean `npm ci` and `verify:frontend` with that exact distribution.
Application dependency upgrades require a separate reviewed change.
