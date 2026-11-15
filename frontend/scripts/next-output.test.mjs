import assert from 'node:assert/strict';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import nextConfigLoader from 'next/dist/server/config.js';
import nextConstants from 'next/constants.js';

const { default: loadConfig } = nextConfigLoader;
const {
  PHASE_DEVELOPMENT_SERVER,
  PHASE_PRODUCTION_BUILD,
  PHASE_PRODUCTION_SERVER,
} = nextConstants;

// Exercise Next's real config loader: a production build must never clean the
// directory the running development server uses for its generated modules.
test('development and production outputs are separate, with matching build/start paths', async () => {
  const root = fileURLToPath(new URL('..', import.meta.url));
  const dev = await loadConfig(PHASE_DEVELOPMENT_SERVER, root);
  const build = await loadConfig(PHASE_PRODUCTION_BUILD, root);
  const start = await loadConfig(PHASE_PRODUCTION_SERVER, root);
  const devPath = path.resolve(root, dev.distDir);
  const buildPath = path.resolve(root, build.distDir);
  assert.notEqual(devPath, buildPath, 'next build can overwrite the running development server');
  assert.ok(!devPath.startsWith(`${buildPath}${path.sep}`), 'build cleanup would remove development output');
  assert.ok(!buildPath.startsWith(`${devPath}${path.sep}`), 'development cleanup would remove production output');
  assert.equal(start.distDir, build.distDir, 'next start must read the production build');
  assert.equal(build.distDir, '.next', 'the Docker image expects the production bundle in .next');
});
