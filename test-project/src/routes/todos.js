const { Router } = require('express');
const store = require('../store/todoStore');
const { logger } = require('../logger');

const router = Router();

router.get('/', (req, res) => {
  const todos = store.getAll();
  logger.info({ count: todos.length }, 'fetched all todos');
  res.json(todos);
});

router.post('/', (req, res) => {
  const { title } = req.body;
  if (!title || typeof title !== 'string' || title.trim() === '') {
    logger.warn({ body: req.body }, 'create todo failed: title is required');
    return res.status(400).json({ error: 'title is required' });
  }
  const todo = store.create(title.trim());
  logger.info({ todoId: todo.id }, 'todo created');
  res.status(201).json(todo);
});

router.get('/:id', (req, res) => {
  const todo = store.getById(req.params.id);
  if (!todo) {
    logger.warn({ todoId: req.params.id }, 'todo not found');
    return res.status(404).json({ error: 'todo not found' });
  }
  res.json(todo);
});

router.put('/:id', (req, res) => {
  const todo = store.update(req.params.id, req.body);
  if (!todo) {
    logger.warn({ todoId: req.params.id }, 'update failed: todo not found');
    return res.status(404).json({ error: 'todo not found' });
  }
  logger.info({ todoId: todo.id }, 'todo updated');
  res.json(todo);
});

router.delete('/:id', (req, res) => {
  const removed = store.remove(req.params.id);
  if (!removed) {
    logger.warn({ todoId: req.params.id }, 'delete failed: todo not found');
    return res.status(404).json({ error: 'todo not found' });
  }
  logger.info({ todoId: req.params.id }, 'todo deleted');
  res.status(204).end();
});

module.exports = router;
