import { mkdirSync, writeFileSync } from 'node:fs';
import { runGoldenReplayBench } from '../bench/golden-bench';
import { suiteSamples } from '../bench/gated-suite';
import { runGateBench, paretoBlownByEscape, compareAtEscape } from '../bench/gated-decision';
import { runAllHavoc } from '../bench/havoc';
import { buildParetoPlot, writeBenchOutput } from '../bench/reporter';

const outDir = new URL('../../bench/out', import.meta.url).pathname;
mkdirSync(outDir, { recursive: true });

const golden = await runGoldenReplayBench();
console.log(`golden replay: ${golden.digest} (${golden.cases.length} cases)`);

const samples = suiteSamples();
const rows = runGateBench(samples);
const frontier = paretoBlownByEscape(rows);
const atEscape = compareAtEscape(samples, 0.6);
console.log(
  `gated-decision @escape≈${atEscape.targetEscape}: gate blown=${atEscape.gate.blownRate.toFixed(3)} vs guardrails-only=${atEscape.guardrailsOnly.blownRate.toFixed(3)} → gateWins=${atEscape.gateWins}`,
);
const plot = buildParetoPlot(rows, 'gated-decision Pareto: blown-outcome rate vs escape rate', frontier);
const written = writeBenchOutput(outDir, plot);
console.log(`wrote ${written.json}, ${written.svg}, ${written.png}`);

const havoc = await runAllHavoc();
for (const h of havoc) {
  console.log(`havoc ${h.scenario}: ${h.passed ? 'PASS' : 'FAIL'} ${JSON.stringify(h.detail)}`);
}

const summary = {
  golden,
  gatedDecision: {
    cases: samples.length,
    frontier: frontier.length,
    gateWins: atEscape.gateWins,
    gateBlownRate: atEscape.gate.blownRate,
    guardrailBlownRate: atEscape.guardrailsOnly.blownRate,
  },
  havoc: havoc.map((h) => ({ scenario: h.scenario, passed: h.passed })),
};
writeFileSync(`${outDir}/summary.json`, JSON.stringify(summary, null, 2) + '\n', 'utf8');
console.log('bench complete → bench/out/');
