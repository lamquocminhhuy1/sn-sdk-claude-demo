# ServiceNow Scoped App - Claude Demo

## Project Overview

This is a ServiceNow scoped app project managed with the ServiceNow SDK (snc CLI).

## Configuration

- **App Scope:** x_demo_claude_app
- **Platform Version:** Xanadu
- **Tooling:** ServiceNow SDK (`snc` CLI)

## Coding Standards

All server-side scripts must be ES5 compatible JavaScript.

### Rules

- Do not use arrow functions (`=>`) in server-side scripts
- Do not use template literals (backtick strings) in server-side scripts
- Use `function` keyword for all function declarations and expressions
- Use string concatenation (`+`) instead of template literals
- Use `var` for variable declarations (avoid `let`/`const` in server-side scripts)

### Examples

```javascript
// WRONG - not ES5 compatible
var greet = (name) => `Hello, ${name}`;

// CORRECT - ES5 compatible
var greet = function(name) {
    return 'Hello, ' + name;
};
```
