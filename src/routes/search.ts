import { Router } from 'express';
import { z } from 'zod';
import { fetchGoogleNews } from '../services/googleNews.js';

export const search = Router();

const schema = z.object({
  query: z.string().min(1),
  maxResults: z.number().int().min(1).max(50).optional(),
  days: z.number().int().min(1).max(30).optional(),
});

search.post('/', async (req, res) => {
  const parsed = schema.safeParse(req.body);
  if (!parsed.success) return res.status(400).json(parsed.error.flatten());
  const { query, maxResults, days } = parsed.data;
  const items = await fetchGoogleNews(query, maxResults, days);
  res.json({ items });
});
