import { AppRouter } from '@/app/router';

import { AppProvider } from './provider';

export const App = () => {
  return (
    <AppProvider>
      <AppRouter />
    </AppProvider>
  );
};
