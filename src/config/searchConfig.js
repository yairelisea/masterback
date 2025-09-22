// searchConfig.js
// Centralized configuration for search adapters. Reads from process.env only once.

const searchConfig = {
  google: {
    apiKey: process.env.GOOGLE_SEARCH_API_KEY || '',
    cx: process.env.GOOGLE_SEARCH_CX || '',
    // Max results per single Google Custom Search API request
    pageSize: 10,
  },
  facebook: {
    token: process.env.FACEBOOK_GRAPH_TOKEN || '',
  },
  defaults: {
    sources: ['google'],
    timeoutMs: 10000,
  },
};

function validateConfig() {
  if (!searchConfig.google.apiKey || !searchConfig.google.cx) {
    // Do not throw here; allow runtime to decide. Just warn.
    // eslint-disable-next-line no-console
    console.warn('[searchConfig] Missing GOOGLE_SEARCH_API_KEY or GOOGLE_SEARCH_CX');
  }
}

validateConfig();

module.exports = searchConfig;
