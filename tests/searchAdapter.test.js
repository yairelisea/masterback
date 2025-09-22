// tests/searchAdapter.test.js
// Jest tests for searchAdapter service.

/* eslint-disable no-undef */

// Ensure env vars before importing module
process.env.GOOGLE_SEARCH_API_KEY = 'test-key';
process.env.GOOGLE_SEARCH_CX = 'test-cx';

const fetchMock = jest.fn();
jest.mock('node-fetch', () => fetchMock);

describe('searchAdapter', () => {
  beforeEach(() => {
    fetchMock.mockReset();
    jest.resetModules();
  });

  test('unifiedSearch (google) returns normalized, deduped & sorted results', async () => {
    // Arrange mocked Google API response
    const payload = {
      items: [
        {
          title: 'Result A',
          link: 'https://example.com/a',
          snippet: 'Snippet A',
          pagemap: { metatags: [{ 'article:published_time': '2024-02-01T10:00:00Z' }] },
        },
        {
          title: 'Result B',
            link: 'https://example.com/b',
            snippet: 'Snippet B',
            pagemap: { metatags: [{ 'article:published_time': '2024-01-15T10:00:00Z' }] },
        },
        {
          title: 'Duplicate A later in list',
          link: 'https://example.com/a', // duplicate link
          snippet: 'Snippet A2',
          pagemap: { metatags: [{ 'article:published_time': '2024-03-01T10:00:00Z' }] },
        },
      ],
    };

    fetchMock.mockResolvedValue({ ok: true, json: async () => payload });

    const { unifiedSearch } = require('../src/services/searchAdapter');

    // Act
    const results = await unifiedSearch('example query', { sources: ['google'] });

    // Assert
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(results).toHaveLength(2); // duplicate removed
    expect(results[0].url).toBe('https://example.com/a'); // Should keep first occurrence despite later newer date for duplicate
    expect(results[0]).toMatchObject({ source: 'google', title: 'Result A' });
    expect(results[1].url).toBe('https://example.com/b');
    // Dates are ISO strings
    results.forEach(r => expect(typeof r.publishedAt).toBe('string'));
  });

  test('unifiedSearch with facebook only (no token) returns empty', async () => {
    const { unifiedSearch } = require('../src/services/searchAdapter');
    const results = await unifiedSearch('q', { sources: ['facebook'] });
    expect(results).toEqual([]);
  });

  test('unifiedSearch invalid query returns []', async () => {
    const { unifiedSearch } = require('../src/services/searchAdapter');
    const results = await unifiedSearch(null);
    expect(results).toEqual([]);
  });
});
