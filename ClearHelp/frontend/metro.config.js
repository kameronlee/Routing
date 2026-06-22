const { getDefaultConfig } = require('expo/metro-config');
const ensureRoutingBackend = require('./scripts/start-routing-backend');

ensureRoutingBackend().catch((error) => {
  console.warn(`[routing-backend] ${error.message}`);
});

module.exports = getDefaultConfig(__dirname);
