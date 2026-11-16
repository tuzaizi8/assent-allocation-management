// 两个资料表单的"能渲染"回归测试:纯 schema 单测抓不到"组件用错 context"这类错
// (实测踩过:表单末尾裸用 FormDescription,它内部 useFormField() 找不到 FormField 直接抛错)。
import type { Profile } from '@/features/profile/api/profile';
import { ProfileInfoForm } from '@/features/profile/components/profile-info-form';
import { ProfilePasswordForm } from '@/features/profile/components/profile-password-form';
import { createUser, renderApp, screen } from '@/testing/test-utils';

const PROFILE: Profile = {
  userName: 'me@example.com',
  nickName: '小明',
  email: 'me@example.com',
  phonenumber: '13800000000',
  role: 'USER',
  createTime: '2026-01-01T00:00:00',
  loginDate: '2026-09-01T00:00:00',
  pwdUpdateDate: null,
};

test('基本资料表单渲染:带出昵称/手机号,邮箱是只读且注明原因', async () => {
  await renderApp(<ProfileInfoForm profile={PROFILE} />, {
    user: await createUser(),
  });

  expect(await screen.findByLabelText('昵称')).toHaveValue('小明');
  expect(screen.getByLabelText('手机号')).toHaveValue('13800000000');
  const email = screen.getByLabelText('邮箱');
  expect(email).toHaveValue('me@example.com');
  expect(email).toBeDisabled();
  expect(screen.getByText('邮箱是登录账号,暂不支持修改')).toBeInTheDocument();
});

test('修改密码表单渲染:三个密码框 + 表单级说明(不依赖 FormField context)', async () => {
  await renderApp(<ProfilePasswordForm />, { user: await createUser() });

  expect(await screen.findByLabelText('原密码')).toBeInTheDocument();
  expect(screen.getByLabelText('新密码')).toBeInTheDocument();
  expect(screen.getByLabelText('确认新密码')).toBeInTheDocument();
  expect(
    screen.getByText('修改成功后当前登录会失效,需要用新密码重新登录'),
  ).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /修改密码/ })).toBeInTheDocument();
});
