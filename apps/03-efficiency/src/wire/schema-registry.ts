import { RegistryEntrySchema, type RegistryEntry } from '@substrate/substrate';

/**
 * A-E-19 schema-registry — versioned wire schemas (C7).
 *
 * Every payload crossing the wire is a RegistryEntry: kind + version +
 * JSON Schema (draft 2020-12). The registry resolves `kind@version`
 * (or `kind@latest`) and validates payloads against a minimal JSON
 * Schema subset (type / required / properties / items / enum / const /
 * additionalProperties) — enough for the wire contracts, no dependency.
 */

export interface RegistryEntryData {
  kind: string;
  version: string;
  schema: Record<string, unknown>;
}

const BUILTINS: RegistryEntryData[] = [
  {
    kind: 'tool-schemas',
    version: '1.0.0',
    schema: {
      type: 'object',
      required: ['tools'],
      properties: {
        tools: { type: 'array', items: { type: 'object', required: ['name', 'parameters'] } },
        version: { type: 'string' },
      },
    },
  },
  {
    kind: 'render_ui',
    version: '1.0.0',
    schema: {
      type: 'object',
      required: ['type', 'props', 'children'],
      properties: {
        type: { type: 'string' },
        props: { type: 'object' },
        children: { type: 'array' },
      },
      additionalProperties: true,
    },
  },
  {
    kind: 'memory',
    version: '1.0.0',
    schema: {
      type: 'object',
      required: ['entries'],
      properties: {
        entries: { type: 'array', items: { type: 'string' } },
        owner: { type: 'string' },
      },
    },
  },
];

export class SchemaRegistry {
  private readonly entries = new Map<string, RegistryEntryData>();

  constructor(entries: RegistryEntryData[] = BUILTINS) {
    for (const entry of entries) this.register(entry);
  }

  register(entry: RegistryEntryData): void {
    RegistryEntrySchema.parse({
      kind: entry.kind,
      version: entry.version,
      schema: entry.schema,
    });
    this.entries.set(`${entry.kind}@${entry.version}`, entry);
  }

  resolve(kind: string, version = 'latest'): RegistryEntry | null {
    if (version === 'latest') {
      const versions = [...this.entries.keys()]
        .filter((k) => k.startsWith(`${kind}@`))
        .sort();
      if (versions.length === 0) return null;
      const latest = versions[versions.length - 1]!;
      return this.toEntry(this.entries.get(latest)!);
    }
    const entry = this.entries.get(`${kind}@${version}`);
    return entry === undefined ? null : this.toEntry(entry);
  }

  versions(kind: string): string[] {
    return [...this.entries.keys()]
      .filter((k) => k.startsWith(`${kind}@`))
      .map((k) => k.slice(kind.length + 1))
      .sort();
  }

  /** Validate a payload against a resolved registry entry's JSON Schema. */
  validate(kind: string, payload: unknown, version = 'latest'): { ok: boolean; errors: string[] } {
    const entry = this.resolve(kind, version);
    if (entry === null) return { ok: false, errors: [`unknown kind ${kind}@${version}`] };
    return validateJsonSchema(entry.schema, payload);
  }

  private toEntry(data: RegistryEntryData): RegistryEntry {
    return { kind: data.kind, version: data.version, schema: data.schema };
  }
}

/** Minimal JSON Schema (subset of draft 2020-12) validator. */
export function validateJsonSchema(
  schema: Record<string, unknown>,
  value: unknown,
): { ok: boolean; errors: string[] } {
  const errors: string[] = [];
  const walk = (s: Record<string, unknown>, v: unknown, path: string): void => {
    const type = s['type'];
    if (type !== undefined) {
      const types = Array.isArray(type) ? type : [type];
      const actual = typeOf(v);
      if (!types.includes(actual)) {
        errors.push(`${path}: expected ${String(type)}, got ${actual}`);
        return;
      }
    }
    if (s['const'] !== undefined && JSON.stringify(s['const']) !== JSON.stringify(v)) {
      errors.push(`${path}: const mismatch`);
      return;
    }
    if (Array.isArray(s['enum']) && !s['enum'].some((e) => JSON.stringify(e) === JSON.stringify(v))) {
      errors.push(`${path}: not in enum`);
      return;
    }
    if (s['required'] !== undefined) {
      if (v === null || typeof v !== 'object' || Array.isArray(v)) {
        errors.push(`${path}: required fields but value is ${typeOf(v)}`);
        return;
      }
      for (const field of s['required'] as string[]) {
        if (!(field in (v as Record<string, unknown>))) {
          errors.push(`${path}: missing required "${field}"`);
        }
      }
    }
    if (s['properties'] !== undefined && v !== null && typeof v === 'object' && !Array.isArray(v)) {
      const props = s['properties'] as Record<string, Record<string, unknown>>;
      for (const [key, sub] of Object.entries(props)) {
        if (key in (v as Record<string, unknown>)) {
          walk(sub, (v as Record<string, unknown>)[key], `${path}/${key}`);
        }
      }
    }
    if (s['items'] !== undefined && Array.isArray(v)) {
      const itemSchema = s['items'] as Record<string, unknown>;
      v.forEach((item, i) => walk(itemSchema, item, `${path}/${i}`));
    }
  };
  walk(schema, value, '');
  return { ok: errors.length === 0, errors };
}

function typeOf(v: unknown): string {
  if (v === null) return 'null';
  if (Array.isArray(v)) return 'array';
  return typeof v;
}
