import { createWebApp } from '../api/web';

const port = Number(process.env.PORT ?? 8941);
const apiBase = process.env.HARNESS_API_BASE ?? 'http://localhost:8930';
createWebApp(apiBase).listen(port, () => console.log(`harness web (read-only) on :${port}`));
