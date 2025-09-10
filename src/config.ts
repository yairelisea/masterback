import 'dotenv/config';

export const config = {
  port: Number(process.env.PORT ?? 8080),
  corsOrigin: process.env.CORS_ORIGIN ?? '*',
  dbUrl: process.env.DATABASE_URL ?? 'file:./dev.db',
  openaiApiKey: process.env.OPENAI_API_KEY ?? '',
  newsMaxResults: Number(process.env.NEWS_MAX_RESULTS ?? 35),
  defaultNewsWindowDays: Number(process.env.DEFAULT_NEWS_WINDOW_DAYS ?? 7),
  timezone: process.env.TIMEZONE ?? 'America/Monterrey',
};
