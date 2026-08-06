export const up = (pgm) => {
  pgm.createTable('runs', {
    id: { type: 'text', primaryKey: true },
    task: { type: 'text', notNull: true },
    status: { type: 'text', notNull: true, default: 'running' },
    reason: { type: 'text' },
    max_turns: { type: 'integer', notNull: true, default: 8 },
    started_at: { type: 'timestamptz', notNull: true },
    ended_at: { type: 'timestamptz' },
    seq: { type: 'integer', notNull: true, default: -1 },
  });
  pgm.createTable('events', {
    run_id: { type: 'text', notNull: true },
    seq: { type: 'integer', notNull: true },
    family: { type: 'text', notNull: true },
    kind: { type: 'text' },
    payload: { type: 'jsonb' },
    tool_call_id: { type: 'text' },
    result: { type: 'jsonb' },
    ts: { type: 'timestamptz', notNull: true },
    idempotency_key: { type: 'text', notNull: true },
    chain_hash: { type: 'text', notNull: true },
  });
  pgm.addConstraint('events', 'events_pk', { primaryKey: ['run_id', 'seq'] });
  pgm.addConstraint('events', 'events_idem_unique', { unique: ['run_id', 'idempotency_key'] });
  pgm.createIndex('events', ['run_id', 'seq']);
  pgm.createTable('decisions', {
    decision_id: { type: 'text', primaryKey: true },
    turn_id: { type: 'text', notNull: true },
    action: { type: 'text', notNull: true },
    confidence_features: { type: 'jsonb', notNull: true },
    verdict: { type: 'text', notNull: true },
    outcome: { type: 'boolean' },
    confirmed_at: { type: 'timestamptz' },
  });
  pgm.createTable('pending_actions', {
    id: { type: 'text', primaryKey: true },
    run_id: { type: 'text', notNull: true },
    turn_id: { type: 'text', notNull: true },
    kind: { type: 'text', notNull: true },
    prompt: { type: 'text', notNull: true },
    schema: { type: 'jsonb', notNull: true, default: '{}' },
    answer: { type: 'jsonb' },
    status: { type: 'text', notNull: true, default: 'pending' },
    created_at: { type: 'timestamptz', notNull: true },
    resolved_at: { type: 'timestamptz' },
    resolved_by: { type: 'text' },
  });
  pgm.createIndex('pending_actions', ['run_id', 'status']);
  pgm.createTable('escalations', {
    escalation_id: { type: 'text', primaryKey: true },
    run_id: { type: 'text' },
    decision_id: { type: 'text', notNull: true },
    proposal: { type: 'jsonb', notNull: true },
    confidence: { type: 'double precision', notNull: true },
    explain: { type: 'jsonb', notNull: true, default: '{}' },
    verdict: { type: 'text', notNull: true, default: 'pending' },
    created_at: { type: 'timestamptz', notNull: true },
    resolved_at: { type: 'timestamptz' },
    decided_by: { type: 'text' },
  });
  pgm.createIndex('escalations', ['verdict', 'created_at']);
  pgm.createTable('sandbox_leases', {
    id: { type: 'text', primaryKey: true },
    container_id: { type: 'text', notNull: true },
    image: { type: 'text', notNull: true },
    lease_ms: { type: 'integer', notNull: true },
    expires_at: { type: 'timestamptz', notNull: true },
    updated_at: { type: 'timestamptz', notNull: true },
    status: { type: 'text', notNull: true, default: 'pending' },
  });
  pgm.createIndex('sandbox_leases', ['expires_at']);
  pgm.createTable('thresholds', {
    task_type: { type: 'text', primaryKey: true },
    execute_threshold: { type: 'double precision', notNull: true },
    reject_threshold: { type: 'double precision', notNull: true },
    note: { type: 'text' },
  });
  pgm.createTable('cost_ledger', {
    decision_id: { type: 'text', notNull: true },
    step_idx: { type: 'integer', notNull: true },
    model: { type: 'text', notNull: true },
    provider: { type: 'text', notNull: true },
    quantization: { type: 'text' },
    input_tokens: { type: 'integer', notNull: true, default: 0 },
    cached_input_tokens: { type: 'integer', notNull: true, default: 0 },
    output_tokens: { type: 'integer', notNull: true, default: 0 },
    cache_event: { type: 'text', notNull: true },
    latency_ms: { type: 'double precision', notNull: true, default: 0 },
    prompt_fingerprint: { type: 'text' },
    quality_signal: { type: 'double precision' },
    ts: { type: 'timestamptz', notNull: true },
  });
  pgm.addConstraint('cost_ledger', 'cost_ledger_pk', { primaryKey: ['decision_id', 'step_idx'] });
};

export const down = (pgm) => {
  pgm.dropTable('cost_ledger');
  pgm.dropTable('thresholds');
  pgm.dropTable('sandbox_leases');
  pgm.dropTable('escalations');
  pgm.dropTable('pending_actions');
  pgm.dropTable('decisions');
  pgm.dropTable('events');
  pgm.dropTable('runs');
};
