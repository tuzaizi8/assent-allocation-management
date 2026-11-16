const path = require('path');
const fs = require('fs');

// 扫描 src/features 目录，作为组件归属的可选项
const featuresDir = path.join(process.cwd(), 'src/features');
const features = fs.readdirSync(featuresDir);

/**
 *
 * @type {import('plop').PlopGenerator}
 */
module.exports = {
  description: 'Component Generator',
  prompts: [
    {
      type: 'input',
      name: 'name',
      message: 'component name',
    },
    {
      type: 'list',
      name: 'feature',
      message: 'Which feature does this component belong to?',
      choices: ['components', ...features],
      when: () => features.length > 0,
    },
    {
      type: 'input',
      name: 'folder',
      message: 'folder in components',
      when: ({ feature }) => !feature || feature === 'components',
    },
  ],
  actions: (answers) => {
    // 共享组件放 src/components/{{folder}}，业务组件放 src/features/{{feature}}/components
    const componentGeneratePath =
        !answers.feature || answers.feature === 'components'
            ? 'src/components/{{folder}}'
            : 'src/features/{{feature}}/components';
    return [
      // 生成 index.ts（barrel 导出）
      {
        type: 'add',
        path: componentGeneratePath + '/{{kebabCase name}}/index.ts',
        templateFile: 'generators/component/index.ts.hbs',
      },
      // 生成组件本体 user-profile.tsx
      {
        type: 'add',
        path: componentGeneratePath + '/{{kebabCase name}}/{{kebabCase name}}.tsx',
        templateFile: 'generators/component/component.tsx.hbs',
      },
      // 生成 Storybook 故事 user-profile.stories.tsx
      {
        type: 'add',
        path: componentGeneratePath + '/{{kebabCase name}}/{{kebabCase name}}.stories.tsx',
        templateFile: 'generators/component/component.stories.tsx.hbs',
      },
    ];
  },
};