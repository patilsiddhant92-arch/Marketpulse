import js from '@eslint/js';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';
import tseslint from 'typescript-eslint';

// Pre-rebuild code (legacy workspaces). Linted for nothing until each tab
// migrates and the file is deleted — see src/routes/legacy.tsx.
const LEGACY = ['src/components/**', 'src/utils/**', 'src/types.ts'];

const HEX = '/#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\\b/';
const HEX_MESSAGE =
  'Raw hex colours are banned — use a design token (tailwind: bg-surface, text-up, … or rgb(var(--c-x))). Tokens live in src/styles/tokens.css.';

export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'src/api/types.gen.ts', ...LEGACY] },
  {
    files: ['src/**/*.{ts,tsx}'],
    extends: [js.configs.recommended, ...tseslint.configs.recommended, reactHooks.configs.flat.recommended],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    rules: {
      'no-restricted-syntax': [
        'error',
        { selector: `Literal[value=${HEX}]`, message: HEX_MESSAGE },
        { selector: `TemplateElement[value.raw=${HEX}]`, message: HEX_MESSAGE },
      ],
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      '@typescript-eslint/no-explicit-any': 'error',
    },
  },
  {
    // Tests may use hex fixtures and looser typing.
    files: ['src/**/*.test.{ts,tsx}', 'src/test/**'],
    rules: { 'no-restricted-syntax': 'off' },
  },
);
