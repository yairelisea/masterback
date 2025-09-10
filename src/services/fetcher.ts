import axios from 'axios';
import * as cheerio from 'cheerio';

export type LinkMeta = {
  url: string;
  title?: string;
  description?: string;
  imageUrl?: string;
  siteName?: string;
};

export async function fetchLinkMeta(url: string): Promise<LinkMeta> {
  const res = await axios.get(url, { timeout: 15000, headers: { 'User-Agent': 'BBXBot/1.0 (+https://example.com)' } });
  const html = res.data as string;
  const $ = cheerio.load(html);
  const og = (prop: string) => $(`meta[property="og:${prop}"]`).attr('content') || $(`meta[name="og:${prop}"]`).attr('content');
  const tw = (prop: string) => $(`meta[name="twitter:${prop}"]`).attr('content');
  const meta = (name: string) => $(`meta[name="${name}"]`).attr('content');

  const title = og('title') || $('title').text() || tw('title');
  const description = og('description') || meta('description') || tw('description');
  const imageUrl = og('image') || tw('image');
  const siteName = og('site_name');

  return { url, title, description, imageUrl, siteName };
}
