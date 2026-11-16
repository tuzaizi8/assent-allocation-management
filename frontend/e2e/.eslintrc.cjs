module.exports = {
  extends: ['plugin:playwright/recommended'],
  parserOptions: { ecmaVersion: 'latest', sourceType: 'module' },
  overrides: [
    {
      files: ['**/*.ts', '**/*.tsx'],
      parser: '@typescript-eslint/parser',
    },
  ],
  rules: {
    // e2e 用 Playwright,不是 Testing Library / Vitest
    'testing-library/no-container': 'off',
    'testing-library/no-debugging-utils': 'off',
    'testing-library/no-dom-import': 'off',
    'testing-library/prefer-screen-queries': 'off',
    'testing-library/prefer-presence-queries': 'off',
    'vitest/expect-expect': 'off',
    'vitest/no-focused-tests': 'off',
    'vitest/identical-title': 'off',
  },
};
