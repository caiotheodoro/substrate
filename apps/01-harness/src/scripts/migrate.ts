import { createPool, migrate } from '../db';

const pool = createPool();
try {
  await migrate(pool);
  console.log('migrations applied');
} finally {
  await pool.end();
}
