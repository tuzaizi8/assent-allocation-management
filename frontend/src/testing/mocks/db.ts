import { factory, primaryKey } from '@mswjs/data';
import { nanoid } from 'nanoid';

// ① 定义数据模型(对应后端的 ORM 模型)
const models = {
  user: {
    id: primaryKey(nanoid),
    firstName: String,
    lastName: String,
    email: String,
    password: String,
    teamId: String,
    role: String,
    permissions: Array, // 新增：权限标识数组
    bio: String,
    createdAt: Date.now,
  },
  team: {
    id: primaryKey(nanoid),
    name: String,
    description: String,
    createdAt: Date.now,
  },
};

// ② 创建 DB 实例
export const db = factory(models);

export type Model = keyof typeof models;

const dbFilePath = 'mocked-db.json';

// ③ 加载 DB(从文件或 localStorage)
export const loadDb = async () => {
  // 测试环境:返回空 db（测试数据由 test-utils 的 createUser 写入）
  // 避免 localStorage 残留开发环境种子数据导致测试间数据串味
  if (import.meta.env.TEST) return {};

  if (typeof window === 'undefined') {
    // Node 环境:从文件读取
    const { readFile, writeFile } = await import('fs/promises');
    try {
      const data = await readFile(dbFilePath, 'utf8');
      return JSON.parse(data);
    } catch (error: any) {
      if (error?.code === 'ENOENT') {
        const emptyDB = {};
        await writeFile(dbFilePath, JSON.stringify(emptyDB, null, 2));
        return emptyDB;
      } else {
        console.error('Error loading mocked DB:', error);
        return null;
      }
    }
  }
  // 浏览器环境:优先从 localStorage 读取(运行时持久化)
  const stored = window.localStorage.getItem('msw-db');
  if (stored) {
    return JSON.parse(stored);
  }
  // 首次加载:fetch mocked-db.json 种子数据
  try {
    const res = await fetch('/mocked-db.json');
    if (res.ok) {
      const data = await res.json();
      window.localStorage.setItem('msw-db', JSON.stringify(data));
      return data;
    }
  } catch (e) {
    console.warn('[MSW] Failed to load mocked-db.json seed:', e);
  }
  return {};
};

// ④ 存储 DB(到文件或 localStorage)
export const storeDb = async (data: string) => {
  if (typeof window === 'undefined') {
    const { writeFile } = await import('fs/promises');
    await writeFile(dbFilePath, data);
  } else {
    window.localStorage.setItem('msw-db', data);
  }
};

// ⑤ 持久化单个 model(handler 写入后调用)
export const persistDb = async (model: Model) => {
  if (process.env.NODE_ENV === 'test') return;
  const data = await loadDb();
  data[model] = db[model].getAll();
  await storeDb(JSON.stringify(data));
};

// ⑥ 初始化 DB(setup-tests.ts 的 beforeEach 调用)
export const initializeDb = async () => {
  const database = await loadDb();
  Object.entries(db).forEach(([key, model]) => {
    const dataEntres = database[key];
    if (dataEntres) {
      dataEntres?.forEach((entry: Record<string, any>) => {
        model.create(entry);
      });
    }
  });
};

// ⑦ 重置 DB(setup-tests.ts 的 afterEach 调用)
//    清空 localStorage + 清空 @mswjs/data 内存数据（防止测试间数据串味）
export const resetDb = () => {
  window.localStorage.clear();
  Object.values(db).forEach((model: any) => {
    model.deleteMany({ where: {} });
  });
};
