import express from 'express';
import cors from 'cors';
import helmet from 'helmet';
import { config } from './config.js';
import { logger } from './logger.js';
import { health } from './routes/health.js';
import { campaigns } from './routes/campaigns.js';
import { search } from './routes/search.js';
import { links } from './routes/links.js';
import { startScheduler } from './scheduler.js';

const app = express();
app.use(helmet());
app.use(cors({ origin: config.corsOrigin, credentials: true }));
app.use(express.json({ limit: '2mb' }));

app.use('/api/health', health);
app.use('/api/campaigns', campaigns);
app.use('/api/search', search);
app.use('/api/links', links);

// 404
app.use((req, res) => res.status(404).json({ error: 'Not Found' }));

app.listen(config.port, () => {
  logger.info(`BBX backend running on :${config.port}`);
});

startScheduler();
