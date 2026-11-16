// 个人资料表单 schema 单测:只钉"前后端同口径"的校验规则,不渲染 Radix(避免 jsdom 交互坑)。
// 前端拦是为了即时反馈;真正的防线在后端 ProfileUpdateModel / PasswordUpdateModel 那一次(见 tests/test_profile.py)。
import { describe, expect, test } from 'vitest';

import { passwordSchema, profileSchema } from '@/features/profile/api/profile';

describe('profileSchema(与后端 ProfileUpdateModel 同口径)', () => {
  test('昵称必填且最多 30 字', () => {
    expect(profileSchema.safeParse({ nickName: '' }).success).toBe(false);
    expect(profileSchema.safeParse({ nickName: 'x'.repeat(31) }).success).toBe(
      false,
    );
    expect(profileSchema.safeParse({ nickName: '小明' }).success).toBe(true);
  });

  test('手机号可空,超过 11 位报错', () => {
    expect(
      profileSchema.safeParse({ nickName: '小明', phonenumber: '' }).success,
    ).toBe(true);
    expect(
      profileSchema.safeParse({ nickName: '小明', phonenumber: '13800000000' })
        .success,
    ).toBe(true);
    expect(
      profileSchema.safeParse({ nickName: '小明', phonenumber: '1'.repeat(12) })
        .success,
    ).toBe(false);
  });
});

describe('passwordSchema(与后端 PasswordUpdateModel 同口径)', () => {
  test('两次输入的新密码必须一致', () => {
    const result = passwordSchema.safeParse({
      oldPassword: 'old123',
      newPassword: 'new12345',
      confirmPassword: 'new54321',
    });
    expect(result.success).toBe(false);
    // 报错要落在确认框上,否则用户不知道该改哪个
    expect(result.error?.issues[0]?.path).toEqual(['confirmPassword']);
  });

  test('新密码不能与原密码相同', () => {
    const result = passwordSchema.safeParse({
      oldPassword: 'same123',
      newPassword: 'same123',
      confirmPassword: 'same123',
    });
    expect(result.success).toBe(false);
    expect(result.error?.issues.map((issue) => issue.path[0])).toContain(
      'newPassword',
    );
  });

  test('新密码至少 5 位', () => {
    expect(
      passwordSchema.safeParse({
        oldPassword: 'old123',
        newPassword: 'abc',
        confirmPassword: 'abc',
      }).success,
    ).toBe(false);
    expect(
      passwordSchema.safeParse({
        oldPassword: 'old123',
        newPassword: 'abcde',
        confirmPassword: 'abcde',
      }).success,
    ).toBe(true);
  });
});
