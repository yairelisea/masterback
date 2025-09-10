import { Router } from 'express';
import { z } from 'zod';
import { prisma } from '../db.js';
import { fetchGoogleNews } from '../services/googleNews.js';
import { analyzeText } from '../services/analyzer.js';
import { config } from '../config.js';

export const campaigns = Router();

const createSchema = z.object({
  name: z.string().min(2),
  query: z.string().min(1),
  socials: z.array(z.string().url()).optional().default([]),
});

campaigns.get('/', async (req, res) => {
  const { q, page = '1', limit = '10' } = req.query as Record<string,string>;
  const p = Math.max(1, parseInt(page));
  const l = Math.min(100, Math.max(1, parseInt(limit)));
  const where = q ? { OR: [{ name: { contains: q } }, { query: { contains: q } }] } : {};
  const [items, total] = await Promise.all([
    prisma.campaign.findMany({ where, skip: (p-1)*l, take: l, orderBy: { createdAt: 'desc' } }),
    prisma.campaign.count({ where }),
  ]);
  res.json({ items, total, page: p, limit: l });
});

campaigns.post('/', async (req, res) => {
  const parsed = createSchema.safeParse(req.body);
  if (!parsed.success) return res.status(400).json(parsed.error.flatten());
  const { name, query, socials } = parsed.data;
  const created = await prisma.campaign.create({ data: { name, query } });

  // fetch news
  const news = await fetchGoogleNews(query);
  for (const n of news) {
    try {
      const analysis = await analyzeText(`${n.title}. ${n.snippet ?? ''}`, config.openaiApiKey);
      await prisma.article.create({
        data: {
          campaignId: created.id,
          source: n.source,
          title: n.title,
          url: n.url,
          imageUrl: n.imageUrl,
          snippet: n.snippet,
          publishedAt: n.publishedAt,
          sentiment: analysis.sentiment,
          topics: analysis.topics,
          summary: analysis.summary,
          raw: n as any,
        }
      });
    } catch (e) {
      // ignore duplicates / errors
    }
  }

  // add socials as placeholder links
  for (const url of socials ?? []) {
    try {
      await prisma.socialLink.create({ data: { campaignId: created.id, url } });
    } catch {}
  }

  const full = await prisma.campaign.findUnique({
    where: { id: created.id },
    include: { articles: true, socials: true },
  });
  res.status(201).json(full);
});

campaigns.get('/:id', async (req, res) => {
  const { id } = req.params;
  const item = await prisma.campaign.findUnique({
    where: { id },
    include: { articles: { orderBy: { createdAt: 'desc' } }, socials: true },
  });
  if (!item) return res.status(404).json({ error: 'Not found' });
  res.json(item);
});

campaigns.post('/:id/refresh', async (req, res) => {
  const { id } = req.params;
  const item = await prisma.campaign.findUnique({ where: { id } });
  if (!item) return res.status(404).json({ error: 'Not found' });
  const news = await fetchGoogleNews(item.query);
  let added = 0;
  for (const n of news) {
    try {
      const analysis = await analyzeText(`${n.title}. ${n.snippet ?? ''}`, config.openaiApiKey);
      await prisma.article.create({
        data: {
          campaignId: id,
          source: n.source,
          title: n.title,
          url: n.url,
          imageUrl: n.imageUrl,
          snippet: n.snippet,
          publishedAt: n.publishedAt,
          sentiment: analysis.sentiment,
          topics: analysis.topics,
          summary: analysis.summary,
          raw: n as any,
        }
      });
      added++;
    } catch {}
  }
  res.json({ ok: true, added });
});
