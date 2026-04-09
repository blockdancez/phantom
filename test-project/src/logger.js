const pino = require('pino');
const pinoHttp = require('pino-http');

const logger = pino({
  level: process.env.LOG_LEVEL || 'info',
  timestamp: pino.stdTimeFunctions.isoTime,
  formatters: {
    level(label) {
      return { level: label };
    },
  },
});

const httpLogger = pinoHttp({
  logger,
  customSuccessMessage(req, res) {
    return `${req.method} ${req.url} completed`;
  },
  customErrorMessage(req, res, err) {
    return `${req.method} ${req.url} failed`;
  },
  customAttributeKeys: {
    req: 'request',
    res: 'response',
    responseTime: 'duration_ms',
  },
});

module.exports = { logger, httpLogger };
