// searchAdapter.js
// Unified search service leveraging Google Programmable Search (Custom Search JSON API)
// and (optionally) Facebook search (stub). Provides a single entry point unifiedSearch.

const fetch = require('node-fetch');
const { google, facebook, defaults } = require('../config/searchConfig');

/**
 * Normalized search result shape
 * @typedef {Object} NormalizedResult
 * @property {string} source  - 'google' | 'facebook'
 * @property {string} title
 * @property {string} url
 * @property {string} snippet
 * @property {string} publishedAt - ISO date string
 */

/**
 * Perform Google Programmable Search.
 * @param {string} q
 * @param {Object} opts
 * @returns {Promise<NormalizedResult[]>}
 */
async function googleSearch(q, opts = {}) {
  if (!google.apiKey || !google.cx) {
    return [];
  }
  // Forzamos 20 resultados siempre (ignora google.pageSize)
  const params = new URLSearchParams({
    key: google.apiKey,
    cx: google.cx,
    q,
    num: '20', // fijo a 20
  });
  const url = `https://www.googleapis.com/customsearch/v1?${params.toString()}`;
  const json = await safeFetchJson(url, opts.timeoutMs || defaults.timeoutMs);
  if (!json || !json.items) return [];

  return json.items.map(it => {
    const metaDate = extractDateFromItem(it);
    return {
      source: 'google',
      title: it.title || it.htmlTitle || '',
      url: it.link || '',
      snippet: it.snippet || '',
      publishedAt: metaDate,
    };
  });
}

/**
 * Very small heuristic to extract a date from the search item.
 */
function extractDateFromItem(item) {
  const nowIso = new Date().toISOString();
  try {
    // Attempt common date fields inside pagemap.metatags[0]
    const meta = item.pagemap && Array.isArray(item.pagemap.metatags) && item.pagemap.metatags[0];
    if (meta) {
      const candidates = [
        meta['article:published_time'],
        meta['og:published_time'],
        meta['pubdate'],
        meta['date'],
        meta['dc.date'],
        meta['dc.date.issued'],
      ].filter(Boolean);
      for (const c of candidates) {
        const d = new Date(c);
        if (!isNaN(d.getTime())) return d.toISOString();
      }
    }
  } catch (e) {
    // ignore
  }
  return nowIso;
}

/**
 * Facebook search stub. Real implementation would call Graph API endpoints.
 * Only returns empty array unless a token is present; logic can be extended.
 */
async function facebookSearch(q, opts = {}) {
  if (!facebook.token) return [];
  // Placeholder: In a real scenario call Graph API.
  return [];
}

/**
 * Fetch JSON with timeout.
 */
async function safeFetchJson(url, timeoutMs) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { signal: controller.signal });
    if (!res.ok) {
      return null;
    }
    return await res.json();
  } catch (e) {
    return null;
  } finally {
    clearTimeout(id);
  }
}

/**
 * Deduplicate results by URL (case-insensitive) preserving first occurrence.
 */
function dedupe(results) {
  const seen = new Set();
  const out = [];
  for (const r of results) {
    const key = r.url.toLowerCase();
    if (key && !seen.has(key)) {
      seen.add(key);
      out.push(r);
    }
  }
  return out;
}

/**
 * Unified search entry point.
 * @param {string} q
 * @param {Object} opts
 * @param {string[]} [opts.sources] - subset of ['google','facebook']
 * @param {number} [opts.timeoutMs]
 * @returns {Promise<NormalizedResult[]>}
 */
async function unifiedSearch(q, opts = {}) {
  if (!q || typeof q !== 'string') return [];
  const sources = (opts.sources && opts.sources.length ? opts.sources : defaults.sources)
    .filter(s => ['google', 'facebook'].includes(s));
  const tasks = sources.map(src => {
    if (src === 'google') return googleSearch(q, opts);
    if (src === 'facebook') return facebookSearch(q, opts);
    return Promise.resolve([]);
  });
  const nested = await Promise.all(tasks);
  let combined = nested.flat();
  combined = dedupe(combined);
  combined.sort((a, b) => (b.publishedAt || '').localeCompare(a.publishedAt || ''));
  return combined;
}

module.exports = { unifiedSearch, googleSearch, facebookSearch, dedupe };
