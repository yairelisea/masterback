import Parser from 'rss-parser';
import { config } from '../config.js';
import type { NewsItem } from '../utils/types.js';

const parser = new Parser({
  customFields: {
    item: [
      ['source', 'source'],
      ['pubDate', 'pubDate'],
      ['link', 'link'],
      ['title', 'title'],
      ['contentSnippet', 'contentSnippet'],
      ['enclosure', 'enclosure'],
    ],
  },
});

function buildRssUrl(query: string, days: number) {
  const q = encodeURIComponent(`${query} when:${days}d`);
  const url = `https://news.google.com/rss/search?q=${q}&hl=es-419&gl=MX&ceid=MX:es-419`;
  return url;
}

export async function fetchGoogleNews(query: string, maxResults = config.newsMaxResults, days = config.defaultNewsWindowDays): Promise<NewsItem[]> {
  const feedUrl = buildRssUrl(query, days);
  const feed = await parser.parseURL(feedUrl);
  const items: NewsItem[] = [];
  for (const it of feed.items.slice(0, maxResults)) {
    const src = (it as any).source?.title ?? 'Google News';
    const item: NewsItem = {
      source: src,
      title: it.title ?? '',
      url: it.link ?? '',
      imageUrl: (it as any).enclosure?.url,
      snippet: it.contentSnippet ?? '',
      publishedAt: it.pubDate ? new Date(it.pubDate) : undefined,
    };
    items.push(item);
  }
  return items;
}
