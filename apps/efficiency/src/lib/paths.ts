import { pathToFileURL } from 'node:url';

/**
 * Resolve a file in `src/data/` regardless of whether we run from source
 * (vitest) or from compiled `dist/` (Makefile CLIs): both layouts keep the
 * module exactly one directory deep under the package root.
 */
export function dataFile(name: string): string {
  const root = new URL('../../', import.meta.url);
  return new URL(`src/data/${name}`, root).pathname;
}

/** True when the calling module is the process entrypoint (node dist/x/y.js). */
export function isMainModule(metaUrl: string): boolean {
  return process.argv[1] !== undefined && metaUrl === pathToFileURL(process.argv[1]).href;
}
