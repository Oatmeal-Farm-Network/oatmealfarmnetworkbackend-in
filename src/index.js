// src/index.js
import 'dotenv/config';
import express from 'express';
import cors from 'cors';
import helmet from 'helmet';
import path from 'path';
import { fileURLToPath } from 'url';

import { getPool, query } from './db/pool.js';
import plantTypesRoutes from './routes/plantType.routes.js';
import contactRoutes from './routes/contact.js';
import authRoutes from './routes/auth.routes.js';
import newsRoutes from './routes/news.routes.js';
import adminRoutes from './routes/admin.routes.js';
import dataRoutes from './routes/data.routes.js';
import projectRoutes from './routes/project.routes.js';
import timeRoutes from './routes/time.routes.js';
import artemisRoutes from './routes/artemis.routes.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

console.log('[boot] NODE_ENV =', process.env.NODE_ENV);

const app = express();

const allowedOrigins = [
  'http://localhost:8080',
  'http://localhost:5173',
  'https://oatmeal-main-802455386518.us-central1.run.app',
  'https://oatmealfarmnetwork.com',
  'https://www.oatmealfarmnetwork.com',
];

app.use(cors({
  origin: (origin, callback) => {
    // Allow requests with no origin (mobile apps, curl, etc.)
    if (!origin) return callback(null, true);
    if (allowedOrigins.includes(origin)) return callback(null, true);
    // In production, also allow same-origin requests
    if (process.env.NODE_ENV === 'production') return callback(null, true);
    callback(new Error('Not allowed by CORS'));
  },
  credentials: true,
  methods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
  allowedHeaders: ['Content-Type', 'Authorization'],
}));
app.use(helmet({ contentSecurityPolicy: false }));
app.use(express.json({ limit: '25mb' }));

app.get('/health', (_req, res) => res.json({ ok: true, service: 'api', time: new Date().toISOString() }));
app.get('/db-ping', async (_req, res) => {
  try { const r = await query('SELECT 1 AS ok'); res.json({ ok: true, result: r.recordset }); }
  catch (err) { res.status(500).json({ ok: false, error: err?.message }); }
});

// Mount ALL routes
app.use('/api/plant-types', plantTypesRoutes);
app.use('/api', contactRoutes);
app.use('/auth', authRoutes);
app.use('/api/news', newsRoutes);
app.use('/api/admin', adminRoutes);
app.use('/api/data', dataRoutes);
app.use('/api/projects', projectRoutes);
app.use('/api/time', timeRoutes);
app.use('/api/artemis', artemisRoutes);

if (process.env.NODE_ENV === 'production') {
  const publicDir = path.join(__dirname, '../public');
  app.use(express.static(publicDir));
  app.get('/{*path}', (req, res) => {
    const indexPath = path.join(publicDir, 'index.html');
    res.sendFile(indexPath, (err) => {
      if (err) { res.status(404).send(`index.html not found at: ${indexPath}`); }
    });
  });
}

app.use((err, _req, res, _next) => {
  console.error('[api] Unhandled error:', err);
  res.status(500).json({ error: 'Internal Server Error', detail: err?.message });
});

const PORT = process.env.PORT || 3001;
getPool()
  .then(() => { console.log('✅ Connected to GCP Cloud SQL.'); app.listen(PORT, () => console.log(`✅ API running at http://localhost:${PORT}`)); })
  .catch((err) => { console.error('❌ Cannot start:', err?.message); process.exit(1); });
