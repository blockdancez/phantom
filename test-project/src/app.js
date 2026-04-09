const express = require('express');
const { httpLogger } = require('./logger');
const todosRouter = require('./routes/todos');

const app = express();

app.use(express.json());
app.use(httpLogger);
app.use('/todos', todosRouter);

module.exports = app;
