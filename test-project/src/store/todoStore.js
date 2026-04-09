const crypto = require('crypto');

const todos = new Map();

function getAll() {
  return Array.from(todos.values());
}

function getById(id) {
  return todos.get(id) || null;
}

function create(title) {
  const todo = {
    id: crypto.randomUUID(),
    title,
    completed: false,
    created_at: new Date().toISOString(),
  };
  todos.set(todo.id, todo);
  return todo;
}

function update(id, data) {
  const todo = todos.get(id);
  if (!todo) return null;

  if (data.title !== undefined) todo.title = data.title;
  if (data.completed !== undefined) todo.completed = data.completed;

  todos.set(id, todo);
  return todo;
}

function remove(id) {
  return todos.delete(id);
}

module.exports = { getAll, getById, create, update, remove };
