import cron from 'node-cron';
import { prisma } from './db.js';
import { fetchGoogleNews } from './services/googleNews.js';
import { analyzeText } from './services/analyzer.js';
import { config } from './config.js';
import { logger } from './logger.js';

export function startScheduler() {
  // Every day at 06:30 local time
  cron.schedule('30 6 * * *', async () => {
    logger.info('Scheduled refresh start');
    const campaigns = await prisma.campaign.findMany();
    for (const c of campaigns) {
      try {
        const news = await fetchGoogleNews(c.query);
        for (const n of news) {
          try {
            const analysis = await analyzeText(`${n.title}. ${n.snippet ?? ''}`, config.openaiApiKey);
            await prisma.article.create({
              data: {
                campaignId: c.id,
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
          } catch {}
        }
      } catch (e) {
        logger.error({ err: e, campaign: c.id }, 'Scheduled refresh failed');
      }
    }
    logger.info('Scheduled refresh complete');
  }, { timezone: config.timezone });
}
