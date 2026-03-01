/**
 * Greets a person by name.
 * @param {string} name
 * @returns {string}
 */
function greet(name) {
  return 'Hello, ' + name;
}

/**
 * A simple HTTP router.
 */
class Router {
  /** Register a GET handler. */
  get(path, handler) {}

  /** Register a POST handler. */
  post(path, handler) {}
}

const VERSION = "2.0.0";

module.exports = { greet, Router, VERSION };

/** Helper utility. */
module.exports.helper = function helper(x) { return x; };

/** Direct exports assignment. */
exports.util = function util(y) { return y; };
