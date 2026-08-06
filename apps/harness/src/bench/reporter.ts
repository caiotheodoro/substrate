import { deflateSync } from 'node:zlib';
import { writeFileSync } from 'node:fs';
import type { BenchRow } from './gated-decision';

export interface ParetoPlotData {
  title: string;
  rows: Array<{ escapeRate: number; blownRate: number; name: string; params: Record<string, number> }>;
  frontier: Array<{ escapeRate: number; blownRate: number; name: string }>;
  baselines: Array<{ name: string; escapeRate: number; blownRate: number }>;
}

export function buildParetoPlot(rows: BenchRow[], title: string, frontier: Array<{ escapeRate: number; blownRate: number; name: string }>): ParetoPlotData {
  return {
    title,
    rows: rows.map((r) => ({ escapeRate: r.escapeRate, blownRate: r.blownRate, name: r.name, params: r.params })),
    frontier,
    baselines: baselinePoints(rows),
  };
}

export function toJson(data: ParetoPlotData): string {
  return JSON.stringify(data, null, 2);
}

export function toSvg(data: ParetoPlotData): string {
  const w = 640;
  const h = 480;
  const pad = 48;
  const px = (v: number) => pad + v * (w - 2 * pad);
  const py = (v: number) => h - pad - v * (h - 2 * pad);
  const colors: Record<string, string> = {
    'gate-3state': '#1f77b4',
    'guardrails-only': '#d62728',
    'turn-boundary-hitl': '#2ca02c',
  };
  const points = data.rows.map(
    (r) => `<circle cx="${px(r.escapeRate).toFixed(1)}" cy="${py(r.blownRate).toFixed(1)}" r="2.5" fill="${colors[r.name] ?? '#999'}" opacity="0.7"><title>${r.name}</title></circle>`,
  );
  const frontier = data.frontier.map(
    (p) => `<circle cx="${px(p.escapeRate).toFixed(1)}" cy="${py(p.blownRate).toFixed(1)}" r="3" fill="#000"/>`,
  );
  const baselines = data.baselines.map(
    (b) => `<rect x="${(px(b.escapeRate) - 4).toFixed(1)}" y="${(py(b.blownRate) - 4).toFixed(1)}" width="8" height="8" fill="${colors[b.name] ?? '#000'}" stroke="#000"><title>${b.name}</title></rect>`,
  );
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
<text x="${pad}" y="24" font-size="16">${escapeXml(data.title)}</text>
${gridLines(w, h, pad)}
${baselines.join('\n')}
${points.join('\n')}
${frontier.join('\n')}
<text x="${pad}" y="${h - 16}" font-size="12">escape rate (decisions shipped without review)</text>
<text x="14" y="${h / 2}" font-size="12" transform="rotate(-90 14 ${h / 2})">blown-outcome rate</text>
</svg>`;
}

function gridLines(w: number, h: number, pad: number): string {
  const lines: string[] = [];
  for (let i = 0; i <= 10; i++) {
    const x = pad + (i / 10) * (w - 2 * pad);
    const y = h - pad - (i / 10) * (h - 2 * pad);
    lines.push(`<line x1="${x}" y1="${pad}" x2="${x}" y2="${h - pad}" stroke="#eee"/>`);
    lines.push(`<line x1="${pad}" y1="${y}" x2="${w - pad}" y2="${y}" stroke="#eee"/>`);
    lines.push(`<text x="${x - 8}" y="${h - pad + 14}" font-size="9">${(i / 10).toFixed(1)}</text>`);
    lines.push(`<text x="${pad - 26}" y="${y + 3}" font-size="9">${(i / 10).toFixed(1)}</text>`);
  }
  return lines.join('\n');
}

function escapeXml(s: string): string {
  return s.replace(/[<>&"]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' })[c]!);
}

export function toPng(data: ParetoPlotData): Buffer {
  const w = 640;
  const h = 480;
  const pixels = Buffer.alloc(w * h * 3);
  const svg = toSvg(data);
  void svg;
  const pad = 48;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const bg = (x + y) % 2 === 0 ? 250 : 248;
      const offset = (y * w + x) * 3;
      pixels[offset] = bg;
      pixels[offset + 1] = bg;
      pixels[offset + 2] = bg;
    }
  }
  for (let i = 0; i <= 10; i++) {
    const x = pad + (i / 10) * (w - 2 * pad);
    const y = h - pad - (i / 10) * (h - 2 * pad);
    for (let k = 0; k < 2; k++) {
      if (y + k < h && x + k < w) {
        const o = ((y + k) * w + x) * 3;
        pixels[o] = 220;
        pixels[o + 1] = 220;
        pixels[o + 2] = 220;
      }
    }
  }
  for (const p of data.frontier) {
    const x = Math.round(pad + p.escapeRate * (w - 2 * pad));
    const y = Math.round(h - pad - p.blownRate * (h - 2 * pad));
    fillDisc(pixels, w, h, x, y, 3, [20, 20, 20] as const);
  }
  for (const r of data.rows) {
    const color: [number, number, number] = r.name === 'gate-3state' ? [31, 119, 180] : r.name === 'guardrails-only' ? [214, 39, 40] : [44, 160, 44];
    const x = Math.round(pad + r.escapeRate * (w - 2 * pad));
    const y = Math.round(h - pad - r.blownRate * (h - 2 * pad));
    fillDisc(pixels, w, h, x, y, 2, color);
  }
  return encodePng(w, h, pixels);
}

function fillDisc(pixels: Buffer, w: number, h: number, cx: number, cy: number, r: number, rgb: [number, number, number]): void {
  for (let dy = -r; dy <= r; dy++) {
    for (let dx = -r; dx <= r; dx++) {
      if (dx * dx + dy * dy > r * r) continue;
      const x = cx + dx;
      const y = cy + dy;
      if (x < 0 || y < 0 || x >= w || y >= h) continue;
      const o = (y * w + x) * 3;
      pixels[o] = rgb[0];
      pixels[o + 1] = rgb[1];
      pixels[o + 2] = rgb[2];
    }
  }
}

function encodePng(width: number, height: number, rgba: Buffer): Buffer {
  const sig = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8;
  ihdr[9] = 2;
  const raw = Buffer.alloc((width * 3 + 1) * height);
  for (let y = 0; y < height; y++) {
    raw[y * (width * 3 + 1)] = 0;
    rgba.copy(raw, y * (width * 3 + 1) + 1, y * width * 3, (y + 1) * width * 3);
  }
  const idat = deflateSync(raw, { level: 9 });
  const ihdrChunk = chunk('IHDR', ihdr);
  const idatChunk = chunk('IDAT', idat);
  const iendChunk = chunk('IEND', Buffer.alloc(0));
  return Buffer.concat([sig, ihdrChunk, idatChunk, iendChunk]);
}

function chunk(type: string, data: Buffer): Buffer {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length, 0);
  const typeBuf = Buffer.from(type, 'ascii');
  const crcBuf = Buffer.alloc(4);
  crcBuf.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])) >>> 0, 0);
  return Buffer.concat([len, typeBuf, data, crcBuf]);
}

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(buf: Buffer): number {
  let crc = 0xffffffff;
  for (const byte of buf) crc = CRC_TABLE[(crc ^ byte) & 0xff]! ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

export function writeBenchOutput(outDir: string, data: ParetoPlotData): { json: string; svg: string; png: string } {
  const json = toJson(data);
  const svg = toSvg(data);
  const png = toPng(data);
  writeFileSync(`${outDir}/pareto.json`, json, 'utf8');
  writeFileSync(`${outDir}/pareto.svg`, svg, 'utf8');
  writeFileSync(`${outDir}/pareto.png`, png);
  return { json: `${outDir}/pareto.json`, svg: `${outDir}/pareto.svg`, png: `${outDir}/pareto.png` };
}

export function baselinePoints(rows: BenchRow[]): Array<{ name: string; escapeRate: number; blownRate: number }> {
  const picked = new Map<string, BenchRow>();
  for (const row of rows) {
    const cur = picked.get(row.name);
    if (!cur || row.blownRate < cur.blownRate) picked.set(row.name, row);
  }
  return [...picked.entries()].map(([name, r]) => ({ name, escapeRate: r.escapeRate, blownRate: r.blownRate }));
}

export function paretoFrontierOf(rows: BenchRow[]): Array<{ escapeRate: number; blownRate: number; name: string }> {
  const best = new Map<number, { blownRate: number; name: string }>();
  for (const row of rows) {
    const key = Math.round(row.escapeRate * 100) / 100;
    const cur = best.get(key);
    if (!cur || row.blownRate < cur.blownRate) best.set(key, { blownRate: row.blownRate, name: row.name });
  }
  return [...best.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([escapeRate, v]) => ({ escapeRate, blownRate: v.blownRate, name: v.name }));
}