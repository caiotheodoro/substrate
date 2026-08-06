import { expect } from 'vitest';
import { serializeGolden, loadGolden, goldenDigest } from '../replay/golden';

declare module 'vitest' {
  interface Assertion<T = any> {
    toMatchGoldenRun(goldenPath: string): T;
    toMatchGoldenString(expected: string): T;
  }
  interface AsymmetricMatchersContaining {
    toMatchGoldenRun(goldenPath: string): unknown;
    toMatchGoldenString(expected: string): unknown;
  }
}

expect.extend({
  toMatchGoldenRun(received: unknown, goldenPath: string) {
    const actual = serializeGolden(received as any);
    let expected: string;
    try {
      expected = loadGolden(goldenPath);
    } catch (e) {
      return {
        pass: false,
        message: () => `golden file not readable: ${goldenPath}: ${(e as Error).message}`,
      };
    }
    if (actual === expected) {
      return { pass: true, message: () => 'golden run matches byte-identically' };
    }
    const [aDigest, eDigest] = [goldenDigest(actual), goldenDigest(expected)];
    return {
      pass: false,
      message: () =>
        `golden run diverged (actual ${aDigest} vs golden ${eDigest}) at ${goldenPath}. ` +
        `first differing line:\n  golden: ${firstDiff(expected, actual) ?? '(none)'}\n  actual: ${firstDiff(actual, expected) ?? '(none)'}`,
    };
  },
  toMatchGoldenString(received: unknown, expected: string) {
    const actual = serializeGolden(received as any);
    return {
      pass: actual === expected,
      message: () =>
        `expected golden string to match byte-identically\n  golden: ${expected.slice(0, 200)}\n  actual: ${actual.slice(0, 200)}`,
    };
  },
});

function firstDiff(a: string, b: string): string | null {
  const al = a.split('\n');
  const bl = b.split('\n');
  const n = Math.max(al.length, bl.length);
  for (let i = 0; i < n; i++) {
    if (al[i] !== bl[i]) return `line ${i + 1}: ${bl[i] ?? '(missing)'}`;
  }
  return null;
}
