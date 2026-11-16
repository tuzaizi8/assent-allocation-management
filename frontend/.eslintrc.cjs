module.exports = {
    root: true, // 标记根配置，ESLint 向上查找时停止于此
    env: {
        node: true, // 启用 Node.js 全局变量（process、Buffer 等）
        es6: true, // 启用 ES6 全局变量（Promise、Symbol 等）
    },
    parserOptions: { ecmaVersion: 'latest', sourceType: 'module' },
    // 忽略目录：依赖、MSW worker、plop 生成器模板
    ignorePatterns: ['node_modules/*', 'public/mockServiceWorker.js', 'generators/*'],
    extends: ['eslint:recommended'], // 基础推荐规则
    plugins: ['check-file'],
    overrides: [
        {
            // 仅对 TS/TSX 文件应用以下配置
            files: ['**/*.ts', '**/*.tsx'],
            parser: '@typescript-eslint/parser', // 用 TS 解析器替代默认 espree
            settings: {
                react: { version: 'detect' }, // 自动探测 React 版本
                'import/resolver': { typescript: {} }, // import 解析走 tsconfig paths
            },
            env: { browser: true, node: true, es6: true },
            extends: [
                'eslint:recommended',
                'plugin:import/errors',
                'plugin:import/warnings',
                'plugin:import/typescript',
                'plugin:@typescript-eslint/recommended',
                'plugin:react/recommended',
                'plugin:react-hooks/recommended',
                'plugin:jsx-a11y/recommended',
                'plugin:prettier/recommended', // 必须放最后：关闭与 Prettier 冲突的规则
                'plugin:testing-library/react',
                'plugin:jest-dom/recommended',
                // tailwindcss 插件暂移除:eslint-plugin-tailwindcss@3.x 不支持 Tailwind v4,
                // v4 的 data-open:/ring-3/cn-font-heading 等类全会被 no-custom-classname 误报;
                // 待插件发布 v4 稳定支持后恢复
                'plugin:vitest/legacy-recommended',
            ],
            rules: {
                // 禁止跨 feature 导入（架构边界守护，核心规则）
                'import/no-restricted-paths': [
                    'error',
                    {
                        zones: [
                            // 例：features/discussions 不能 import features/comments
                            { target: './src/features/auth', from: './src/features', except: ['./auth'] },
                            { target: './src/features/comments', from: './src/features', except: ['./comments'] },
                            //单向数据流：app 可 import features，反之禁止
                            { target: './src/features', from: './src/app' },
                            // 共享层禁止反向依赖 features/app
                            {
                                target: ['./src/components', './src/hooks', './src/lib', './src/types', './src/utils'],
                                from: ['./src/features', './src/app'],
                            },
                        ],
                    },
                ],
                'import/no-cycle': 'error', // 禁止循环依赖
                'linebreak-style': ['error', 'unix'], // 统一 LF 换行
                'react/prop-types': 'off', // TS 已做类型校验，关闭 propTypes 检查
                // import 顺序：内置 > 外部 > 内部 > 父级 > 同级 > 索引，且组间空行 + 字母排序
                'import/order': [
                    'error',
                    {
                        groups: ['builtin', 'external', 'internal', 'parent', 'sibling', 'index', 'object'],
                        'newlines-between': 'always',
                        alphabetize: { order: 'asc', caseInsensitive: true },
                    },
                ],
                'react/react-in-jsx-scope': 'off', // React 17+ 不需要 import React
                '@typescript-eslint/no-unused-vars': ['error'], // 未使用变量报错
                '@typescript-eslint/no-explicit-any': ['off'], // 允许 any（脚手架阶段）
                // Prettier 规则作为 ESLint 规则运行，读取 .prettierrc
                'prettier/prettier': ['error', {}, { usePrettierrc: true }],
                // 强制文件名 kebab-case（如 user-profile.tsx）
                'check-file/filename-naming-convention': [
                    'error',
                    { '**/*.{ts,tsx}': 'KEBAB_CASE' },
                    { ignoreMiddleExtensions: true },
                ],
            },
        },
        {
            // shadcn v4 官方平铺组件的 a11y 已知误报豁免(官方范式:children 经 props 透传/
            // cmdk 样式钩子属性/受控 div 交互),只匹配平铺文件不进 legacy 等子目录
            files: ['src/components/ui/*.tsx'],
            rules: {
                'jsx-a11y/click-events-have-key-events': 'off',
                'jsx-a11y/no-noninteractive-element-interactions': 'off',
                'jsx-a11y/anchor-has-content': 'off',
                'jsx-a11y/heading-has-content': 'off',
            },
        },
        {
            // 非测试目录强制文件夹名 kebab-case
            plugins: ['check-file'],
            files: ['src/**/!(__tests__)/*'],
            rules: {
                'check-file/folder-naming-convention': ['error', { '**/*': 'KEBAB_CASE' }],
            },
        },
    ],
};