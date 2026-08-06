// ESM loader hook: resolves extensionless relative specifiers (repo TS
// convention) so compiled dist CLIs can import workspace packages whose
// sources are extensionless (e.g. @substrate/substrate). Used as:
//   node --loader apps/03-efficiency/scripts/esm-loader.mjs dist/...js
export async function resolve(specifier, context, nextResolve) {
  if (typeof specifier === 'string' && specifier.startsWith('.')) {
    for (const candidate of [specifier, `${specifier}.js`, `${specifier}.ts`, `${specifier}/index.js`, `${specifier}/index.ts`]) {
      try {
        return await nextResolve(candidate, context);
      } catch {
        // try next candidate
      }
    }
  }
  return nextResolve(specifier, context);
}
