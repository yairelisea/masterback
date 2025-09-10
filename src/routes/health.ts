import { Router } from 'express';
export const health = Router();
health.get('/', (_, res) => res.json({ ok: true, service: 'bbx-backend', ts: new Date().toISOString() }));
