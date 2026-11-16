import { motion, useReducedMotion } from 'motion/react';

import { EmptyStateArt } from '@/components/shared/empty-state-art';
import { Link } from '@/components/ui/link';
import { paths } from '@/config/paths';

export default function NotFoundRoute() {
  const reduceMotion = useReducedMotion();

  return (
    <motion.div
      className="flex h-screen flex-col items-center justify-center gap-3 px-6 text-center font-semibold"
      initial={reduceMotion ? false : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
    >
      <EmptyStateArt className="h-14 w-24" />
      <h1>404 - Not Found</h1>
      <p>Sorry, the page you are looking for does not exist.</p>
      <Link to={paths.home.getHref()}>Go to Home</Link>
    </motion.div>
  );
}
