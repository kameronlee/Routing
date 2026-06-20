const { spawn } = require('child_process');
const http = require('http');
const path = require('path');

const STARTED_KEY = '__routingBackendAutostarted';
const DEFAULT_PORT = 8000;

function repoRoot() {
  return path.resolve(__dirname, '..', '..', '..');
}

function configuredPort() {
  const rawUrl = process.env.EXPO_PUBLIC_ROUTING_API_URL || `http://127.0.0.1:${DEFAULT_PORT}`;
  try {
    const parsed = new URL(rawUrl);
    return Number(parsed.port || DEFAULT_PORT);
  } catch (_error) {
    return DEFAULT_PORT;
  }
}

function localBaseUrl(port) {
  return `http://127.0.0.1:${port}`;
}

function requestJson(url, timeoutMs = 1000) {
  return new Promise((resolve, reject) => {
    const request = http.get(url, { timeout: timeoutMs }, (response) => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', (chunk) => {
        body += chunk;
      });
      response.on('end', () => {
        if (response.statusCode < 200 || response.statusCode >= 300) {
          reject(new Error(`HTTP ${response.statusCode}`));
          return;
        }
        try {
          resolve(body ? JSON.parse(body) : {});
        } catch (_error) {
          resolve({});
        }
      });
    });

    request.on('timeout', () => {
      request.destroy(new Error('request timed out'));
    });
    request.on('error', reject);
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForHealth(baseUrl) {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    try {
      await requestJson(`${baseUrl}/health`, 750);
      return true;
    } catch (_error) {
      await sleep(500);
    }
  }
  return false;
}

async function logDataStatus(baseUrl) {
  try {
    const status = await requestJson(`${baseUrl}/data/status`, 3000);
    const lidarReady = Boolean(status.dem_exists && status.canopy_raster_count > 0);
    const strictReady = Boolean(status.strict_real_ready);
    const canopyProducts = status.canopy_raster_count || 0;
    const lidarTilesProcessed = status.lidar_tiles_processed ?? 0;
    const lidarTilesDownloaded = status.lidar_tiles_downloaded ?? 0;
    console.log(
      `[routing-backend] LiDAR status: dem=${status.dem_exists ? 'yes' : 'no'}, ` +
        `canopy_products=${canopyProducts}, ` +
        `lidar_tiles_processed=${lidarTilesProcessed}, ` +
        `lidar_tiles_downloaded=${lidarTilesDownloaded}, ` +
        `strict_real_ready=${strictReady ? 'yes' : 'no'}`
    );
    if (!lidarReady || !strictReady) {
      const missing = Array.isArray(status.missing_required_layers)
        ? status.missing_required_layers.join('; ')
        : 'unknown required layer';
      console.warn(`[routing-backend] Real-data routing is not fully ready: ${missing}`);
    }
  } catch (error) {
    console.warn(`[routing-backend] Could not read /data/status: ${error.message}`);
  }
}

function spawnBackend(port) {
  const root = repoRoot();
  const python = process.env.ROUTING_BACKEND_PYTHON || process.env.PYTHON || 'python';
  const srcPath = path.join(root, 'src');
  const pythonPath = [srcPath, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter);
  const env = {
    ...process.env,
    PYTHONPATH: pythonPath,
    ROUTING_HOST: process.env.ROUTING_HOST || '0.0.0.0',
    ROUTING_PORT: process.env.ROUTING_PORT || String(port),
    ROUTING_PRELOAD_LOCAL_GRAPH: process.env.ROUTING_PRELOAD_LOCAL_GRAPH || '0',
  };
  const child = spawn(python, ['scripts/run_dev_server.py'], {
    cwd: root,
    env,
    stdio: 'ignore',
    windowsHide: true,
  });
  const stdoutLog = path.relative(process.cwd(), path.join(root, 'devserver.log'));
  const stderrLog = path.relative(process.cwd(), path.join(root, 'devserver.err.log'));
  console.log(
    `[routing-backend] starting FastAPI on ${localBaseUrl(port)} ` +
      `(host ${env.ROUTING_HOST}; logs: ${stdoutLog}, ${stderrLog})`
  );

  let exiting = false;
  const stop = () => {
    exiting = true;
    if (!child.killed) {
      child.kill();
    }
  };
  process.once('exit', stop);
  process.once('SIGINT', () => {
    stop();
    process.exit(130);
  });
  process.once('SIGTERM', () => {
    stop();
    process.exit(143);
  });
  child.once('exit', (code, signal) => {
    if (!exiting && code !== 0) {
      console.warn(`[routing-backend] backend process exited with code=${code} signal=${signal || 'none'}`);
    }
  });
}

async function ensureRoutingBackend() {
  if (process.env.EXPO_SKIP_ROUTING_BACKEND === '1' || process.env.EXPO_ROUTING_BACKEND_AUTOSTART === '0') {
    return;
  }
  if (global[STARTED_KEY]) {
    return;
  }
  global[STARTED_KEY] = true;

  const port = configuredPort();
  const baseUrl = localBaseUrl(port);
  try {
    await requestJson(`${baseUrl}/health`, 750);
    console.log(`[routing-backend] already running at ${baseUrl}`);
    await logDataStatus(baseUrl);
    return;
  } catch (_error) {
    spawnBackend(port);
  }

  if (await waitForHealth(baseUrl)) {
    console.log(`[routing-backend] ready at ${baseUrl}`);
    await logDataStatus(baseUrl);
  } else {
    console.warn(`[routing-backend] FastAPI did not answer /health yet. Check devserver.err.log.`);
  }
}

module.exports = ensureRoutingBackend;

if (require.main === module) {
  ensureRoutingBackend().catch((error) => {
    console.error(`[routing-backend] ${error.stack || error.message}`);
    process.exitCode = 1;
  });
}
