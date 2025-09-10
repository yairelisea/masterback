import { Router } from 'express';
import { z } from 'zod';
import { prisma } from '../db.js';
import { fetchLinkMeta } from '../services/fetcher.js';
import { analyzeText } from '../services/analyzer.js';
import { config } from '../config.js';

export const links = Router();

const addSchema = z.object({
  campaignId: z.string().cuid(),
  urls: z.array(z.string().url()).min(1).max(50),
});

links.post('/add', async (req, res) => {
  const parsed = addSchema.safeParse(req.body);
  if (!parsed.success) return res.status(400).json(parsed.error.flatten());
  const { campaignId, urls } = parsed.data;
  const campaign = await prisma.campaign.findUnique({ where: { id: campaignId } });
  if (!campaign) return res.status(404).json({ error: 'Campaign not found' });

  const out: any[] = [];
  for (const url of urls) {
    try {
      const meta = await fetchLinkMeta(url);
      const text = `${meta.title ?? ''}. ${meta.description ?? ''}`.trim();
      const analysis = await analyzeText(text || url, config.openaiApiKey);
      const link = await prisma.socialLink.create({
        data: {
          campaignId,
          url,
          platform: meta.siteName,
          title: meta.title,
          description: meta.description,
          imageUrl: meta.imageUrl,
          sentiment: analysis.sentiment,
          summary: analysis.summary,
          raw: meta as any,
        }
      });
      out.push(link);
    } catch (e) {
      out.push({ url, error: 'failed' });
    }
  }
  res.json({ added: out.length, items: out });
});
